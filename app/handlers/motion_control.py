from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.confirm import ConfirmCallbacks, yes_no_kb
from app.keyboards.extra import buy_generations_kb
from app.keyboards.menu import MenuCallbacks, video_menu_kb
from app.repository.generations import (
    NoGenerationsLeft,
    charge_video_generation,
    refund_video_generation,
    ensure_default_subscription,
)
from app.repository.users import increment_generated_videos, upsert_user
from app.states.motion_control_flow import MotionControlFlow
from app.utils.kie_kling_client import KieKlingClient
from app.db.config import settings
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.tg_edit import edit_text_safe
from app.utils.tg_files import tg_file_id_to_bytes

router = Router()
logger = logging.getLogger(__name__)

MAX_INPUT_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_INPUT_VIDEO_DURATION_S = 10 * 60  # 10 minutes


async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


@router.callback_query(F.data == MenuCallbacks.MOTION_CONTROL)
async def motion_control_soon(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await edit_text_safe(
            call,
            "🎞 <b>Оживить фото по видео</b>\n\nСкоро будет доступно 🚧",
            reply_markup=video_menu_kb(),
            parse_mode="HTML",
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

    file_id = photo.file_id
    await state.update_data(photo_id=file_id)
    await state.set_state(MotionControlFlow.video)
    await message.answer("Теперь пришли видео-референс 🎬")


@router.message(MotionControlFlow.video)
async def motion_control_video(message: Message, state: FSMContext) -> None:
    if not message.video:
        await message.answer("Нужно видео 🎬 Отправь, пожалуйста, видео-файл.")
        return
    if int(message.video.duration or 0) > MAX_INPUT_VIDEO_DURATION_S:
        await message.answer(
            "Видео слишком длинное 😕\n\n"
            "Поддерживается видео-референс до 10 минут."
        )
        return

    file_id = message.video.file_id
    await state.update_data(video_id=file_id)
    await state.set_state(MotionControlFlow.confirm)

    data = await state.get_data()
    photo_id = data.get("photo_id")

    if photo_id:
        await message.answer_photo(photo_id, caption="Фото для оживления")
    await message.answer_video(file_id, caption="Видео-референс")
    await message.answer(
        "Все ли верно? ✅",
        reply_markup=yes_no_kb(
            yes_text="✅ Да, всё верно",
            no_text="❌ Нет",
            no_style="danger",
        ),
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
    await call.answer()


@router.callback_query(MotionControlFlow.confirm, F.data == ConfirmCallbacks.YES)
async def motion_control_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    photo_id = data.get("photo_id")
    video_id = data.get("video_id")

    if not photo_id or not video_id:
        await state.clear()
        await call.answer("Не вижу фото/видео 😕", show_alert=True)
        return

    if call.message is None:
        await call.answer()
        return

    try:
        await ensure_default_subscription(session, call.from_user.id)
        await charge_video_generation(session, call.from_user.id)
    except NoGenerationsLeft:
        await edit_text_safe(
            call,
            "⛔️ Лимит генераций исчерпан.\n\nОформи подписку или пополни баланс 💳",
            reply_markup=buy_generations_kb(),
        )
        await state.clear()
        await call.answer()
        return

    progress_msg = await call.message.answer(progress_initial_text())
    stop = asyncio.Event()
    progress_task = asyncio.create_task(
        progress_loop(lambda t: _update_progress_message(progress_msg, t), stop, interval_s=7.0)
    )

    client = KieKlingClient(api_key=settings.kie_api_key)
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
            prompt="",
            image_url=photo_url,
            video_url=video_url,
            character_orientation="image",
            mode="720p",
        )

        res = await client.wait_for_success(task_id, poll_interval_s=10, max_wait_s=20 * 60)
        if res.fail_msg:
            await refund_video_generation(session, call.from_user.id)
            await stop_progress(stop, progress_task)
            await edit_text_safe(
                progress_msg,
                f"Генерация завершилась ошибкой: {res.fail_msg}",
            )
            await state.clear()
            await call.answer()
            return

        if not res.result_url:
            await refund_video_generation(session, call.from_user.id)
            await stop_progress(stop, progress_task)
            await edit_text_safe(progress_msg, "Готово, но не удалось найти ссылку 😕")
            await state.clear()
            await call.answer()
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

        await increment_generated_videos(session=session, tg_id=call.from_user.id, delta=1)
        await call.bot.send_message(
            chat_id=call.message.chat.id,
            text="Хотите ли что-то ещё сгенерировать?",
            reply_markup=video_menu_kb(),
        )
        await state.clear()
        await call.answer()

    except Exception as e:
        logger.exception("MOTION_CONTROL failed: %s", e)
        await refund_video_generation(session, call.from_user.id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(
            progress_msg,
            "Не получилось сгенерировать 😅 Попробуй ещё раз чуть позже.",
        )
        await state.clear()
        await call.answer()


async def _download_bytes(url: str, timeout_s: int = 240) -> bytes:
    import aiohttp

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_s)) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()
