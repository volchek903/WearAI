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
from app.services.generation import generate_image_kie_from_telegram
from app.services.kie_ai import KieAIError
from app.states.drift_heart_flow import DriftHeartFlow
from app.utils.kie_errors import kie_error_to_user_text
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.tg_edit import edit_text_safe
from app.utils.content_media import send_content_photo
from app.utils.tg_send import send_image_smart
from app.utils.support_text import with_support
from app.utils.tg_callback import safe_answer

router = Router()
logger = logging.getLogger(__name__)

_PROMPT = (
    "Create a vertical 9:16 ultra-realistic phone wallpaper. "
    "Use the car from the reference image as a strict base — do not change its model, "
    "shape, proportions, wheels, or identity. "
    "Scene: a frozen winter lake. The car drifts aggressively on ice, captured from a "
    "high drone angle. Tire tracks form a large heart shape. A natural, sharp ice crack "
    "cuts through the heart unevenly. "
    "Cold blue tones, light fog, snow dust, subtle motion blur on the car, sharp ice texture. "
    "Overcast or soft twilight lighting. "
    "No people, text, logos, or cinematic look — raw, photorealistic, minimal, moody, masculine."
)


async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


@router.callback_query(F.data == MenuCallbacks.DRIFT_HEART)
async def start_drift_heart(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await safe_answer(call)
    await upsert_user(session, call.from_user.id, call.from_user.username)
    await state.clear()
    await state.set_state(DriftHeartFlow.photo)

    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass
        await send_content_photo(
            call.message,
            filename="love_car.jpeg",
            caption="💘 <b>Дрифт сердце</b>\n\nПришли одно фото машины 📸",
            parse_mode="HTML",
        )


@router.message(DriftHeartFlow.photo)
async def drift_heart_photo_in(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Нужно одно фото машины 📸 Отправь, пожалуйста, изображение.")
        return

    file_id = message.photo[-1].file_id
    await state.update_data(photo_id=file_id)
    await state.set_state(DriftHeartFlow.confirm)

    await message.answer_photo(
        file_id,
        caption="Генерировать с этой машиной?",
        reply_markup=yes_no_kb(
            yes_text="✅ Да, всё верно",
            no_text="❌ Нет",
            no_style="danger",
        ),
    )


@router.callback_query(DriftHeartFlow.confirm, F.data == ConfirmCallbacks.NO)
async def drift_heart_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if call.message:
        await edit_text_safe(
            call,
            "Хорошо, вернул в меню фото 👇",
            reply_markup=photo_menu_kb(),
        )
    await safe_answer(call)


@router.callback_query(DriftHeartFlow.confirm, F.data == ConfirmCallbacks.YES)
async def drift_heart_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    file_id = data.get("photo_id")
    if not file_id:
        await state.clear()
        await call.answer("Фото не найдено 😕", show_alert=True)
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
        return

    sent_any = False
    try:
        results = await generate_image_kie_from_telegram(
            bot=call.bot,
            session=session,
            tg_id=tg_id,
            prompt=_PROMPT,
            telegram_photo_file_ids=[file_id],
            aspect_ratio="9:16",
            max_images=1,
        )

        if not results:
            raise RuntimeError("KIE returned empty result")

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

    except KieAIError as e:
        logger.warning("DRIFT_HEART generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, kie_error_to_user_text(e))
        await state.clear()
        await safe_answer(call)
        return

    except Exception as e:
        logger.exception("DRIFT_HEART generation failed: %s", e)
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
