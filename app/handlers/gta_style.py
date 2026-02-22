from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.menu import MenuCallbacks, photo_menu_kb
from app.keyboards.extra import buy_generations_kb
from app.repository.generations import (
    NoGenerationsLeft,
    charge_photo_generation,
    ensure_default_subscription,
    refund_photo_generation,
)
from app.repository.users import increment_generated_photos, upsert_user
from app.services.generation import generate_image_kie_from_telegram_with_extra
from app.services.kie_ai import KieAIError
from app.states.gta_style_flow import GTAStyleFlow
from app.utils.kie_errors import kie_error_to_user_text
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.tg_edit import edit_text_safe
from app.utils.content_media import send_content_photo
from app.utils.tg_send import send_image_smart
from app.utils.support_text import with_support
from app.utils.launch_guard import block_launch_for_call

router = Router()
logger = logging.getLogger(__name__)

_PROMPT = (
    "foto orizzontale:) Prendi questi riferimenti fotografici e fai un rendering 3D "
    "iperrealistico di alta qualità, stile gta di quella giovane donna NON CAMBIARE I "
    "TRATTI FACCIALI ORIGINALI; con estetica di gta, stile illustrazione ditigale "
    "iperrealistico kalitesi daha yuksek olsun lutfen"
)


def _load_gta_background_bytes() -> bytes:
    path = Path(__file__).resolve().parents[1] / "content" / "gta_fon.png"
    return path.read_bytes()


async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


@router.callback_query(F.data == MenuCallbacks.GTA_STYLE)
async def start_gta_style(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await call.answer()
    await upsert_user(session, call.from_user.id, call.from_user.username)
    if await block_launch_for_call(call, session, reply_markup=buy_generations_kb()):
        return
    await state.clear()
    await state.set_state(GTAStyleFlow.photo)

    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass
        ok = await send_content_photo(
            call.message,
            filename="gta_style.png",
            caption=(
                "🕶 <b>GTA STYLE</b>\n\n"
                "Пришли фото человека, который будет на изображении 📸"
            ),
            parse_mode="HTML",
        )
        if not ok:
            await edit_text_safe(
                call,
                "🕶 <b>GTA STYLE</b>\n\nПришли фото человека, который будет на изображении 📸",
                reply_markup=None,
            )


@router.message(GTAStyleFlow.photo)
async def gta_style_photo_in(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not message.photo:
        await message.answer("Нужно фото человека 📸 Отправь, пожалуйста, изображение.")
        return

    file_id = message.photo[-1].file_id
    await state.update_data(photo_id=file_id)
    prompt = _PROMPT

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
        gta_bg = _load_gta_background_bytes()
        results = await generate_image_kie_from_telegram_with_extra(
            bot=message.bot,
            session=session,
            tg_id=tg_id,
            prompt=prompt,
            telegram_photo_file_ids=[file_id],
            extra_images=[("gta_fon.png", gta_bg)],
            aspect_ratio="16:9",
            max_images=1,
        )

        if not results:
            raise RuntimeError("KIE returned empty result")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю результат…")

        for filename, img_bytes in results:
            await send_image_smart(message, img_bytes=img_bytes, filename=filename)
            sent_any = True

        await increment_generated_photos(session=session, tg_id=tg_id, delta=1)
        await state.clear()
        await message.answer(
            "Хотите ли что-то ещё сгенерировать?",
            reply_markup=photo_menu_kb(),
        )
        return

    except KieAIError as e:
        logger.warning("GTA_STYLE generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, kie_error_to_user_text(e))
        await state.clear()
        return

    except Exception as e:
        logger.exception("GTA_STYLE generation failed: %s", e)
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
