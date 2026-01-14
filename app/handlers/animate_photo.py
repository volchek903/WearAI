from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiohttp
from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.db.config import settings  # settings.kie_api_key (env: KIE_API_KEY)
from app.keyboards.menu import MenuCallbacks, main_menu_kb
from app.states.animate_photo import AnimatePhotoStates
from app.utils.kie_kling_client import KieKlingClient

router = Router()
logger = logging.getLogger(__name__)

# Чтобы не плодить параллельные генерации на одного юзера
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


async def _status_spinner(
    bot, chat_id: int, message_id: int, stop: asyncio.Event
) -> None:
    frames = [
        "⏳ Генерирую видео",
        "⏳ Генерирую видео.",
        "⏳ Генерирую видео..",
        "⏳ Генерирую видео...",
    ]
    i = 0
    while not stop.is_set():
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=frames[i % len(frames)],
            )
        except Exception:
            # Не критично: могли удалить сообщение или Telegram ограничил частоту
            pass
        i += 1
        await asyncio.sleep(2)


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
        "Пришлите <b>одно фото</b>, которое хотите оживить.\n"
        "<i>(Не альбом / не несколько фото одним сообщением)</i>\n\n"
        "После этого я попрошу промпт и начну генерацию видео на <b>5 секунд</b>.\n\n"
        "💡 <b>Совет</b>: лучше работает фото без смаза, с хорошим светом и лицом в кадре."
    )

    # Редактируем прошлое сообщение и УБИРАЕМ кнопки
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=None)
    except Exception:
        # На случай, если редактирование недоступно (редко)
        await cb.message.answer(text, parse_mode="HTML")

    await cb.answer()


@router.message(AnimatePhotoStates.waiting_photo, F.photo)
async def animate_got_photo(message: Message, state: FSMContext) -> None:
    if not settings.kie_api_key:
        await message.answer("Не настроен KIE_API_KEY в .env.")
        await state.clear()
        logger.error("KIE_API_KEY missing in settings")
        return

    # Проверка: не альбом (media_group_id != None означает медиагруппу)
    if message.media_group_id is not None:
        await message.answer(
            "Пожалуйста, отправьте <b>одно</b> фото (не альбомом).", parse_mode="HTML"
        )
        logger.info(
            "User %s sent media group instead of single photo", message.from_user.id
        )
        return

    photo = message.photo[-1]  # последний — самое большое качество у Telegram
    tg_file = await message.bot.get_file(photo.file_id)
    file_path = tg_file.file_path
    if not file_path:
        await message.answer("Не удалось получить файл из Telegram. Попробуй ещё раз.")
        logger.warning("Telegram file_path is empty for user %s", message.from_user.id)
        return

    logger.info(
        "User %s photo received: file_id=%s path=%s",
        message.from_user.id,
        photo.file_id,
        file_path,
    )

    # Скачаем фото и загрузим в KIE, чтобы получить публичный image_url
    image_bytes = await _download_telegram_file(message.bot.token, file_path)
    filename = Path(file_path).name or "photo.jpg"

    client = KieKlingClient(settings.kie_api_key)
    try:
        image_url = await client.upload_image_bytes(
            image_bytes=image_bytes,
            filename=filename,
            upload_path=f"images/wearai/animate/{message.from_user.id}",
        )
    except Exception as e:
        await message.answer(f"Ошибка загрузки фото в KIE: {e}")
        await state.clear()
        logger.exception("KIE upload failed for user %s", message.from_user.id)
        return

    logger.info(
        "User %s uploaded to KIE. image_url=%s", message.from_user.id, image_url
    )

    await state.update_data(image_url=image_url)
    await state.set_state(AnimatePhotoStates.waiting_prompt)

    await message.answer(
        "Отлично! Теперь напишите, что вы хотите, чтобы происходило на данной фотке.",
    )


@router.message(AnimatePhotoStates.waiting_photo)
async def animate_waiting_photo_wrong(message: Message) -> None:
    await message.answer(
        "Сейчас нужно фото. Пришлите <b>одно</b> фото сообщением.", parse_mode="HTML"
    )


