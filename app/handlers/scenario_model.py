# app/handlers/scenario_model.py
from __future__ import annotations

import asyncio
import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.validators import MAX_TEXT_LEN, is_text_too_long
from app.keyboards.menu import MenuCallbacks, photo_menu_kb
from app.keyboards.extra import buy_generations_kb
from app.keyboards.confirm import yes_no_kb, review_edit_kb, ConfirmCallbacks
from app.keyboards.feedback import feedback_kb
from app.repository.users import increment_generated_photos, upsert_user

# 1) В импортах добавь ensure_default_subscription:
from app.repository.generations import (
    ensure_default_subscription,  # ✅ NEW
    charge_photo_generation,
    refund_photo_generation,
    NoGenerationsLeft,
    is_launch_subscription,
)
from app.services.album_collector import AlbumCollector
from app.services.generation import generate_image_wavespeed_from_telegram
from app.services.wavespeed_ai import WaveSpeedError
from app.states.model_flow import ModelFlow
from app.states.feedback_flow import FeedbackFlow
from app.utils.tg_edit import edit_text_safe
from app.utils.content_media import send_content_album
from app.utils.tg_send import send_image_smart
from app.utils.support_text import with_support, launch_limits_message
from app.utils.launch_guard import block_launch_for_call
from app.utils.wavespeed_errors import wavespeed_error_to_user_text
from app.utils.generated_files import save_generated_image_bytes
from app.utils.progress_bar import (
    progress_initial_text,
    progress_loop,
    stop_progress,
)


router = Router()
logger = logging.getLogger(__name__)
_album = AlbumCollector(debounce_seconds=0.8)

MODEL_DESC_EXAMPLE = (
    "Отлично! 🛍✨\n\n"
    "Опиши, какой ты хочешь видеть модель 👇\n"
    "Пример: “Мужчина 25–35, студийный свет, белый фон, стиль casual, лёгкая улыбка, поза в пол-оборота”."
)

PRODUCT_ACTION_EXAMPLE = (
    "Класс! Фото товара получил ✅\n\n"
    "Теперь напиши, <b>что нужно сделать с товаром</b> 👇\n"
    "Примеры:\n"
    "— “Сделай крупный план товара в руке, чтобы были видны детали.”\n"
    "— “Товар должен быть на модели: портрет по плечи, естественный свет.”\n"
    "— “Покажи товар на белом фоне, как в каталоге, без лишних объектов.”\n"
    "— “Сделай акцент на принте/логотипе, высокая резкость.”"
)


