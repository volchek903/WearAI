from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.validators import MAX_TEXT_LEN, is_text_too_long
from app.keyboards.menu import MenuCallbacks
from app.keyboards.confirm import yes_no_kb, review_edit_kb, ConfirmCallbacks
from app.keyboards.help import help_button_kb
from app.keyboards.feedback import feedback_kb
from app.repository.users import increment_generated_photos, upsert_user
from app.repository.generations import (
    charge_photo_generation,
    refund_photo_generation,
    NoGenerationsLeft,
)
from app.services.album_collector import AlbumCollector
from app.services.generation import generate_image_kie_from_telegram
from app.services.kie_ai import KieAIError
from app.states.model_flow import ModelFlow
from app.states.feedback_flow import FeedbackFlow
from app.utils.tg_edit import edit_text_safe
from app.utils.tg_send import send_image_smart
from app.utils.kie_errors import kie_error_to_user_text
from app.utils.generated_files import save_generated_image_bytes


router = Router()
logger = logging.getLogger(__name__)
_album = AlbumCollector(debounce_seconds=0.8)

MODEL_DESC_EXAMPLE = (
    "Отлично! 🛍✨\n\n"
    "Опиши, какой ты хочешь видеть модель 👇\n"
    "Пример: “Мужчина 25–35, студийный свет, белый фон, стиль casual, лёгкая улыбка, поза в пол-оборота”."
)