async def _run_video_job(
    chat_id: int, bot, task_id: str, user_id: int, status_message_id: int
) -> None:
    """
    Фоновая задача: ждём готовности и отправляем видео файлом.
    + анимация загрузки (spinner + chat action)
    """
    stop = asyncio.Event()
    spinner_task = asyncio.create_task(
        _status_spinner(bot, chat_id, status_message_id, stop)
    )
    action_task = asyncio.create_task(_chat_action_loop(bot, chat_id, stop))

    client = KieKlingClient(settings.kie_api_key)

    try:
        logger.info("User %s task started: task_id=%s", user_id, task_id)

        res = await client.wait_for_success(
            task_id, poll_interval_s=10, max_wait_s=12 * 60
        )

        if res.state == "timeout":
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text="Таймаут ожидания результата. Попробуйте ещё раз.",
            )
            logger.warning("User %s task timeout: task_id=%s", user_id, task_id)
            return

        if res.fail_msg:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=f"Генерация завершилась ошибкой: {res.fail_msg}",
            )
            logger.warning(
                "User %s task failed: task_id=%s fail=%s",
                user_id,
                task_id,
                res.fail_msg,
            )
            return

        if not res.result_url:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text="Готово, но не удалось найти ссылку на результат.",
            )
            logger.error(
                "User %s success without result_url: task_id=%s", user_id, task_id
            )
            return

        direct_url = await client.to_direct_download_url(res.result_url)
        logger.info("User %s result url: %s -> %s", user_id, res.result_url, direct_url)

        # Скачиваем и отправляем файлом (стабильнее и не превращается в GIF)
        video_bytes = await _download_bytes(direct_url, timeout_s=240)
        video_file = BufferedInputFile(video_bytes, filename="animation.mp4")

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_message_id,
            text="✅ Готово. Отправляю видео…",
        )
        await bot.send_video(
            chat_id=chat_id,
            video=video_file,
            caption="Готово. Если нужно — дай следующий промпт.",
            supports_streaming=True,
        )

        logger.info("User %s video sent OK: task_id=%s", user_id, task_id)

    except Exception as e:
        logger.exception("User %s error in job: task_id=%s", user_id, task_id)
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=f"Ошибка при ожидании/отправке видео: {e}",
            )
        except Exception:
            await bot.send_message(chat_id, f"Ошибка при ожидании/отправке видео: {e}")
    finally:
        stop.set()
        for t in (spinner_task, action_task):
            t.cancel()
        _active_jobs.pop(user_id, None)
        logger.info("User %s job cleaned up", user_id)


@router.message(AnimatePhotoStates.waiting_prompt, F.text)
async def animate_got_prompt(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id

    if user_id in _active_jobs and not _active_jobs[user_id].done():
        await message.answer(
            "У вас уже запущена генерация. Дождитесь результата или попробуйте позже."
        )
        logger.info("User %s tried to start second job while active", user_id)
        return

    data = await state.get_data()
    image_url = data.get("image_url")
    if not image_url:
        await message.answer(
            "Фото не найдено в контексте. Начните заново: «Оживить фото» → отправьте фото."
        )
        await state.clear()
        logger.warning("User %s missing image_url in state", user_id)
        return

    prompt = message.text.strip()
    if not prompt:
        await message.answer("Промпт пустой. Напишите, что должно происходить в видео.")
        return

    client = KieKlingClient(settings.kie_api_key)
    try:
        # duration="5" — строго 5 секунд
        # cfg_scale=1.0 — сильнее придерживаться промпта
        task_id = await client.create_kling_task(
            prompt=prompt,
            image_url=image_url,
            duration="5",
            negative_prompt="blur, distort, low quality, artifacts",
            cfg_scale=1.0,
        )
    except Exception as e:
        await message.answer(f"Не удалось запустить генерацию: {e}")
        await state.clear()
        logger.exception("User %s create task failed", user_id)
        return

    logger.info(
        "User %s created task: task_id=%s prompt_len=%s", user_id, task_id, len(prompt)
    )

    status_msg = await message.answer("⏳ Генерирую видео…")
    await state.clear()

    job = asyncio.create_task(
        _run_video_job(
            chat_id=message.chat.id,
            bot=message.bot,
            task_id=task_id,
            user_id=user_id,
            status_message_id=status_msg.message_id,
        )
    )
    _active_jobs[user_id] = job


@router.message(AnimatePhotoStates.waiting_prompt)
async def animate_waiting_prompt_wrong(message: Message) -> None:
    await message.answer(
        "Теперь нужен текстовый промпт: что должно происходить в видео."
    )
