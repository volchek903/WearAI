from __future__ import annotations

import asyncio
import logging
import math

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import settings
from app.keyboards.confirm import ConfirmCallbacks, yes_no_kb
from app.keyboards.extra import buy_generations_kb
from app.keyboards.menu import MenuCallbacks, video_menu_kb
from app.keyboards.utils import add_button
from app.repository.app_settings import get_model_price_credits
from app.repository.generations import (
    NoGenerationsLeft,
    VIDEO_MODEL_MOTION_KEY,
    charge_video_generation,
    ensure_default_subscription,
    refund_video_generation,
    finalize_video_generation,
)
from app.repository.users import increment_generated_videos
from app.states.motion_control_flow import MotionControlFlow
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.support_text import with_support
from app.utils.tg_callback import safe_answer
from app.utils.tg_edit import edit_text_safe
from app.utils.tg_files import tg_file_id_to_bytes
from app.utils.content_media import get_content_file
from app.utils.wavespeed_kling_client import WaveSpeedKlingClient

router = Router()
logger = logging.getLogger(__name__)

MAX_INPUT_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB
MIN_INPUT_VIDEO_DURATION_S = 3
MAX_INPUT_VIDEO_DURATION_S = 30
MOTION_CONTROL_BILLING_STEP_S = 3
SKIP_PROMPT_CALLBACK = "motion_control:skip_prompt"


def _motion_control_fail_text(raw_error: str) -> str:
    raw = (raw_error or "").strip()
    raw_l = raw.lower()
    if "image recognition failed" in raw_l or "no complete upper body detected" in raw_l:
        return with_support(
            "Не получилось распознать человека на фото 😕\n\n"
            "Для этой модели нужна фотография, где верхняя часть тела хорошо видна: "
            "голова, плечи, грудь/торс должны помещаться в кадр целиком.\n\n"
            "Что попробовать:\n"
            "• отправить фото, где человек снят по пояс или крупнее\n"
            "• не обрезать голову, плечи и верх тела\n"
            "• выбрать более чёткое фото без сильного наклона и перекрытий"
        )
    return with_support(f"Генерация завершилась ошибкой: {raw}")


def _prompt_optional_kb():
    kb = InlineKeyboardBuilder()
    add_button(
        kb,
        text="⏭ Оставить промпт пустым",
        callback_data=SKIP_PROMPT_CALLBACK,
        style="success",
    )
    kb.adjust(1)
    return kb.as_markup()


async def _credits_per_second(session: AsyncSession) -> int:
    base_price = await get_model_price_credits(session, VIDEO_MODEL_MOTION_KEY)
    return max(1, math.ceil(base_price / MOTION_CONTROL_BILLING_STEP_S))


def _build_intro_text(*, credits_per_second: int) -> str:
    return (
        "🎞 <b>Оживить фото по видео</b>\n\n"
        "Пришлите <b>одно фото</b>, которое нужно превратить в видео 📸\n\n"
        f"Стоимость: <b>{credits_per_second}</b> кредитов за 1 секунду генерации.\n"
        f"Тарификация идёт блоками по <b>{MOTION_CONTROL_BILLING_STEP_S} сек</b>.\n\n"
        "Ограничения модели:\n"
        f"• видео-референс не может быть короче <b>{MIN_INPUT_VIDEO_DURATION_S} сек</b>\n"
        f"• видео-референс не может быть длиннее <b>{MAX_INPUT_VIDEO_DURATION_S} сек</b>\n"
        "• отправьте обычное видео сообщением, не документом\n"
        "• лучше работает чистый референс без резких скачков камеры\n\n"
        "После фото я попрошу видео-референс, затем промпт. Промпт можно оставить пустым."
    )


def _charged_seconds(duration_s: int) -> int:
    safe_duration = max(MIN_INPUT_VIDEO_DURATION_S, int(duration_s or 0))
    return max(
        MIN_INPUT_VIDEO_DURATION_S,
        math.ceil(safe_duration / MOTION_CONTROL_BILLING_STEP_S)
        * MOTION_CONTROL_BILLING_STEP_S,
    )


async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