@router.callback_query(F.data == MenuCallbacks.MODEL)
async def start_model_flow(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await call.answer()
    await upsert_user(session, call.from_user.id, call.from_user.username)
    if await block_launch_for_call(call, session, reply_markup=buy_generations_kb()):
        return

    await state.clear()
    await state.set_state(ModelFlow.model_desc)

    if call.message:
        # Убираем сообщение с welcome.png, чтобы не висело над альбомом
        try:
            await call.message.delete()
        except Exception:
            pass
        await send_content_album(
            call.message,
            filenames=["model_photo.jpeg", "model_photo1.jpg"],
            caption=MODEL_DESC_EXAMPLE,
            parse_mode="HTML",
        )


@router.message(ModelFlow.model_desc)
async def model_desc_in(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer(
            "Мне нужен текст 😊 Опиши модель словами, пожалуйста 🙌"
        )
        return

    desc = message.text.strip()

    if is_text_too_long(desc):
        await message.answer(
            f"Ой, текст слишком длинный 😅\n"
            f"Максимум {MAX_TEXT_LEN} символов, а у тебя {len(desc)}.\n"
            "Сократи, пожалуйста, и отправь ещё раз 🙌"
        )
        return

    await state.update_data(model_desc=desc)
    await state.set_state(ModelFlow.confirm_model_desc)

    await message.answer(
        f"Супер! 😊 Вот описание, как я понял модель:\n“{desc}”\n\nВсё верно? ✅",
        reply_markup=yes_no_kb(yes_text="✅ Да", no_text="✏️ Изменить"),
    )


@router.callback_query(ModelFlow.confirm_model_desc, F.data == ConfirmCallbacks.NO)
async def model_desc_edit(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(model_desc="")
    await state.set_state(ModelFlow.model_desc)

    await edit_text_safe(
        call,
        "Хорошо 😄 Тогда опиши модель заново 👇\n\n"
        + MODEL_DESC_EXAMPLE.split("\n\n", 1)[1],
        reply_markup=None,
    )
    await call.answer()


@router.callback_query(ModelFlow.confirm_model_desc, F.data == ConfirmCallbacks.YES)
async def model_desc_confirmed(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ModelFlow.product_photos)

    await edit_text_safe(
        call,
        "Отлично! Теперь пришли фото товара 📸\n"
        "Можно от 1 до 5 фото за один раз (одним сообщением/альбомом) 🙌",
        reply_markup=None,
    )
    await call.answer()


@router.message(ModelFlow.product_photos)
async def product_photos_in(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer(
            "Ой, кажется, это не то 😅\n"
            "Нужно отправить <b>от 1 до 5 фото</b> товара одним сообщением (альбомом) 📸\n"
            "Попробуй ещё раз 🙌"
        )
        return

    if not message.media_group_id:
        file_id = message.photo[-1].file_id
        await state.update_data(product_photos=[file_id])
        await state.set_state(ModelFlow.presentation_desc)

        await message.answer(
            PRODUCT_ACTION_EXAMPLE, reply_markup=None
        )
        return

    await _album.push(
        message.chat.id, message.media_group_id, message.photo[-1].file_id
    )
    result = await _album.collect(message.chat.id, message.media_group_id)

    if not result.file_ids:
        return

    if not (1 <= len(result.file_ids) <= 5):
        await message.answer(
            "Ой, тут должно быть <b>от 1 до 5 фото</b> одним сообщением. Попробуй ещё раз 📸🙌"
        )
        return

    await state.update_data(product_photos=result.file_ids)
    await state.set_state(ModelFlow.presentation_desc)

    await message.answer(
        PRODUCT_ACTION_EXAMPLE, reply_markup=None
    )


@router.message(ModelFlow.presentation_desc)
async def presentation_desc_in(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer(
            "Нужен текст ✍️ Напиши, что нужно сделать с товаром 👇"
        )
        return

    action_text = message.text.strip()

    if is_text_too_long(action_text):
        await message.answer(
            f"Ой, текст слишком длинный 😅\n"
            f"Максимум {MAX_TEXT_LEN} символов, а у тебя {len(action_text)}.\n"
            "Сократи, пожалуйста, и отправь ещё раз 🙌"
        )
        return

    await state.update_data(presentation_desc=action_text)
    await state.set_state(ModelFlow.review)

    data = await state.get_data()
    desc = data.get("model_desc", "")
    photos = data.get("product_photos", []) or []

    await message.answer(
        "Давай быстро проверим ✅😊\n\n"
        f"1) Описание модели: “{desc}”\n"
        f"2) Фото товара: {len(photos)} шт. 📸\n"
        f"3) Что сделать с товаром: “{action_text}”\n\n"
        "Всё верно?",
        reply_markup=review_edit_kb(),
    )


@router.callback_query(ModelFlow.review, F.data == ConfirmCallbacks.EDIT_MODEL)
async def review_edit_model(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(model_desc="")
    await state.set_state(ModelFlow.model_desc)

    await edit_text_safe(
        call,
        "Хорошо 😄 Меняем описание модели 👇\n\n"
        + MODEL_DESC_EXAMPLE.split("\n\n", 1)[1],
        reply_markup=None,
    )
    await call.answer()


@router.callback_query(ModelFlow.review, F.data == ConfirmCallbacks.EDIT_PHOTOS)
async def review_edit_photos(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(product_photos=[])
    await state.set_state(ModelFlow.product_photos)

    await edit_text_safe(
        call,
        "Хорошо 😄 Пришли фото товара заново (1–5 фото одним сообщением) 📸",
        reply_markup=None,
    )
    await call.answer()


@router.callback_query(ModelFlow.review, F.data == ConfirmCallbacks.EDIT_PRESENTATION)
async def review_edit_presentation(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(presentation_desc="")
    await state.set_state(ModelFlow.presentation_desc)

    await edit_text_safe(
        call,
        "Хорошо 😊 Напиши заново, что нужно сделать с товаром 👇\n\n"
        + PRODUCT_ACTION_EXAMPLE,
        reply_markup=None,
    )
    await call.answer()


# ✅ FIXED review_confirmed (версия A: списание по users.id, но ensure_default_subscription ждёт tg_id)
@router.callback_query(ModelFlow.review, F.data == ConfirmCallbacks.YES)
async def review_confirmed(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    model_desc: str = (data.get("model_desc") or "").strip()
    action_desc: str = (data.get("presentation_desc") or "").strip()
    product_photos: list[str] = data.get("product_photos", []) or []

    if not model_desc or not action_desc or not product_photos:
        await edit_text_safe(
            call,
            "Не вижу всех данных для генерации 😅\nДавай начнём заново: /start",
        )
        await call.answer()
        await state.clear()
        return

    await call.answer()
    if call.message is None:
        return

    progress_msg = await call.message.answer(progress_initial_text())
    stop = asyncio.Event()

    async def _update(text: str) -> None:
        try:
            await progress_msg.edit_text(text)
        except Exception:
            return

    progress_task = asyncio.create_task(progress_loop(_update, stop))

    # гарантируем пользователя
    user = await upsert_user(session, call.from_user.id, call.from_user.username)

    # ✅ ВАЖНО:
    # ensure_default_subscription(session, tg_id)  -> ждёт TG id (по твоему generations.py версии A)
    # charge_photo_generation(session, tg_id)     -> ждёт TG id (по твоему generations.py версии A)
    tg_id = call.from_user.id

    # гарантируем дефолтную подписку, если нет активной
    await ensure_default_subscription(session, tg_id)

    try:
        await charge_photo_generation(session, tg_id)
    except NoGenerationsLeft:
        await stop_progress(stop, progress_task)
        if await is_launch_subscription(session, tg_id):
            await edit_text_safe(
                progress_msg, launch_limits_message(), reply_markup=buy_generations_kb()
            )
        else:
            await edit_text_safe(
                progress_msg,
                "⛔️ Лимит генераций исчерпан.\n\nОформи подписку или пополни баланс 💳",
                reply_markup=buy_generations_kb(),
            )
        return

    prompt = (
        f"{model_desc}\n\n"
        f"{action_desc}\n\n"
        "Важно: товар должен строго соответствовать референс-фото (цвет, фактура, форма, принты/логотипы). "
        "Фотореализм, корректные пропорции, естественный свет, высокое качество."
    )

    sent_any = False
    try:
        results = await generate_image_wavespeed_from_telegram(
            bot=call.bot,
            session=session,
            tg_id=tg_id,  # тут именно tg_id нужен (photo_settings + tg download)
            prompt=prompt,
            telegram_photo_file_ids=product_photos,
        )

        if not results:
            raise RuntimeError("WaveSpeed returned empty result")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю результат…")

        output_files: list[dict[str, str]] = []
        local_output_paths: list[str] = []
        best_local_path: str = ""

        for filename, img_bytes in results:
            local_path = save_generated_image_bytes(
                img_bytes=img_bytes,
                filename=filename,
                scenario="model",
                tg_id=tg_id,
            )
            local_output_paths.append(local_path)
            if not best_local_path:
                best_local_path = local_path

            sent = await send_image_smart(
                call.message, img_bytes=img_bytes, filename=filename
            )
            sent_any = True

            if getattr(sent, "photo", None):
                output_files.append(
                    {
                        "kind": "photo",
                        "file_id": sent.photo[-1].file_id,
                        "filename": filename,
                    }
                )
            elif getattr(sent, "document", None):
                output_files.append(
                    {
                        "kind": "document",
                        "file_id": sent.document.file_id,
                        "filename": filename,
                    }
                )

        await increment_generated_photos(session=session, tg_id=tg_id, delta=1)

        await state.set_data(
            {
                "feedback_payload": {
                    "scenario": "model",
                    "user_tg_id": tg_id,
                    "username": call.from_user.username or "",
                    "model_desc": model_desc,
                    "action_desc": action_desc,
                    "kie_prompt": prompt,
                    "input_photos": product_photos,
                    "output_files": output_files,
                    "local_output_paths": local_output_paths,
                    "best_local_path": best_local_path,
                }
            }
        )
        await state.set_state(FeedbackFlow.choice)

        await call.message.answer(
            "Всё получилось как ты хотел(а) или есть ошибка? 😊",
            reply_markup=feedback_kb(),
        )
        await call.message.answer(
            "Хотите ли что-то ещё сгенерировать?",
            reply_markup=photo_menu_kb(),
        )
        return

    except WaveSpeedError as e:
        logger.warning("WaveSpeed rejected/failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(
            progress_msg, wavespeed_error_to_user_text(e), reply_markup=review_edit_kb()
        )
        return

    except Exception as e:
        logger.exception("MODEL generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(
            progress_msg,
            with_support(
                "Не получилось сгенерировать 😅\n"
                "Попробуй нажать «✅ Всё верно» ещё раз или внеси правки."
            ),
            reply_markup=review_edit_kb(),
        )
        return
