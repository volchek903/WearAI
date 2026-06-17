from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.generation import generate_image_wavespeed_from_telegram
from app.services.wavespeed_ai import WaveSpeedError
from app.states.glam_collage_flow import GlamCollageFlow
from app.utils.content_media import send_content_photo
from app.utils.launch_guard import block_launch_for_call
from app.utils.pricing import build_single_generation_price_line
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.support_text import launch_limits_message, with_support
from app.utils.tg_callback import safe_answer
from app.utils.tg_edit import edit_text_safe
from app.utils.tg_send import send_image_smart
from app.utils.wavespeed_errors import wavespeed_error_to_user_text

router = Router()
logger = logging.getLogger(__name__)

_PROMPT = """Photo 3:4. Vertical three-frame editorial collage, professional beauty studio photography with hard directional lighting.
A person based on an uploaded reference photo, facial features preserved exactly. The subject can be either a woman or a man depending on the uploaded reference photo.
High-fashion beauty editorial with strong contrast and pronounced skin texture.
The model poses against a deep black background.
Identity preservation:
Keep the face, age, skin tone, facial proportions, expression type, and overall identity максимально close to the uploaded reference photo. Do not feminize a man and do not masculinize a woman.
Appearance & Styling:
If the uploaded reference is a woman:
Long hair styled in a sleek wet-look editorial finish, with textured, slightly tousled waves.
Transparent fashion eyeglasses with thin gold metal frame, minimalistic and elegant.
Thin gold hoop earrings, clearly visible in all frames.
Makeup:
Flawless glamorous beauty look.
Sharp black winged eyeliner, voluminous lashes, well-defined brows.
Soft pink-beige glossy lips.
Luminous skin with subtle highlighter on cheekbones and nose bridge.
Outfit:
Simple white ribbed tank top with wide straps, clean and minimal.
If the uploaded reference is a man:
Male high-fashion beauty editorial styling with preserved masculine facial features.
Hair styled in a sleek editorial wet-look texture appropriate to the reference.
Transparent fashion eyeglasses with thin gold metal frame, minimalistic and elegant.
Minimal jewelry only if it fits the reference and styling naturally.
Clean polished skin, defined brows, subtle natural lip tone, no feminine makeup.
Simple white ribbed tank top or minimal white editorial top with clean masculine styling.
Collage composition:
Top frame - portrait shot, confident direct gaze.
Middle frame - extreme close-up on eyes, lips, glasses, finger near lips.
Bottom frame - three-quarter angle, over-the-shoulder pose.
Lighting & Background:
Deep black background.
Hard frontal studio light, crisp highlights, deep shadows.
Style & Quality:
Luxury beauty editorial, cosmetic advertising, magazine-level quality.
Ultra high resolution, visible skin texture, fabric fibers, individual hair strands."""


async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


@router.callback_query(F.data == MenuCallbacks.GLAM_COLLAGE)
async def start_glam_collage(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await safe_answer(call)
    await upsert_user(session, call.from_user.id, call.from_user.username)
    if await block_launch_for_call(call, session, reply_markup=buy_generations_kb()):
        return

    await state.clear()
    await state.set_state(GlamCollageFlow.photo)
    price_line = await build_single_generation_price_line(session)

    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass
        await send_content_photo(
            call.message,
            filename="collage.jpeg",
            caption=(
                "✨ <b>Шикарный коллаж</b>\n\n"
                "Пришли фотку мужчины или женщины, и я подготовлю "
                f"гламурный editorial-коллаж в формате 3:4 📸\n\n{price_line}"
            ),
            parse_mode="HTML",
        )


@router.message(GlamCollageFlow.photo)
async def glam_collage_photo_in(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Нужно одно фото 📸 Отправь, пожалуйста, изображение.")
        return
    if message.media_group_id:
        await message.answer("Нужно одно фото (не альбом) 📸")
        return

    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await state.set_state(GlamCollageFlow.confirm)
    await message.answer_photo(
        photo_id,
        caption="Точно эту фотку хочешь использовать? ✨",
        reply_markup=yes_no_kb(
            yes_text="✅ Начать генерацию",
            no_text="🔁 Отправить другую",
            no_style="danger",
        ),
    )


@router.callback_query(GlamCollageFlow.confirm, F.data == ConfirmCallbacks.NO)
async def glam_collage_confirm_no(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(GlamCollageFlow.photo)
    await edit_text_safe(call, "Хорошо! Пришли другую фотку 📸", reply_markup=None)
    await safe_answer(call)


@router.callback_query(GlamCollageFlow.confirm, F.data == ConfirmCallbacks.YES)
async def glam_collage_confirm_yes(
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
        results = await generate_image_wavespeed_from_telegram(
            bot=call.bot,
            session=session,
            tg_id=tg_id,
            prompt=_PROMPT,
            telegram_photo_file_ids=[photo_id],
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

        await increment_generated_photos(session=session, tg_id=tg_id, delta=1, section="glam_collage")
        await state.clear()
        await call.message.answer(
            "Хочешь сгенерировать ещё что-нибудь? ✨",
            reply_markup=photo_menu_kb(),
        )
        return

    except WaveSpeedError as e:
        logger.warning("GLAM_COLLAGE generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, wavespeed_error_to_user_text(e))
        await state.clear()
        return

    except Exception as e:
        logger.exception("GLAM_COLLAGE generation failed: %s", e)
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