@router.callback_query(F.data == MenuCallbacks.MOTION_CONTROL)
async def motion_control_entry(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    await state.set_state(MotionControlFlow.photo)
    credits_per_second = await _credits_per_second(session)
    await safe_answer(call)
    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.message.answer_video(
            get_content_file("kling_motion.mp4"),
            caption=_build_intro_text(credits_per_second=credits_per_second),
            parse_mode="HTML",
            request_timeout=20,
        )


@router.message(MotionControlFlow.photo)
async def motion_control_photo(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Нужно фото 📸 Отправь, пожалуйста, изображение.")
        return
    if message.media_group_id:
        await message.answer("Нужно одно фото (не альбом) 📸")
        return

    photo = message.photo[-1]
    if (photo.file_size or 0) > MAX_INPUT_PHOTO_BYTES:
        await message.answer(
            "Фото слишком большое 😕\n\n"
            "Для стабильной обработки отправь фото до 5 МБ."
        )
        return

    await state.update_data(photo_id=photo.file_id)
    await state.set_state(MotionControlFlow.video)
    await message.answer(
        "Теперь пришли <b>видео-референс</b> 🎬\n\n"
        f"Поддерживается длина от <b>{MIN_INPUT_VIDEO_DURATION_S}</b> до <b>{MAX_INPUT_VIDEO_DURATION_S}</b> секунд.",
        parse_mode="HTML",
    )


@router.message(MotionControlFlow.video)
async def motion_control_video(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not message.video:
        await message.answer("Нужно видео 🎬 Отправь, пожалуйста, видео-файл.")
        return

    duration_s = int(message.video.duration or 0)
    if duration_s < MIN_INPUT_VIDEO_DURATION_S:
        await message.answer(
            f"Видео слишком короткое 😕\n\n"
            f"Минимальная длина — <b>{MIN_INPUT_VIDEO_DURATION_S}</b> секунды.",
            parse_mode="HTML",
        )
        return
    if duration_s > MAX_INPUT_VIDEO_DURATION_S:
        await message.answer(
            f"Видео слишком длинное 😕\n\n"
            f"Поддерживается видео-референс до <b>{MAX_INPUT_VIDEO_DURATION_S}</b> секунд.",
            parse_mode="HTML",
        )
        return

    charged_seconds = _charged_seconds(duration_s)
    credits_per_second = await _credits_per_second(session)
    total_credits = credits_per_second * charged_seconds

    await state.update_data(
        video_id=message.video.file_id,
        video_duration_s=duration_s,
        charged_seconds=charged_seconds,
        total_credits=total_credits,
    )
    await state.set_state(MotionControlFlow.prompt)
    await message.answer(
        "Теперь напиши промпт для генерации ✍️\n\n"
        "Например: плавное движение волос, лёгкий поворот головы, кинематографичный свет.\n\n"
        "Если промпт не нужен, нажми кнопку ниже.\n\n"
        f"За это видео будет списано <b>{total_credits}</b> кредитов "
        f"({charged_seconds} сек тарификации).",
        reply_markup=_prompt_optional_kb(),
        parse_mode="HTML",
    )


@router.callback_query(MotionControlFlow.prompt, F.data == SKIP_PROMPT_CALLBACK)
async def motion_control_skip_prompt(
    call: CallbackQuery, state: FSMContext
) -> None:
    await state.update_data(prompt_text="")
    await _motion_control_send_preview(call.message, state)
    await state.set_state(MotionControlFlow.confirm)
    await safe_answer(call)


@router.message(MotionControlFlow.prompt)
async def motion_control_prompt(message: Message, state: FSMContext) -> None:
    prompt_text = (message.text or "").strip()
    await state.update_data(prompt_text=prompt_text)
    await _motion_control_send_preview(message, state)
    await state.set_state(MotionControlFlow.confirm)


async def _motion_control_send_preview(target: Message | None, state: FSMContext) -> None:
    if target is None:
        return
    data = await state.get_data()
    photo_id = data.get("photo_id")
    video_id = data.get("video_id")
    prompt_text = (data.get("prompt_text") or "").strip()
    total_credits = int(data.get("total_credits") or 0)
    charged_seconds = int(data.get("charged_seconds") or 0)

    if photo_id:
        await target.answer_photo(photo_id, caption="Фото для оживления")
    if video_id:
        await target.answer_video(video_id, caption="Видео-референс")
    if prompt_text:
        await target.answer(f"Промпт:\n<blockquote>{prompt_text}</blockquote>", parse_mode="HTML")

    await target.answer(
        "Все ли верно? ✅\n\n"
        f"К списанию: <b>{total_credits}</b> кредитов "
        f"за <b>{charged_seconds}</b> секунд тарификации.",
        reply_markup=yes_no_kb(
            yes_text="✅ Да, всё верно",
            no_text="❌ Нет",
            no_style="danger",
        ),
        parse_mode="HTML",
    )


@router.callback_query(MotionControlFlow.confirm, F.data == ConfirmCallbacks.NO)
async def motion_control_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if call.message:
        await edit_text_safe(
            call,
            "Хорошо, давай заново. Пришли фото 📸",
            reply_markup=None,
        )
    await state.set_state(MotionControlFlow.photo)
    await safe_answer(call)


@router.callback_query(MotionControlFlow.confirm, F.data == ConfirmCallbacks.YES)
async def motion_control_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    photo_id = data.get("photo_id")
    video_id = data.get("video_id")
    prompt_text = (data.get("prompt_text") or "").strip()
    total_credits = int(data.get("total_credits") or 0)

    if not photo_id or not video_id or total_credits <= 0:
        await state.clear()
        await safe_answer(call, "Не вижу фото/видео 😕", show_alert=True)
        return

    if call.message is None:
        await safe_answer(call)
        return

    try:
        await ensure_default_subscription(session, call.from_user.id)
        await charge_video_generation(
            session,
            call.from_user.id,
            model_key=VIDEO_MODEL_MOTION_KEY,
            credits_override=total_credits,
        )
    except NoGenerationsLeft:
        await edit_text_safe(
            call,
            "⛔️ Недостаточно кредитов.\n\nПополните баланс, чтобы запустить генерацию 💳",
            reply_markup=buy_generations_kb(),
        )
        await state.clear()
        await safe_answer(call)
        return

    progress_msg = await call.message.answer(progress_initial_text())
    stop = asyncio.Event()
    progress_task = asyncio.create_task(
        progress_loop(
            lambda t: _update_progress_message(progress_msg, t),
            stop,
            interval_s=7.0,
        )
    )

    client = WaveSpeedKlingClient(api_key=settings.kie_api_key)
    delivered = False
    try:
        photo_bytes = await tg_file_id_to_bytes(call.bot, photo_id, tg_id=call.from_user.id)
        video_bytes = await tg_file_id_to_bytes(call.bot, video_id, tg_id=call.from_user.id)

        photo_url = await client.upload_image_bytes(
            photo_bytes,
            filename=f"{call.from_user.id}_motion.jpg",
            upload_path=f"images/wearai/motion/{call.from_user.id}",
        )
        video_url = await client.upload_video_bytes(
            video_bytes,
            filename=f"{call.from_user.id}_motion.mp4",
            upload_path=f"videos/wearai/motion/{call.from_user.id}",
        )

        task_id = await client.create_motion_control_task(
            prompt=prompt_text,
            image_url=photo_url,
            video_url=video_url,
            character_orientation="image",
            mode="720p",
        )

        res = await client.wait_for_success(
            task_id, poll_interval_s=10, max_wait_s=30 * 60
        )
        if res.fail_msg:
            await refund_video_generation(
                session,
                call.from_user.id,
                model_key=VIDEO_MODEL_MOTION_KEY,
            )
            await stop_progress(stop, progress_task)
            await edit_text_safe(
                progress_msg,
                _motion_control_fail_text(res.fail_msg),
            )
            await state.clear()
            await safe_answer(call)
            return

        if not res.result_url:
            await refund_video_generation(
                session,
                call.from_user.id,
                model_key=VIDEO_MODEL_MOTION_KEY,
            )
            await stop_progress(stop, progress_task)
            await edit_text_safe(
                progress_msg,
                with_support("Готово, но не удалось найти ссылку 😕"),
            )
            await state.clear()
            await safe_answer(call)
            return

        direct_url = await client.to_direct_download_url(res.result_url)
        video_data = await _download_bytes(direct_url)
        video_file = BufferedInputFile(video_data, filename="motion_control.mp4")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю видео…")
        await call.bot.send_video(
            chat_id=call.message.chat.id,
            video=video_file,
            supports_streaming=True,
        )
        delivered = True
        await finalize_video_generation(session, call.from_user.id)

        await increment_generated_videos(
            session=session,
            tg_id=call.from_user.id,
            delta=1,
            section="motion_control",
        )
        await call.bot.send_message(
            chat_id=call.message.chat.id,
            text="Хочешь сгенерировать ещё что-нибудь? ✨",
            reply_markup=video_menu_kb(),
        )
        await state.clear()
        await safe_answer(call)

    except Exception as e:
        logger.exception("MOTION_CONTROL failed: %s", e)
        if not delivered:
            await refund_video_generation(
                session,
                call.from_user.id,
                model_key=VIDEO_MODEL_MOTION_KEY,
            )
        await stop_progress(stop, progress_task)
        await edit_text_safe(
            progress_msg,
            with_support("Не получилось сгенерировать 😅 Попробуй ещё раз чуть позже."),
        )
        await state.clear()
        await safe_answer(call)


async def _download_bytes(url: str, timeout_s: int = 240) -> bytes:
    import aiohttp

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout_s)
    ) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()
