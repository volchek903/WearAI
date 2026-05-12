from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

# 3
from app.keyboards.confirm import ConfirmCallbacks, yes_no_kb
from app.keyboards.extra import buy_generations_kb
from app.keyboards.menu import MenuCallbacks, photo_menu_kb
from app.repository.generations import (
    NoGenerationsLeft,
    charge_photo_generation,
    ensure_default_subscription,
    refund_photo_generation,
    finalize_photo_generation,
    is_launch_subscription,
)
from app.repository.users import increment_generated_photos, upsert_user
from app.services.generation import generate_image_wavespeed_from_telegram_with_extra
from app.services.wavespeed_ai import WaveSpeedError
from app.states.sims_style_flow import SimsStyleFlow
from app.utils.content_media import get_content_file
from app.utils.launch_guard import block_launch_for_call
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.support_text import launch_limits_message, with_support
from app.utils.tg_callback import safe_answer
from app.utils.tg_edit import edit_text_safe
from app.utils.tg_send import send_image_smart
from app.utils.wavespeed_errors import wavespeed_error_to_user_text

router = Router()
logger = logging.getLogger(__name__)

_PROMPT = (
    "Image 1 = composition/style reference.\n"
    "Image 2 = subject identity reference.\n\n"
    "Create an edited version of Image 1 where the cat is replaced by the subject from Image 2.\n"
    "Preserve the full layout and all environmental details of Image 1.\n"
    "Match the exact art direction of Image 1:\n"
    "adorable stylized 3D render, oversized shiny eyes, plush fur, soft warm lighting, cozy cinematic atmosphere, high detail, clean polished finish.\n\n"
    "The inserted subject should inherit all recognizable identity traits from Image 2.\n"
    "If Image 2 is an animal, preserve species identity, facial structure, fur color, markings, and unique traits.\n"
    "If Image 2 is a person, preserve face, hairstyle, skin tone, proportions, and unique recognizable traits.\n\n"
    "The scene, props, and mood must stay consistent with Image 1.\n"
    "The final image should feel seamless, as if the original scene was created with that subject from the start."
)


def _load_sims_template_bytes() -> bytes:
    path = Path(__file__).resolve().parents[1] / "content" / "sims_maket.jpeg"
    return path.read_bytes()


async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


@router.callback_query(F.data == MenuCallbacks.SIMS_STYLE)
async def start_sims_style(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await safe_answer(call)
    await upsert_user(session, call.from_user.id, call.from_user.username)
    if await block_launch_for_call(call, session, reply_markup=buy_generations_kb()):
        return

    await state.clear()
    await state.set_state(SimsStyleFlow.photo)

    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass

        try:
            await call.message.answer_photo(
                get_content_file("sims_maket.jpeg"),
                caption=(
                    "🎮 <b>Sims стиль</b>\n\n"
                    "Пришли фото человека или животного, которого нужно поместить в Sims стиль 📸"
                ),
                parse_mode="HTML",
            )
        except Exception:
            await edit_text_safe(
                call,
                "🎮 <b>Sims стиль</b>\n\n"
                "Пришли фото человека или животного, которого нужно поместить в Sims стиль 📸",
                reply_markup=None,
            )


@router.message(SimsStyleFlow.photo)
async def sims_style_photo_in(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer(
            "Нужно одно фото человека или животного 📸 Отправь, пожалуйста, изображение."
        )
        return
    if message.media_group_id:
        await message.answer("Нужно одно фото, не альбом 📸")
        return

    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await state.set_state(SimsStyleFlow.confirm)
    await message.answer_photo(
        photo_id,
        caption="Это фото используем? Запускаю генерацию? ✅",
        reply_markup=yes_no_kb(
            yes_text="✅ Да, это оно",
            no_text="🔁 Отправить заново",
            no_style="danger",
        ),
    )


@router.callback_query(SimsStyleFlow.confirm, F.data == ConfirmCallbacks.NO)
async def sims_style_confirm_no(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SimsStyleFlow.photo)
    await edit_text_safe(
        call,
        "Хорошо, пришли другое фото человека или животного 📸",
        reply_markup=None,
    )
    await safe_answer(call)


@router.callback_query(SimsStyleFlow.confirm, F.data == ConfirmCallbacks.YES)
async def sims_style_confirm_yes(
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
        if await is_launch_subscription(session, tg_id):
            await edit_text_safe(
                progress_msg, launch_limits_message(), reply_markup=buy_generations_kb()
            )
        else:
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
        sims_template = _load_sims_template_bytes()
        results = await generate_image_wavespeed_from_telegram_with_extra(
            bot=call.bot,
            session=session,
            tg_id=tg_id,
            prompt=_PROMPT,
            telegram_photo_file_ids=[photo_id],
            extra_images=[("sims_maket.jpeg", sims_template)],
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

        await increment_generated_photos(
            session=session,
            tg_id=tg_id,
            delta=1,
            section="sims_style",
        )
        await state.clear()
        await call.message.answer(
            "Хочешь сгенерировать ещё что-нибудь? ✨",
            reply_markup=photo_menu_kb(),
        )
        return

    except WaveSpeedError as e:
        logger.warning("SIMS_STYLE generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, wavespeed_error_to_user_text(e))
        await state.clear()
        return

    except Exception as e:
        logger.exception("SIMS_STYLE generation failed: %s", e)
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
