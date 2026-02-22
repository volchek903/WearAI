# app/handlers/scenario_tryon.py
from __future__ import annotations

import asyncio
import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.menu import MenuCallbacks
from app.keyboards.extra import buy_generations_kb
from app.keyboards.confirm import yes_no_tryon_kb_with_help, ConfirmCallbacks
from app.keyboards.menu import photo_menu_kb
from app.keyboards.feedback import feedback_kb
from app.repository.users import increment_generated_photos, upsert_user
from app.repository.generations import (
    ensure_default_subscription,
    charge_photo_generation,
    refund_photo_generation,
    NoGenerationsLeft,
)
from app.services.generation import generate_image_kie_from_telegram
from app.services.kie_ai import KieAIError
from app.states.tryon_flow import TryOnFlow
from app.states.feedback_flow import FeedbackFlow
from app.utils.kie_errors import kie_error_to_user_text
from app.utils.tg_edit import edit_text_safe
from app.utils.content_media import send_content_album
from app.utils.tg_send import send_image_smart
from app.utils.support_text import with_support
from app.utils.launch_guard import block_launch_for_call
from app.utils.validators import MAX_TEXT_LEN, is_text_too_long
from app.utils.progress_bar import (
    progress_initial_text,
    progress_loop,
    stop_progress,
)
from app.utils.generated_files import save_generated_image_bytes


router = Router()
logger = logging.getLogger(__name__)

TRYON_DESC_EXAMPLE = (
    "Отлично! ✅\n\n"
    "Теперь напиши, <b>что нужно сделать с вещью</b> 👇\n"
    "Примеры:\n"
    "— «Надень эту вещь на меня максимально реалистично»\n"
    "— «Оставь оригинальный цвет/принт/логотип, без лишних объектов»\n"
    "— «Сделай посадку по фигуре, естественные складки, реалистичный свет»"
)


