from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

import aiohttp
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.db.config import settings
from app.keyboards.feedback import FeedbackCallbacks, feedback_offer_video_kb
from app.keyboards.menu import main_menu_kb
from app.states.animate_photo import AnimatePhotoStates
from app.states.feedback_flow import FeedbackFlow
from app.utils.kie_kling_client import KieKlingClient
from app.utils.tg_edit import edit_text_safe

router = Router()
logger = logging.getLogger(__name__)


async def _download_telegram_file(bot_token: str, file_path: str) -> bytes:
    url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=120)
    ) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()


def _pick_best_output_file(fp: dict) -> tuple[str, str]:
    output_files = fp.get("output_files") or []
    if not isinstance(output_files, list) or not output_files:
        raise RuntimeError(
            "Не найден результат генерации. Сгенерируйте изображение заново."
        )

    for item in output_files:
        if (
            isinstance(item, dict)
            and item.get("kind") == "photo"
            and item.get("file_id")
        ):
            return str(item["file_id"]), str(item.get("filename") or "image.jpg")

    for item in output_files:
        if (
            isinstance(item, dict)
            and item.get("kind") == "document"
            and item.get("file_id")
        ):
            return str(item["file_id"]), str(item.get("filename") or "image.jpg")

    raise RuntimeError("Не удалось определить file_id результата генерации.")


def _read_local_best_image_from_feedback(fp: dict) -> tuple[bytes, str, str]:
    best = fp.get("best_local_path")
    src_path: str | None = str(best) if isinstance(best, str) and best.strip() else None

    if not src_path:
        paths = fp.get("local_output_paths")
        if isinstance(paths, list) and paths:
            first = paths[0]
            if isinstance(first, str) and first.strip():
                src_path = first.strip()

    if not src_path:
        raise RuntimeError("Не найден локальный файл результата (best_local_path).")

    p = Path(src_path)
    if not p.exists() or not p.is_file():
        raise RuntimeError(f"Локальный файл результата не найден: {p}")

    data = p.read_bytes()
    filename = p.name or "image.png"
    return data, filename, str(p)


async def _get_or_upload_kling_image_url(cb: CallbackQuery, state: FSMContext) -> str:
    data = await state.get_data()
    fp = data.get("feedback_payload")
    if not isinstance(fp, dict):
        raise RuntimeError("Сессия устарела. Сгенерируйте изображение заново.")

    scenario = str(fp.get("scenario") or "")
    if scenario not in {"model", "tryon"}:
        raise RuntimeError("Оживление доступно только после «Модель» или «Примерка».")

    cached_url = fp.get("kling_image_url")
    cached_src = fp.get("kling_image_source_path")

    image_bytes: bytes | None = None
    filename: str = "image.png"
    source_path: str | None = None

    try:
        image_bytes, filename, source_path = _read_local_best_image_from_feedback(fp)
        if (
            isinstance(cached_url, str)
            and cached_url.strip()
            and isinstance(cached_src, str)
            and source_path
            and cached_src == source_path
        ):
            return cached_url.strip()
    except Exception as e:
        logger.warning("No local image for video, fallback to Telegram. err=%s", e)

    if not settings.kie_api_key:
        raise RuntimeError("Не настроен KIE_API_KEY.")

    if image_bytes is None:
        file_id, filename_from_payload = _pick_best_output_file(fp)
        tg_file = await cb.bot.get_file(file_id)
        if not tg_file.file_path:
            raise RuntimeError("Не удалось получить file_path из Telegram.")
        image_bytes = await _download_telegram_file(cb.bot.token, tg_file.file_path)
        filename = Path(filename_from_payload).name or "image.jpg"
        source_path = f"tg:{file_id}"

        if (
            isinstance(cached_url, str)
            and cached_url.strip()
            and isinstance(cached_src, str)
            and cached_src == source_path
        ):
            return cached_url.strip()

    tag = f"{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"
    p = Path(filename)
    unique_filename = f"{p.stem or 'image'}_{tag}{p.suffix or '.png'}"

    client = KieKlingClient(settings.kie_api_key)
    image_url = await client.upload_image_bytes(
        image_bytes=image_bytes,
        filename=unique_filename,
        upload_path=f"images/wearai/video_source/{scenario}/{cb.from_user.id}/{tag}",
    )

    fp["kling_image_url"] = image_url
    fp["kling_image_source_path"] = source_path or ""
    await state.update_data(feedback_payload=fp)
    return image_url


