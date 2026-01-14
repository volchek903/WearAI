from __future__ import annotations

import logging
from pathlib import Path

import aiohttp
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.db.config import settings
from app.keyboards.feedback import (
    FeedbackCallbacks,
    feedback_offer_video_kb,
    back_to_menu_kb,
)
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
    """
    Берём лучший output из feedback_payload.output_files:
    - приоритет photo
    - затем document
    Возвращаем (file_id, filename)
    """
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


async def _get_or_upload_kling_image_url(cb: CallbackQuery, state: FSMContext) -> str:
    """
    Из результата генерации (file_id в Telegram) делаем публичный image_url для Kling:
    - если уже есть fp["kling_image_url"] — используем
    - иначе скачиваем из Telegram -> upload в KIE -> кешируем в fp
    """
    data = await state.get_data()
    fp = data.get("feedback_payload")
    if not isinstance(fp, dict):
        raise RuntimeError("Сессия устарела. Сгенерируйте изображение заново.")

    scenario = str(fp.get("scenario") or "")
    if scenario not in {"model", "tryon"}:
        raise RuntimeError("Оживление доступно только после «Модель» или «Примерка».")

    cached = fp.get("kling_image_url")
    if isinstance(cached, str) and cached.strip():
        return cached.strip()

    if not settings.kie_api_key:
        raise RuntimeError("Не настроен KIE_API_KEY.")

    file_id, filename = _pick_best_output_file(fp)

    tg_file = await cb.bot.get_file(file_id)
    if not tg_file.file_path:
        raise RuntimeError("Не удалось получить file_path из Telegram.")

    image_bytes = await _download_telegram_file(cb.bot.token, tg_file.file_path)

    client = KieKlingClient(settings.kie_api_key)
    image_url = await client.upload_image_bytes(
        image_bytes=image_bytes,
        filename=Path(filename).name or "image.jpg",
        upload_path=f"images/wearai/generated/{scenario}/{cb.from_user.id}",
    )

    fp["kling_image_url"] = image_url
    await state.update_data(feedback_payload=fp)
    return image_url


# ✅ Всё хорошо -> редактируем сообщение -> предлагаем видео
@router.callback_query(FeedbackFlow.choice, F.data == FeedbackCallbacks.OK)
async def fb_ok(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.message is None:
        await cb.answer()
        return

    data = await state.get_data()
    fp = data.get("feedback_payload") or {}
    scenario = str(fp.get("scenario") or "")

    # если вдруг вызвали без payload — просто в меню
    if scenario not in {"model", "tryon"}:
        await edit_text_safe(cb, "Главное меню:", reply_markup=main_menu_kb())
        await state.clear()
        await cb.answer()
        return

    text = (
        "✅ <b>Отлично!</b>\n\n"
        "Желаете сгенерировать <b>видео на основе этого фото</b>?"
    )
    await edit_text_safe(cb, text, reply_markup=feedback_offer_video_kb())
    await state.set_state(FeedbackFlow.offer_video)
    await cb.answer()


# 🛠 Сообщить об ошибке -> просим текст
@router.callback_query(FeedbackFlow.choice, F.data == FeedbackCallbacks.BUG)
async def fb_bug(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.message is None:
        await cb.answer()
        return

    text = (
        "🛠 <b>Сообщить об ошибке</b>\n\n"
        "Опишите, пожалуйста, что пошло не так:\n"
        "— что ожидали\n"
        "— что получили\n"
        "— если есть, приложите скрин\n\n"
        "После сообщения я верну вас в меню."
    )
    await edit_text_safe(cb, text, reply_markup=back_to_menu_kb())
    await state.set_state(FeedbackFlow.text)
    await cb.answer()


# ⬅️ В меню (работает и на offer_video, и на text, и на choice)
@router.callback_query(F.data == FeedbackCallbacks.MENU)
async def fb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.message is None:
        await cb.answer()
        return

    await edit_text_safe(cb, "Главное меню:", reply_markup=main_menu_kb())
    await state.clear()
    await cb.answer()


# 🎬 Оживить фото -> спрашиваем промпт и переводим в AnimatePhotoStates.waiting_prompt
@router.callback_query(FeedbackFlow.offer_video, F.data == FeedbackCallbacks.ANIMATE)
async def fb_animate(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.message is None:
        await cb.answer()
        return

    try:
        image_url = await _get_or_upload_kling_image_url(cb, state)
    except Exception as e:
        logger.warning("Cannot start animate from feedback: %s", e)
        await edit_text_safe(cb, f"Ошибка: {e}", reply_markup=main_menu_kb())
        await state.clear()
        await cb.answer()
        return

    await state.update_data(image_url=image_url)
    await state.set_state(AnimatePhotoStates.waiting_prompt)

    text = (
        "🎬 <b>Оживить фото</b>\n\n"
        "Напишите, что должно произойти в видео на основе этой фотки.\n\n"
        "💡 Пример: «лёгкая улыбка, моргание, голова чуть вправо, камера плавно приближает»"
    )
    await edit_text_safe(cb, text, reply_markup=None)
    await cb.answer()


# Текст ошибки от пользователя
@router.message(FeedbackFlow.text)
async def fb_text(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip()
    if not txt:
        await message.answer("Нужен текст 🙂 Опишите проблему одним сообщением.")
        return

    # Тут можно отправлять менеджеру/в БД — пока логируем
    data = await state.get_data()
    fp = data.get("feedback_payload") or {}
    logger.info(
        "USER_FEEDBACK scenario=%s user=%s text=%s",
        fp.get("scenario"),
        fp.get("user_tg_id"),
        txt,
    )

    await message.answer(
        "Спасибо! ✅ Я записал сообщение. Возвращаю в меню.",
        reply_markup=main_menu_kb(),
    )
    await state.clear()