@router.callback_query(F.data == MenuCallbacks.TRYON)
async def start_tryon_flow(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await call.answer()
    await upsert_user(session, call.from_user.id, call.from_user.username)
    if await block_launch_for_call(call, session, reply_markup=buy_generations_kb()):
        return

    await state.clear()
    await state.set_state(TryOnFlow.user_photo)

    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass
        await send_content_album(
            call.message,
            filenames=["scenario_photo1.jpeg", "scenario_photo2.jpeg"],
            caption="Поехали! 👕✨\n\nПришли свою фотографию (1 фото) 🤳📸",
            parse_mode="HTML",
        )


@router.message(TryOnFlow.user_photo)
async def user_photo_in(message: Message, state: FSMContext) -> None:
    if message.media_group_id:
        await message.answer("Пожалуйста, пришли одну фотографию (не альбом) 🤳")
        return
    if not message.photo:
        await message.answer(
            "Нужна именно фотография 🤳 Пришли, пожалуйста, 1 фото."
        )
        return

    user_file_id = message.photo[-1].file_id
    await state.update_data(user_photo=user_file_id)
    await state.set_state(TryOnFlow.item_photo)

    await message.answer(
        "Фото получил ✅😊\n\nТеперь пришли фото вещи (1 фото) 📦📸",
        reply_markup=None,
    )


@router.message(TryOnFlow.item_photo)
async def item_photo_in(message: Message, state: FSMContext) -> None:
    if message.media_group_id:
        await message.answer("Пожалуйста, пришли одно фото вещи (не альбом) 📸")
        return
    if not message.photo:
        await message.answer("Хочу именно фото вещи 📸 Пришли, пожалуйста, 1 фото.")
        return

    item_file_id = message.photo[-1].file_id
    data = await state.get_data()
    user_file_id = data.get("user_photo")

    if not user_file_id:
        await state.clear()
        await message.answer("Ой, сессия сбилась 😅 Нажми /start и начни заново 🙌")
        return

    await state.update_data(item_photo=item_file_id)
    await state.set_state(TryOnFlow.confirm)

    media = [
        InputMediaPhoto(
            media=user_file_id,
            caption="Смотри 😊\nЭто твоё фото и вещь. Точно надеваем именно её? ✅",
        ),
        InputMediaPhoto(media=item_file_id),
    ]

    try:
        await message.answer_media_group(media=media)
    except Exception:
        await message.answer_photo(user_file_id, caption="Твоё фото 🤳")
        await message.answer_photo(item_file_id, caption="Фото вещи 📦")
        await message.answer("Точно надеваем именно эту вещь? ✅🙂")

    await message.answer(
        "Жду твоё решение 👇", reply_markup=yes_no_tryon_kb_with_help()
    )


@router.callback_query(TryOnFlow.confirm, F.data == ConfirmCallbacks.NO)
async def tryon_choose_other(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(item_photo=None)
    await state.set_state(TryOnFlow.item_photo)

    await edit_text_safe(call, "Хорошо 😄 Пришли другое фото вещи (1 фото) 📸")
    await call.answer()


@router.callback_query(TryOnFlow.confirm, F.data == ConfirmCallbacks.YES)
async def tryon_confirmed_go_prompt(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TryOnFlow.tryon_desc)

    await edit_text_safe(
        call,
        TRYON_DESC_EXAMPLE,
        reply_markup=None,
    )
    await call.answer()


@router.message(TryOnFlow.tryon_desc)
async def tryon_desc_in(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Нужен текст ✍️ Напиши, что нужно сделать с вещью.")
        return

    style_prompt = message.text.strip()

    if is_text_too_long(style_prompt):
        await message.answer(
            f"Ой, текст слишком длинный 😅\n"
            f"Максимум {MAX_TEXT_LEN} символов, а у тебя {len(style_prompt)}.\n"
            "Сократи, пожалуйста, и отправь ещё раз 🙌"
        )
        return

    data = await state.get_data()
    user_photo: str | None = data.get("user_photo")
    item_photo: str | None = data.get("item_photo")

    if not user_photo or not item_photo:
        await state.clear()
        await message.answer("Ой, сессия сбилась 😅 Нажми /start и начни заново 🙌")
        return

    progress_msg = await message.answer(progress_initial_text())
    stop = asyncio.Event()

    async def _update(text: str) -> None:
        try:
            await progress_msg.edit_text(text)
        except Exception:
            return

    progress_task = asyncio.create_task(progress_loop(_update, stop))

    # гарантируем пользователя
    await upsert_user(session, message.from_user.id, message.from_user.username)

    tg_id = message.from_user.id

    # ✅ ключевой фикс: гарантируем активную подписку
    await ensure_default_subscription(session, tg_id)

    try:
        # ✅ списание по tg_id (как в generations.py версии A)
        await charge_photo_generation(session, tg_id)
    except NoGenerationsLeft:
        await stop_progress(stop, progress_task)
        await message.answer(
            "⛔️ Лимит генераций исчерпан.\n\nОформи подписку или пополни баланс 💳",
            reply_markup=buy_generations_kb(),
        )
        return

    prompt = (
        "Create a photorealistic virtual try-on result.\n"
        "Use the first image as the person reference (keep face/body identity).\n"
        "Use the second image as the clothing/item reference (keep colors, fabric, prints, logos).\n"
        "Ensure realistic fit, folds, lighting, and proportions. High quality.\n"
        "No extra accessories unless present in the source images.\n"
        f"\nUser instruction (RU): {style_prompt}\n"
    )

    sent_any = False
    try:
        results = await generate_image_kie_from_telegram(
            bot=message.bot,
            session=session,
            tg_id=tg_id,  # ✅ тут тоже tg_id
            prompt=prompt,
            telegram_photo_file_ids=[user_photo, item_photo],
        )

        if not results:
            raise RuntimeError("KIE returned empty result")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю результат…")

        output_files: list[dict[str, str]] = []
        local_output_paths: list[str] = []
        best_local_path: str = ""

        for filename, img_bytes in results:
            local_path = save_generated_image_bytes(
                img_bytes=img_bytes,
                filename=filename,
                scenario="tryon",
                tg_id=tg_id,
            )
            local_output_paths.append(local_path)
            if not best_local_path:
                best_local_path = local_path

            sent = await send_image_smart(
                message, img_bytes=img_bytes, filename=filename
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
                    "scenario": "tryon",
                    "user_tg_id": tg_id,
                    "username": message.from_user.username or "",
                    "tryon_desc": style_prompt,
                    "kie_prompt": prompt,
                    "input_photos": {
                        "user_photo": user_photo,
                        "item_photo": item_photo,
                    },
                    "output_files": output_files,
                    "local_output_paths": local_output_paths,
                    "best_local_path": best_local_path,
                }
            }
        )
        await state.set_state(FeedbackFlow.choice)

        await message.answer(
            "Всё получилось как ты хотел(а) или есть ошибка? 😊",
            reply_markup=feedback_kb(),
        )
        await message.answer(
            "Хотите ли что-то ещё сгенерировать?",
            reply_markup=photo_menu_kb(),
        )
        return

    except KieAIError as e:
        logger.warning("TRYON KIE failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)  # ✅ tg_id
        await stop_progress(stop, progress_task)
        await message.answer(kie_error_to_user_text(e))
        return

    except Exception as e:
        logger.exception("TRYON generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)  # ✅ tg_id
        await stop_progress(stop, progress_task)
        await message.answer(
            with_support(
                "Не получилось сделать примерку 😅\n"
                "Попробуй изменить описание и отправь ещё раз."
            )
        )
        return