@router.callback_query(FeedbackFlow.choice, F.data == FeedbackCallbacks.OK)
async def fb_ok(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.message is None:
        await cb.answer()
        return

    data = await state.get_data()
    fp = data.get("feedback_payload") or {}
    scenario = str(fp.get("scenario") or "")

    if scenario not in {"model", "tryon"}:
        await edit_text_safe(cb, "Главное меню 👇", reply_markup=main_menu_kb())
        await state.clear()
        await cb.answer()
        return

    text = (
        "✅ <b>Отлично!</b>\n\nХочешь сгенерировать <b>видео на основе этого фото</b>?"
    )
    await edit_text_safe(cb, text, reply_markup=feedback_offer_video_kb())
    await state.set_state(FeedbackFlow.offer_video)
    await cb.answer()


@router.callback_query(F.data == FeedbackCallbacks.MENU)
async def fb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.message is None:
        await cb.answer()
        return

    await edit_text_safe(cb, "Главное меню 👇", reply_markup=main_menu_kb())
    await state.clear()
    await cb.answer()


# ✅ ФИКС задержки UX: сразу отвечаем на callback + показываем "подготавливаю..."
@router.callback_query(F.data == FeedbackCallbacks.ANIMATE)
async def fb_animate(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.message is None:
        await cb.answer()
        return

    # 1) Сразу убираем "часики" у кнопки
    await cb.answer()

    cur_state = await state.get_state()
    data = await state.get_data()
    fp = data.get("feedback_payload")

    logger.info(
        "[fb_animate] tg_id=%s state=%s has_payload=%s scenario=%s",
        cb.from_user.id,
        cur_state,
        isinstance(fp, dict),
        (fp.get("scenario") if isinstance(fp, dict) else None),
    )

    if not isinstance(fp, dict):
        await edit_text_safe(
            cb,
            "Не вижу данных последней генерации 😅\n"
            "Сгенерируйте изображение заново и попробуйте ещё раз.",
            reply_markup=main_menu_kb(),
        )
        await state.clear()
        return

    # 2) Сразу рисуем промежуточный экран (самое важное для ощущения скорости)
    await edit_text_safe(
        cb,
        "⏳ Подготавливаю фото для видео…\n\n"
        "Это может занять пару секунд (загрузка в сервис).",
        reply_markup=None,
    )

    try:
        image_url = await _get_or_upload_kling_image_url(cb, state)
    except Exception as e:
        logger.warning("Cannot start animate from feedback: %s", e)
        await edit_text_safe(cb, f"Ошибка: {e}", reply_markup=main_menu_kb())
        await state.clear()
        return

    await state.update_data(image_url=image_url)
    await state.set_state(AnimatePhotoStates.waiting_prompt)

    text = (
        "🎬 <b>Оживить фото</b>\n\n"
        "Напиши, что должно произойти в видео на основе этой фотки.\n\n"
        "💡 Пример: «лёгкая улыбка, моргание, голова чуть вправо, камера плавно приближает»"
    )
    await edit_text_safe(cb, text, reply_markup=None)


@router.message(FeedbackFlow.text)
async def fb_text(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip()
    if not txt:
        await message.answer("Нужен текст ✍️ Опишите проблему одним сообщением.")
        return

    data = await state.get_data()
    fp = data.get("feedback_payload") or {}
    logger.info(
        "USER_FEEDBACK scenario=%s user=%s text=%s",
        fp.get("scenario"),
        fp.get("user_tg_id"),
        txt,
    )

    await message.answer(
        "Спасибо! ✅ Сообщение записал. Возвращаю в меню.",
        reply_markup=main_menu_kb(),
    )
    await state.clear()
