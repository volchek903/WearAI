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
    is_launch_subscription,
)
from app.repository.users import increment_generated_photos, upsert_user
from app.services.generation import generate_image_kie_from_telegram
from app.services.kie_ai import KieAIError
from app.states.cinema_bw_flow import CinemaBWFlow
from app.utils.kie_errors import kie_error_to_user_text
from app.utils.launch_guard import block_launch_for_call
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.support_text import with_support, launch_limits_message
from app.utils.tg_callback import safe_answer
from app.utils.tg_edit import edit_text_safe
from app.utils.content_media import send_content_photo
from app.utils.tg_send import send_image_smart

router = Router()
logger = logging.getLogger(__name__)
_PROMPT = (
    "Use TWO uploaded reference photos: (1) the man, (2) the woman.\n\n"
    "ABSOLUTE PRIORITY: The faces must match the reference photos as closely as "
    "possible (near 1:1 likeness). Preserve the exact facial structure and "
    "identity: eye shape, nose, lips, jawline, cheekbones, proportions, age, "
    "skin tone, and any unique marks (moles/scars). Do NOT beautify, do NOT "
    "change face shape, do NOT average features, do NOT make them look "
    "younger/older. The references have higher priority than style, lighting, "
    "or grading. Keep photorealistic skin texture and sharp, detailed eyes.\n\n"
    "Scene: a completely empty movie theater. The man and woman are seated next "
    "to each other in soft cinema seats, alone, with many empty rows of seats "
    "behind them creating deep perspective. Medium shot (waist/knee), camera "
    "slightly below eye level, strong depth and leading lines from the rows.\n\n"
    "Wardrobe and pose: the woman wears a long, tight black dress; feminine calm "
    "posture; one hand resting on the armrest. The man wears a black suit, "
    "athletic build, sitting relaxed.\n\n"
    "Lighting: a bright projector beam from above/behind them, visible dust "
    "particles in the beam, strong cinematic highlights and dramatic shadows "
    "across their faces and clothing.\n\n"
    "Style: cinematic high-contrast black-and-white photorealism, subtle film "
    "grain, light vignette, 35mm film look. Focus is locked on the faces; "
    "moderate depth of field; background slightly blurred; ultra-detailed, "
    "realistic."
)


async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


@router.callback_query(F.data == MenuCallbacks.CINEMA_BW)
async def start_cinema_bw(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await safe_answer(call)
    await upsert_user(session, call.from_user.id, call.from_user.username)
    if await block_launch_for_call(call, session, reply_markup=buy_generations_kb()):
        return
    await state.clear()
    await state.set_state(CinemaBWFlow.female_photo)

    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass
        await send_content_photo(
            call.message,
            filename="kino.jpg",
            caption=(
                "🎞 <b>Одни в кинозале ЧБ</b>\n\n"
                "Сначала пришли фото девушки 📸"
            ),
            parse_mode="HTML",
        )


@router.message(CinemaBWFlow.female_photo)
async def cinema_bw_female_in(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Нужно фото девушки 📸 Отправь, пожалуйста, изображение.")
        return
    if message.media_group_id:
        await message.answer("Нужно одно фото (не альбом) 📸")
        return

    female_id = message.photo[-1].file_id
    await state.update_data(female_photo_id=female_id)
    await state.set_state(CinemaBWFlow.male_photo)
    await message.answer("Теперь пришли фото мужчины 📸")


@router.message(CinemaBWFlow.male_photo)
async def cinema_bw_male_in(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Нужно фото мужчины 📸 Отправь, пожалуйста, изображение.")
        return
    if message.media_group_id:
        await message.answer("Нужно одно фото (не альбом) 📸")
        return

    male_id = message.photo[-1].file_id
    data = await state.get_data()
    female_id = data.get("female_photo_id")
    if not female_id:
        await state.clear()
        await message.answer("Не вижу фото девушки 😕 Давай начнем заново: /start")
        return

    await state.update_data(male_photo_id=male_id)
    await state.set_state(CinemaBWFlow.confirm)
    await message.answer_photo(female_id, caption="Фото девушки")
    await message.answer_photo(male_id, caption="Фото мужчины")
    await message.answer(
        "Все верно? Если да — запускаю генерацию.",
        reply_markup=yes_no_kb(
            yes_text="✅ Всё верно",
            no_text="🔁 Отправить заново",
            no_style="danger",
        ),
    )


@router.callback_query(CinemaBWFlow.confirm, F.data == ConfirmCallbacks.NO)
async def cinema_bw_confirm_no(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CinemaBWFlow.female_photo)
    await edit_text_safe(
        call,
        "Хорошо! Сначала пришли фото девушки 📸",
        reply_markup=None,
    )
    await safe_answer(call)


@router.callback_query(CinemaBWFlow.confirm, F.data == ConfirmCallbacks.YES)
async def cinema_bw_confirm_yes(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    female_id = data.get("female_photo_id")
    male_id = data.get("male_photo_id")
    if not female_id or not male_id:
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
        await state.clear()
        await safe_answer(call)
        return

    sent_any = False
    try:
        results = await generate_image_kie_from_telegram(
            bot=call.bot,
            session=session,
            tg_id=tg_id,
            prompt=_PROMPT,
            telegram_photo_file_ids=[female_id, male_id],
            resolution="2K",
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
        return

    except KieAIError as e:
        logger.warning("CINEMA_BW generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, kie_error_to_user_text(e))
        await state.clear()
        return

    except Exception as e:
        logger.exception("CINEMA_BW generation failed: %s", e)
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
