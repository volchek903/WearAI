from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.menu import MenuCallbacks, SettingsCallbacks, photo_menu_kb
from app.keyboards.extra import buy_generations_kb
from app.repository.generations import (
    NoGenerationsLeft,
    charge_photo_generation,
    ensure_default_subscription,
    refund_photo_generation,
)
from app.repository.users import increment_generated_photos, upsert_user
from app.services.album_collector import AlbumCollector
from app.services.generation import generate_image_kie_from_telegram
from app.services.kie_ai import KieAIError
from app.states.nano_banana_flow import NanoBananaFlow
from app.utils.kie_errors import kie_error_to_user_text
from app.utils.progress_bar import (
    progress_initial_text,
    progress_loop,
    stop_progress,
)
from app.utils.tg_edit import edit_text_safe
from app.utils.tg_send import send_image_smart
from app.utils.validators import MAX_TEXT_LEN, is_text_too_long
from app.utils.support_text import with_support

router = Router()
logger = logging.getLogger(__name__)
_album = AlbumCollector(debounce_seconds=0.8)

async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


@router.callback_query(
    F.data.in_({MenuCallbacks.NANO_BANANA, SettingsCallbacks.NANO_BANANA})
)
async def start_nano_banana(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await call.answer()
    await upsert_user(session, call.from_user.id, call.from_user.username)

    await state.clear()
    await state.set_state(NanoBananaFlow.photos)

    if call.message:
        await edit_text_safe(
            call,
            "🍌 nano-banano\n\n"
            "Пришли от 1 до 8 фото одним сообщением (альбомом) 📸",
            reply_markup=None,
        )


@router.message(NanoBananaFlow.photos)
async def nano_banana_photos_in(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer(
            "Нужно отправить <b>от 1 до 8 фото</b> одним сообщением (альбомом) 📸"
        )
        return

    if not message.media_group_id:
        file_id = message.photo[-1].file_id
        await state.update_data(photos=[file_id])
        await state.set_state(NanoBananaFlow.prompt)
        await message.answer("Отлично! Теперь пришли промпт ✍️")
        return

    await _album.push(
        message.chat.id, message.media_group_id, message.photo[-1].file_id
    )
    result = await _album.collect(message.chat.id, message.media_group_id)
    if not result.file_ids:
        return

    if not (1 <= len(result.file_ids) <= 8):
        await message.answer(
            "Ой, тут должно быть <b>от 1 до 8 фото</b> одним сообщением. Попробуй ещё раз 📸"
        )
        return

    await state.update_data(photos=result.file_ids)
    await state.set_state(NanoBananaFlow.prompt)
    await message.answer("Отлично! Теперь пришли промпт ✍️")


@router.message(NanoBananaFlow.prompt)
async def nano_banana_prompt_in(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Нужен текст промпта ✍️ Отправь, пожалуйста, сообщение.")
        return

    prompt = message.text.strip()
    if is_text_too_long(prompt):
        await message.answer(
            f"Ой, текст слишком длинный 😅\n"
            f"Максимум {MAX_TEXT_LEN} символов, а у тебя {len(prompt)}.\n"
            "Сократи, пожалуйста, и отправь ещё раз 🙌"
        )
        return

    data = await state.get_data()
    photos: list[str] = data.get("photos", []) or []
    if not photos:
        await message.answer(
            "Не вижу фото для генерации 😅 Давай начнём заново: /start"
        )
        await state.clear()
        return

    progress_msg = await message.answer(progress_initial_text())
    stop = asyncio.Event()
    progress_task = asyncio.create_task(
        progress_loop(lambda t: _update_progress_message(progress_msg, t), stop)
    )

    user = await upsert_user(session, message.from_user.id, message.from_user.username)
    tg_id = user.tg_id

    await ensure_default_subscription(session, tg_id)

    try:
        await charge_photo_generation(session, tg_id)
    except NoGenerationsLeft:
        await stop_progress(stop, progress_task)
        await edit_text_safe(
            progress_msg,
            "⛔️ Лимит генераций исчерпан.\n\nОформи подписку или пополни баланс 💳",
            reply_markup=buy_generations_kb(),
        )
        await state.clear()
        return

    sent_any = False
    try:
        results = await generate_image_kie_from_telegram(
            bot=message.bot,
            session=session,
            tg_id=tg_id,
            prompt=prompt,
            telegram_photo_file_ids=photos,
            max_images=8,
        )

        if not results:
            raise RuntimeError("KIE returned empty result")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю результат…")

        for filename, img_bytes in results:
            await send_image_smart(
                message, img_bytes=img_bytes, filename=filename
            )
            sent_any = True

        await increment_generated_photos(session=session, tg_id=tg_id, delta=1)
        await state.clear()
        await message.answer(
            "Хотите ли что-то ещё сгенерировать?",
            reply_markup=photo_menu_kb(),
        )
        return

    except KieAIError as e:
        logger.warning("KIE rejected/failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, kie_error_to_user_text(e))
        await state.clear()
        return

    except Exception as e:
        logger.exception("NANO_BANANA generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(
            progress_msg,
            with_support(
                "Не получилось сгенерировать 😅\n"
                "Попробуй ещё раз или вернись в меню."
            ),
            reply_markup=photo_menu_kb(),
        )
        await state.clear()
        return
