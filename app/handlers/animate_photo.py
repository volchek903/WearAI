from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiohttp
from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import settings
from app.keyboards.menu import MenuCallbacks
from app.keyboards.extra import buy_generations_kb
from app.keyboards.menu import video_menu_kb
from app.models.subscription import Subscription
from app.models.user import User
from app.models.user_subscription import UserSubscription
from app.repository.generations import (
    charge_video_generation,
    refund_video_generation,
    NoGenerationsLeft,
)
from app.repository.users import increment_generated_videos
from app.states.animate_photo import AnimatePhotoStates
from app.utils.wavespeed_kling_client import WaveSpeedKlingClient
from app.utils.tg_edit import edit_text_safe
from app.utils.support_text import with_support
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress

router = Router()
logger = logging.getLogger(__name__)

MAX_INPUT_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB

# key = tg_id (telegram id) — чтобы не путать с users.id
_active_jobs: dict[int, asyncio.Task] = {}


async def _download_telegram_file(bot_token: str, file_path: str) -> bytes:
    url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=60)
    ) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()


async def _download_bytes(url: str, timeout_s: int = 180) -> bytes:
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout_s)
    ) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()


async def _chat_action_loop(bot, chat_id: int, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
        except Exception:
            pass
        await asyncio.sleep(5)


@router.callback_query(F.data == MenuCallbacks.ANIMATE)
async def animate_entry(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AnimatePhotoStates.waiting_photo)

    if cb.message is None:
        await cb.answer()
        return

    text = (
        "🎬 <b>Оживить фото</b>\n\n"
        "Пришлите <b>одно фото</b>, которое хотите оживить 📸\n"
        "<i>(Не альбом / не несколько фото одним сообщением)</i>\n\n"
        "После этого я попрошу промпт и начну генерацию видео на <b>5 секунд</b>.\n\n"
        "💡 <b>Совет</b>: лучше работает фото без смаза, с хорошим светом и лицом в кадре."
    )

    await edit_text_safe(cb, text, reply_markup=None)
    await cb.answer()


@router.message(AnimatePhotoStates.waiting_photo, F.photo)
async def animate_got_photo(message: Message, state: FSMContext) -> None:
    if not settings.kie_api_key:
        await message.answer("Не настроен WAVESPEED_API_KEY в .env 😕")
        await state.clear()
        logger.error("WAVESPEED_API_KEY missing in settings")
        return

    if message.media_group_id is not None:
        await message.answer(
            "Пожалуйста, отправьте <b>одно</b> фото (не альбомом) 📸",
            parse_mode="HTML",
        )
        return

    photo = message.photo[-1]
    if (photo.file_size or 0) > MAX_INPUT_PHOTO_BYTES:
        await message.answer(
            "Фото слишком большое 😕\n\n"
            "Пришлите изображение до 5 МБ, чтобы загрузка и генерация проходили стабильно."
        )
        return

    tg_file = await message.bot.get_file(photo.file_id)
    file_path = tg_file.file_path
    if not file_path:
        await message.answer("Не удалось получить файл из Telegram 😕 Попробуй ещё раз.")
        return

    image_bytes = await _download_telegram_file(message.bot.token, file_path)
    filename = Path(file_path).name or "photo.jpg"

    client = WaveSpeedKlingClient(settings.kie_api_key)
    try:
        image_url = await client.upload_image_bytes(
            image_bytes=image_bytes,
            filename=filename,
            upload_path=f"images/wearai/animate/{message.from_user.id}",
        )
    except Exception as e:
        await message.answer(with_support(f"Ошибка загрузки фото в WaveSpeed 😕: {e}"))
        await state.clear()
        logger.exception("WaveSpeed upload failed for user %s", message.from_user.id)
        return

    await state.update_data(image_url=image_url)
    await state.set_state(AnimatePhotoStates.waiting_prompt)

    await message.answer("Отлично! ✨ Теперь напишите, что должно происходить на видео.")


@router.message(AnimatePhotoStates.waiting_photo)
async def animate_waiting_photo_wrong(message: Message) -> None:
    await message.answer(
        "Сейчас нужно фото 📸 Пришлите <b>одно</b> фото сообщением.",
        parse_mode="HTML",
    )


async def _run_video_job(
    *,
    chat_id: int,
    bot,
    task_id: str,
    tg_id: int,
    status_message_id: int,
    session: AsyncSession,
) -> None:
    stop = asyncio.Event()
    progress_task = asyncio.create_task(
        progress_loop(
            lambda t: bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=t,
            ),
            stop,
            interval_s=7.0,
        )
    )
    action_task = asyncio.create_task(_chat_action_loop(bot, chat_id, stop))

    client = WaveSpeedKlingClient(settings.kie_api_key)

    try:
        res = await client.wait_for_success(task_id, poll_interval_s=10, max_wait_s=30 * 60)

        if res.state == "timeout":
            await refund_video_generation(session, tg_id)
            await stop_progress(stop, progress_task)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=with_support("Таймаут ожидания результата ⏳ Попробуйте ещё раз."),
            )
            return

        if res.fail_msg:
            await refund_video_generation(session, tg_id)
            await stop_progress(stop, progress_task)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=with_support(f"Генерация завершилась ошибкой: {res.fail_msg}"),
            )
            return

        if not res.result_url:
            await refund_video_generation(session, tg_id)
            await stop_progress(stop, progress_task)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=with_support("Готово, но не удалось найти ссылку на результат 😕"),
            )
            return

        direct_url = await client.to_direct_download_url(res.result_url)
        video_bytes = await _download_bytes(direct_url, timeout_s=240)
        video_file = BufferedInputFile(video_bytes, filename="animation.mp4")

        await stop_progress(stop, progress_task)
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_message_id,
            text="✅ Готово! Отправляю видео…",
        )
        await bot.send_video(
            chat_id=chat_id,
            video=video_file,
            caption="Готово! Если нужно — дай следующий промпт ✍️",
            supports_streaming=True,
        )
        await increment_generated_videos(session=session, tg_id=tg_id, delta=1, section="animate_photo")
        await bot.send_message(
            chat_id=chat_id,
            text="Хочешь сгенерировать ещё что-нибудь? ✨",
            reply_markup=video_menu_kb(),
        )

    except Exception as e:
        logger.exception("User %s error in job: task_id=%s", tg_id, task_id)
        await refund_video_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=with_support(f"Ошибка при ожидании/отправке видео: {e}"),
            )
        except Exception:
            await bot.send_message(
                chat_id, with_support(f"Ошибка при ожидании/отправке видео: {e}")
            )
    finally:
        stop.set()
        for t in (progress_task, action_task):
            t.cancel()
        _active_jobs.pop(tg_id, None)


