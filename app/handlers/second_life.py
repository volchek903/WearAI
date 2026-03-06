from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.confirm import ConfirmCallbacks, yes_no_kb
from app.keyboards.menu import MenuCallbacks, photo_menu_kb
from app.keyboards.extra import buy_generations_kb
from app.repository.generations import (
    NoGenerationsLeft,
    charge_photo_generation,
    ensure_default_subscription,
    refund_photo_generation,
)
from app.repository.users import increment_generated_photos, upsert_user
from app.services.generation import generate_image_wavespeed_from_telegram
from app.services.wavespeed_ai import WaveSpeedError
from app.states.second_life_flow import SecondLifeFlow
from app.utils.wavespeed_errors import wavespeed_error_to_user_text
from app.utils.launch_guard import block_launch_for_call
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.tg_edit import edit_text_safe
from app.utils.content_media import send_content_album
from app.utils.tg_send import send_image_smart
from app.utils.support_text import with_support
from app.utils.tg_callback import safe_answer

router = Router()
logger = logging.getLogger(__name__)

_PROMPT = (
    "Ultra-high-resolution 4K enhancement based strictly on the provided reference image. "
    "Absolute fidelity to original facial anatomy, proportions, and identity. Preserve expression, "
    "gaze, pose, camera angle, framing, and perspective with zero deviation. Clothing, hair, skin, "
    "and background elements must remain unchanged in structure, placement, and design. "
    "Recover fine-grain detail with natural realism. Enhance pores, fine lines, hair strands, "
    "eyelashes, fabric weave, seams, and material edges without introducing stylization. "
    "Maintain original color science, white balance, and tonal relationships exactly as captured. "
    "Lighting direction, intensity, contrast, and shadow behavior must match the source image precisely, "
    "with only improved clarity and expanded dynamic range. No relighting, no reshaping. Remove any grain. "
    "Apply controlled sharpening and high-frequency detail reconstruction. Remove compression artifacts and "
    "noise while retaining authentic texture. No smoothing, no plastic skin, no artificial gloss. "
    "Facial features must remain consistent across the entire image with coherent anatomy and clean, stable edges. "
    "Negative constraints: no warping, no facial drift, no added or missing anatomy, no altered hands, "
    "no distortions, no perspective shift, no text or graphics, no hallucinated detail, "
    "no stylized rendering. Output must read as a true-to-life, photorealistic upscale that matches the reference exactly, "
    "only clearer, sharper, and higher resolution."
)


async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


@router.callback_query(F.data == MenuCallbacks.SECOND_LIFE)
async def start_second_life(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await safe_answer(call)
    await upsert_user(session, call.from_user.id, call.from_user.username)
    if await block_launch_for_call(call, session, reply_markup=buy_generations_kb()):
        return
    await state.clear()
    await state.set_state(SecondLifeFlow.photo)
    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass
        await send_content_album(
            call.message,
            filenames=["old_photo.jpeg", "new_photo.jpeg"],
            caption=(
                "🖼 <b>Вторая жизнь для фото</b>\n\n"
                "Пришли фото, которое нужно улучшить 📸"
            ),
            parse_mode="HTML",
        )


@router.message(SecondLifeFlow.photo)
async def second_life_photo_in(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Нужно фото 📸 Отправь, пожалуйста, изображение.")
        return

    file_id = message.photo[-1].file_id
    await state.update_data(photo_id=file_id)
    await state.set_state(SecondLifeFlow.confirm)

    await message.answer_photo(
        file_id,
        caption="Сгенерировать улучшенное фото на основе этого изображения?",
        reply_markup=yes_no_kb(
            yes_text="✅ Да",
            no_text="❌ Нет",
            no_style="danger",
        ),
    )


@router.callback_query(SecondLifeFlow.confirm, F.data == ConfirmCallbacks.NO)
async def second_life_confirm_no(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(photo_id=None)
    await state.set_state(SecondLifeFlow.photo)
    await edit_text_safe(
        call,
        "Хорошо! Пришли фото ещё раз 📸",
        reply_markup=None,
    )
    await safe_answer(call)


@router.callback_query(SecondLifeFlow.confirm, F.data == ConfirmCallbacks.YES)
async def second_life_confirm_yes(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    photo_id = data.get("photo_id")
    if not photo_id:
        await state.clear()
        await safe_answer(call, "Фото не найдено 😕", show_alert=True)
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
            "⛔️ Лимит генераций исчерпан.\n\nОформи подписку или пополни баланс 💳",
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
            telegram_photo_file_ids=[photo_id],
            aspect_ratio="auto",
            max_images=1,
        )

        if not results:
            raise RuntimeError("WaveSpeed returned empty result")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю результат…")

        for filename, img_bytes in results:
            await send_image_smart(call.message, img_bytes=img_bytes, filename=filename)
            sent_any = True

        await increment_generated_photos(session=session, tg_id=tg_id, delta=1)
        await state.clear()
        await call.message.answer(
            "Хотите ли что-то ещё сгенерировать?",
            reply_markup=photo_menu_kb(),
        )
        await safe_answer(call)
        return

    except WaveSpeedError as e:
        logger.warning("SECOND_LIFE generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, wavespeed_error_to_user_text(e))
        await state.clear()
        await safe_answer(call)
        return

    except Exception as e:
        logger.exception("SECOND_LIFE generation failed: %s", e)
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
