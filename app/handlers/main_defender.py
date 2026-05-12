from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.confirm import ConfirmCallbacks, yes_no_kb
from app.keyboards.menu import MenuCallbacks, photo_menu_kb
from app.keyboards.extra import buy_generations_kb
from app.repository.generations import (
    NoGenerationsLeft,
    charge_photo_generation,
    ensure_default_subscription,
    refund_photo_generation,
    finalize_photo_generation,
)
from app.repository.users import increment_generated_photos, upsert_user
from app.services.album_collector import AlbumCollector
from app.services.generation import generate_image_wavespeed_from_telegram
from app.services.wavespeed_ai import WaveSpeedError
from app.states.main_defender_flow import MainDefenderFlow
from app.utils.wavespeed_errors import wavespeed_error_to_user_text
from app.utils.launch_guard import block_launch_for_call
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.tg_edit import edit_text_safe
from app.utils.content_media import send_content_photo
from app.utils.tg_send import send_image_smart
from app.utils.support_text import with_support
from app.utils.tg_callback import safe_answer

router = Router()
logger = logging.getLogger(__name__)
_album = AlbumCollector(debounce_seconds=0.8)

_PROMPT = (
    "Make a greeting card from this photo. Preserve facial features and pose. "
    "The card is dedicated to a holiday with the texts [Главному защитнику] and [с праздником]. "
    "Style: bold editorial fashion illustration rendered in thick oil pastel or wax crayon, "
    "with chunky, textured strokes on visible sketchbook paper. It should feel chic and modern, "
    "focusing on outfit and pose through expressive color blocks rather than outlines or realism. "
    "No national symbols, flags, insignia, or country-specific emblems."
)


async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


@router.callback_query(F.data == MenuCallbacks.MAIN_DEFENDER)
async def start_main_defender(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await safe_answer(call)
    await upsert_user(session, call.from_user.id, call.from_user.username)
    if await block_launch_for_call(call, session, reply_markup=buy_generations_kb()):
        return
    await state.clear()
    await state.set_state(MainDefenderFlow.photos)
    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass
        await send_content_photo(
            call.message,
            filename="my_23.jpeg",
            caption=(
                "🛡 <b>Мой главный защитник</b>\n\n"
                "Пришли 1–2 фото, где чётко видны мужчина и женщина 📸"
            ),
            parse_mode="HTML",
        )


@router.message(MainDefenderFlow.photos)
async def main_defender_photos_in(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Нужно 1–2 фото 📸 Отправь, пожалуйста, изображения.")
        return

    if not message.media_group_id:
        file_id = message.photo[-1].file_id
        await state.update_data(photos=[file_id])
        await state.set_state(MainDefenderFlow.confirm)
        await message.answer_photo(
            file_id,
            caption="Сгенерировать открытку на основе этой фотографии? ✨",
            reply_markup=yes_no_kb(
                yes_text="✅ Да",
                no_text="❌ Нет",
                no_style="danger",
            ),
        )
        return

    await _album.push(
        message.chat.id, message.media_group_id, message.photo[-1].file_id
    )
    result = await _album.collect(message.chat.id, message.media_group_id)
    if not result.file_ids:
        return

    if not (1 <= len(result.file_ids) <= 2):
        await message.answer(
            "Нужно 1–2 фото одним сообщением (альбомом). Попробуй ещё раз 📸"
        )
        return

    await state.update_data(photos=result.file_ids)
    await state.set_state(MainDefenderFlow.confirm)

    if len(result.file_ids) == 1:
        await message.answer_photo(
            result.file_ids[0],
            caption="Сгенерировать открытку на основе этой фотографии? ✨",
            reply_markup=yes_no_kb(
                yes_text="✅ Да",
                no_text="❌ Нет",
                no_style="danger",
            ),
        )
        return

    media = [InputMediaPhoto(media=fid) for fid in result.file_ids]
    await message.answer_media_group(media=media)
    await message.answer(
        "Сгенерировать открытку на основе этих фотографий? ✨",
        reply_markup=yes_no_kb(
            yes_text="✅ Да",
            no_text="❌ Нет",
            no_style="danger",
        ),
    )


@router.callback_query(MainDefenderFlow.confirm, F.data == ConfirmCallbacks.NO)
async def main_defender_confirm_no(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(photos=[])
    await state.set_state(MainDefenderFlow.photos)
    await edit_text_safe(
        call,
        "Хорошо! Пришли 1–2 фото ещё раз 📸",
        reply_markup=None,
    )
    await safe_answer(call)


@router.callback_query(MainDefenderFlow.confirm, F.data == ConfirmCallbacks.YES)
async def main_defender_confirm_yes(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    photos: list[str] = data.get("photos") or []
    if not photos:
        await state.clear()
        await safe_answer(call, "Фото не найдены 😕", show_alert=True)
        return

    if call.message is None:
        await safe_answer(call)
        return

    progress_msg = await call.message.answer(progress_initial_text())
    stop = asyncio.Event()
    progress_task = asyncio.create_task(
        progress_loop(lambda t: _update_progress_message(progress_msg, t), stop)
    )

    user = await upsert_user(session, call.from_user.id, call.from_user.username)
    tg_id = user.tg_id

    await ensure_default_subscription(session, tg_id)

    try:
        await charge_photo_generation(session, tg_id)
    except NoGenerationsLeft:
        await stop_progress(stop, progress_task)
        await edit_text_safe(
            progress_msg,
            "⛔️ Недостаточно кредитов.\n\nПополните баланс 💳",
            reply_markup=buy_generations_kb(),
        )
        await state.clear()
        await safe_answer(call)
        return

    sent_any = False
    try:
        results = await generate_image_wavespeed_from_telegram(
            bot=call.bot,
            session=session,
            tg_id=tg_id,
            prompt=_PROMPT,
            telegram_photo_file_ids=photos,
            aspect_ratio="3:4",
            max_images=1,
        )

        if not results:
            raise RuntimeError("WaveSpeed returned empty result")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю результат…")

        for filename, img_bytes in results:
            await send_image_smart(call.message, img_bytes=img_bytes, filename=filename)
            sent_any = True
            await finalize_photo_generation(session, tg_id)

        await increment_generated_photos(session=session, tg_id=tg_id, delta=1, section="main_defender")
        await state.clear()
        await call.message.answer(
            "Хочешь сгенерировать ещё что-нибудь? ✨",
            reply_markup=photo_menu_kb(),
        )
        await safe_answer(call)
        return

    except WaveSpeedError as e:
        logger.warning("MAIN_DEFENDER generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, wavespeed_error_to_user_text(e))
        await state.clear()
        await safe_answer(call)
        return

    except Exception as e:
        logger.exception("MAIN_DEFENDER generation failed: %s", e)
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
        await safe_answer(call)
        return