@router.message(AnimatePhotoStates.waiting_prompt, F.text)
async def animate_got_prompt(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    tg_id = message.from_user.id

    if tg_id in _active_jobs and not _active_jobs[tg_id].done():
        await message.answer(
            "У тебя уже запущена генерация ⏳ Дождись результата или попробуй позже."
        )
        return

    data = await state.get_data()
    image_url = data.get("image_url")
    if not image_url:
        await message.answer(
            "Фото не найдено в контексте 😕 Начни заново: «Оживить фото» → отправь фото."
        )
        await state.clear()
        return

    prompt = (message.text or "").strip()
    if not prompt:
        await message.answer("Промпт пустой ✍️ Напиши, что должно происходить в видео.")
        return

    # --- DEBUG (можно потом убрать) ---
    logger.warning("ANIMATE_DEBUG tg_id=%s", tg_id)
    db_user_id = await session.scalar(select(User.id).where(User.tg_id == tg_id))
    logger.warning("ANIMATE_DEBUG db_user_id=%s", db_user_id)

    if db_user_id:
        row = await session.execute(
            select(
                UserSubscription.id,
                UserSubscription.status,
                UserSubscription.remaining_video,
                UserSubscription.remaining_photo,
                UserSubscription.expires_at,
                Subscription.name,
            )
            .select_from(UserSubscription)
            .join(Subscription, Subscription.id == UserSubscription.subscription_id)
            .where(UserSubscription.user_id == db_user_id)
            .order_by(UserSubscription.activated_at.desc())
            .limit(5)
        )
        logger.warning("ANIMATE_DEBUG last_subscriptions=%s", row.all())

        row_active = await session.execute(
            select(
                UserSubscription.id,
                UserSubscription.remaining_video,
                UserSubscription.remaining_photo,
                UserSubscription.expires_at,
                Subscription.name,
            )
            .select_from(UserSubscription)
            .join(Subscription, Subscription.id == UserSubscription.subscription_id)
            .where(UserSubscription.user_id == db_user_id, UserSubscription.status == 1)
            .order_by(UserSubscription.activated_at.desc())
            .limit(1)
        )
        logger.warning("ANIMATE_DEBUG active_subscription=%s", row_active.first())
    # --- /DEBUG ---

    try:
        # ✅ ВАЖНО: generations.py (версия A) ждёт tg_id
        await charge_video_generation(session, tg_id)
    except NoGenerationsLeft:
        await message.answer(
            "⛔️ Недостаточно кредитов.\n\nПополните баланс 💳",
            reply_markup=buy_generations_kb(),
        )
        return

    client = WaveSpeedKlingClient(settings.kie_api_key)
    try:
        task_id = await client.create_kling_task(
            prompt=prompt,
            image_url=image_url,
            duration="5",
            negative_prompt="blur, distort, low quality, artifacts",
            cfg_scale=1.0,
        )
    except Exception as e:
        await refund_video_generation(session, tg_id)
        await message.answer(f"Не удалось запустить генерацию 😕: {e}")
        await state.clear()
        return

    status_msg = await message.answer(progress_initial_text())
    await state.clear()

    job = asyncio.create_task(
        _run_video_job(
            chat_id=message.chat.id,
            bot=message.bot,
            task_id=task_id,
            tg_id=tg_id,
            status_message_id=status_msg.message_id,
            session=session,
        )
    )
    _active_jobs[tg_id] = job


@router.message(AnimatePhotoStates.waiting_prompt)
async def animate_waiting_prompt_wrong(message: Message) -> None:
    await message.answer(
        "Теперь нужен текстовый промпт ✍️ Что должно происходить в видео?"
    )