PRODUCT_ACTION_EXAMPLE = (
    "Класс, фото товара получил! ✅\n\n"
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
    await upsert_user(session, call.from_user.id, call.from_user.username)

    await state.clear()
    await state.set_state(ModelFlow.model_desc)

    await edit_text_safe(
        call, MODEL_DESC_EXAMPLE, reply_markup=help_button_kb("model_desc")
    )
    await call.answer()


@router.message(ModelFlow.model_desc)
async def model_desc_in(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer(
            "Ой 😅 Мне нужен текст. Опиши модель словами, пожалуйста 🙌"
        )
        return

    desc = message.text.strip()

    if is_text_too_long(desc):
        await message.answer(
            f"Ой 😅 Текст слишком длинный.\n"
            f"Максимум {MAX_TEXT_LEN} символов, а у тебя {len(desc)}.\n"
            "Сократи, пожалуйста, и отправь ещё раз 🙌"
        )
        return

    await state.update_data(model_desc=desc)
    await state.set_state(ModelFlow.confirm_model_desc)

    await message.answer(
        f"Супер! 😊 Вот так я понял твою модель:\n“{desc}”\n\nВсё верно? ✅",
        reply_markup=yes_no_kb(yes_text="✅ Да", no_text="✏️ Изменить"),
    )


@router.callback_query(ModelFlow.confirm_model_desc, F.data == ConfirmCallbacks.NO)
async def model_desc_edit(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(model_desc="")
    await state.set_state(ModelFlow.model_desc)

    await edit_text_safe(
        call,
        "Ок! 😄 Тогда опиши модель заново 👇\n\n"
        + MODEL_DESC_EXAMPLE.split("\n\n", 1)[1],
        reply_markup=help_button_kb("model_desc"),
    )
    await call.answer()


@router.callback_query(ModelFlow.confirm_model_desc, F.data == ConfirmCallbacks.YES)
async def model_desc_confirmed(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ModelFlow.product_photos)

    await edit_text_safe(
        call,
        "Отлично! Теперь пришли фото товара 📸\n"
        "Можно от 1 до 5 фото за один раз (одним сообщением/альбомом) 🙌",
        reply_markup=help_button_kb("product_photos", text="📸 Как лучше сфоткать?"),
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
            PRODUCT_ACTION_EXAMPLE, reply_markup=help_button_kb("presentation_desc")
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
            "Ой 😅 Тут должно быть <b>от 1 до 5 фото</b> одним сообщением. Попробуй ещё раз 📸🙌"
        )
        return

    await state.update_data(product_photos=result.file_ids)
    await state.set_state(ModelFlow.presentation_desc)

    await message.answer(
        PRODUCT_ACTION_EXAMPLE, reply_markup=help_button_kb("presentation_desc")
    )


@router.message(ModelFlow.presentation_desc)
async def presentation_desc_in(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer(
            "Мне нужен текст 😊 Напиши, что нужно сделать с товаром 👇"
        )
        return

    action_text = message.text.strip()

    if is_text_too_long(action_text):
        await message.answer(
            f"Ой 😅 Текст слишком длинный.\n"
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
        "Давай быстренько проверим ✅😊\n\n"
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
        "Ок! 😄 Меняем описание модели 👇\n\n" + MODEL_DESC_EXAMPLE.split("\n\n", 1)[1],
        reply_markup=help_button_kb("model_desc"),
    )
    await call.answer()


@router.callback_query(ModelFlow.review, F.data == ConfirmCallbacks.EDIT_PHOTOS)
async def review_edit_photos(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(product_photos=[])
    await state.set_state(ModelFlow.product_photos)

    await edit_text_safe(
        call,
        "Ок! 😄 Пришли фото товара заново (1–5 фото одним сообщением) 📸",
        reply_markup=help_button_kb("product_photos", text="📸 Как лучше сфоткать?"),
    )
    await call.answer()


@router.callback_query(ModelFlow.review, F.data == ConfirmCallbacks.EDIT_PRESENTATION)
async def review_edit_presentation(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(presentation_desc="")
    await state.set_state(ModelFlow.presentation_desc)

    await edit_text_safe(
        call,
        "Ок! 😊 Напиши заново, что нужно сделать с товаром 👇\n\n"
        + PRODUCT_ACTION_EXAMPLE,
        reply_markup=help_button_kb("presentation_desc"),
    )
    await call.answer()


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
            call, "Не вижу всех данных для генерации 😅\nДавай начнём заново: /start"
        )
        await call.answer()
        await state.clear()
        return

    await edit_text_safe(call, "Генерирую изображение… ⏳")
    await call.answer()

    user = await upsert_user(session, call.from_user.id, call.from_user.username)

    try:
        await charge_photo_generation(session, user.id)  # ✅ user_id, не tg_id
    except NoGenerationsLeft:
        await edit_text_safe(
            call,
            "⛔️ Лимит генераций исчерпан.\n\nОформи подписку или пополни баланс.",
            reply_markup=review_edit_kb(),
        )
        await call.answer()
        return

    prompt = (
        f"{model_desc}\n\n"
        f"{action_desc}\n\n"
        "Важно: товар должен строго соответствовать референс-фото (цвет, фактура, форма, принты/логотипы). "
        "Фотореализм, корректные пропорции, естественный свет, высокое качество."
    )

    try:
        results = await generate_image_kie_from_telegram(
            bot=call.bot,
            session=session,
            tg_id=call.from_user.id,
            prompt=prompt,
            telegram_photo_file_ids=product_photos,
        )

        if not results:
            raise RuntimeError("KIE returned empty result")

        output_files: list[dict[str, str]] = []
        local_output_paths: list[str] = []
        best_local_path: str = ""

        for filename, img_bytes in results:
            local_path = save_generated_image_bytes(
                img_bytes=img_bytes,
                filename=filename,
                scenario="model",
                tg_id=call.from_user.id,
            )
            local_output_paths.append(local_path)
            if not best_local_path:
                best_local_path = local_path

            sent = await send_image_smart(
                call.message, img_bytes=img_bytes, filename=filename
            )

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

        await increment_generated_photos(
            session=session, tg_id=call.from_user.id, delta=1
        )

        await state.set_data(
            {
                "feedback_payload": {
                    "scenario": "model",
                    "user_tg_id": call.from_user.id,
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
            "Все получилось как вы хотели или обнаружили ошибку?",
            reply_markup=feedback_kb(),
        )
        return

    except KieAIError as e:
        logger.warning("KIE rejected/failed: %s", e)
        await refund_photo_generation(session, user.id)  # ✅ user_id
        await edit_text_safe(
            call, kie_error_to_user_text(e), reply_markup=review_edit_kb()
        )
        await call.answer()
        return

    except Exception as e:
        logger.exception("MODEL generation failed: %s", e)
        await refund_photo_generation(session, user.id)  # ✅ user_id
        await edit_text_safe(
            call,
            "Не получилось сгенерировать 😅\n"
            "Попробуй нажать «✅ Всё верно» ещё раз или внеси правки.",
            reply_markup=review_edit_kb(),
        )
        await call.answer()
        return
