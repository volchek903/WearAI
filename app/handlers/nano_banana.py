from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.menu import MenuCallbacks, SettingsCallbacks, photo_models_kb
from app.keyboards.extra import buy_generations_kb
from app.repository.app_settings import MODEL_PRICE_NANO_BANANA_PRO_KEY
from app.repository.generations import (
    NoGenerationsLeft,
    charge_photo_generation,
    ensure_default_subscription,
    refund_photo_generation,
    is_launch_subscription,
)
from app.repository.users import increment_generated_photos, upsert_user
from app.services.album_collector import AlbumCollector
from app.services.generation import generate_image_wavespeed_from_telegram
from app.services.wavespeed_ai import WaveSpeedError
from app.states.nano_banana_flow import NanoBananaFlow
from app.utils.wavespeed_errors import wavespeed_error_to_user_text
from app.utils.progress_bar import (
    progress_initial_text,
    progress_loop,
    stop_progress,
)
from app.utils.tg_edit import edit_text_safe
from app.utils.tg_send import send_image_smart
from app.utils.validators import MAX_TEXT_LEN, is_text_too_long
from app.utils.support_text import with_support, launch_limits_message
from app.utils.launch_guard import block_launch_for_call
from app.utils.tg_callback import safe_answer

router = Router()
logger = logging.getLogger(__name__)
_album = AlbumCollector(debounce_seconds=0.8)

MODEL_CFG = {
    MenuCallbacks.NANO_BANANA: {
        "title": "Nano Banana 2",
        "caption": "🍌 <b>Nano Banana 2</b>\n\nПришли от 1 до 8 фото одним сообщением (альбомом) 📸",
        "min_images": 1,
        "max_images": 8,
        "model_key": None,
        "section": "nano_banana",
        "variant": "nano_banana_2",
    },
    SettingsCallbacks.NANO_BANANA: {
        "title": "Nano Banana 2",
        "caption": "🍌 <b>Nano Banana 2</b>\n\nПришли от 1 до 8 фото одним сообщением (альбомом) 📸",
        "min_images": 1,
        "max_images": 8,
        "model_key": None,
        "section": "nano_banana",
        "variant": "nano_banana_2",
    },
    MenuCallbacks.NANO_BANANA_PRO: {
        "title": "Nano Banana Pro",
        "caption": "🍌 <b>Nano Banana Pro</b>\n\nПришли от 1 до 10 фото одним сообщением (альбомом) 📸",
        "min_images": 1,
        "max_images": 10,
        "model_key": MODEL_PRICE_NANO_BANANA_PRO_KEY,
        "section": "nano_banana_pro",
        "variant": "nano_banana_pro",
    },
}

async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


@router.callback_query(
    F.data.in_({
        MenuCallbacks.NANO_BANANA,
        SettingsCallbacks.NANO_BANANA,
        MenuCallbacks.NANO_BANANA_PRO,
    })
)
async def start_nano_banana(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await safe_answer(call)
    await upsert_user(session, call.from_user.id, call.from_user.username)
    if await block_launch_for_call(call, session, reply_markup=buy_generations_kb()):
        return

    await state.clear()
    await state.set_state(NanoBananaFlow.photos)
    cfg = MODEL_CFG.get(str(call.data), MODEL_CFG[MenuCallbacks.NANO_BANANA])
    await state.update_data(
        model_key=cfg["model_key"],
        section=cfg["section"],
        title=cfg["title"],
        max_images=cfg["max_images"],
        min_images=cfg["min_images"],
        model_variant=cfg["variant"],
    )

    if call.message:
        await edit_text_safe(
            call,
            str(cfg["caption"]),
            reply_markup=None,
            parse_mode="HTML",
        )


@router.message(NanoBananaFlow.photos)
async def nano_banana_photos_in(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    min_images = int(data.get("min_images") or 1)
    max_images = int(data.get("max_images") or 8)

    if not message.photo:
        await message.answer(
            f"Нужно отправить <b>от {min_images} до {max_images} фото</b> одним сообщением (альбомом) 📸"
        )
        return

    if not message.media_group_id:
        file_id = message.photo[-1].file_id
        await state.update_data(photos=[file_id])
        await state.set_state(NanoBananaFlow.prompt)
        await message.answer("Отлично! Теперь пришли промпт ✍️")
        return

    await _album.push(
        message.chat.id, message.media_group_id, message.photo[-1].file_id
    )
    result = await _album.collect(message.chat.id, message.media_group_id)
    if not result.file_ids:
        return

    if not (min_images <= len(result.file_ids) <= max_images):
        await message.answer(
            f"Ой, тут должно быть <b>от {min_images} до {max_images} фото</b> одним сообщением. Попробуй ещё раз 📸"
        )
        return

    await state.update_data(photos=result.file_ids)
    await state.set_state(NanoBananaFlow.prompt)
    await message.answer("Отлично! Теперь пришли промпт ✍️")


@router.message(NanoBananaFlow.prompt)
async def nano_banana_prompt_in(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Нужен текст промпта ✍️ Отправь, пожалуйста, сообщение.")
        return

    prompt = message.text.strip()
    if is_text_too_long(prompt):
        await message.answer(
            f"Ой, текст слишком длинный 😅\n"
            f"Максимум {MAX_TEXT_LEN} символов, а у тебя {len(prompt)}.\n"
            "Сократи, пожалуйста, и отправь ещё раз 🙌"
        )
        return

    data = await state.get_data()
    photos: list[str] = data.get("photos", []) or []
    model_key = data.get("model_key")
    section = str(data.get("section") or "nano_banana")
    max_images = int(data.get("max_images") or 8)
    model_variant = str(data.get("model_variant") or "nano_banana_2")
    if not photos:
        await message.answer(
            "Не вижу фото для генерации 😅 Давай начнём заново: /start"
        )
        await state.clear()
        return

    progress_msg = await message.answer(progress_initial_text())
    stop = asyncio.Event()
    progress_task = asyncio.create_task(
        progress_loop(lambda t: _update_progress_message(progress_msg, t), stop)
    )

    user = await upsert_user(session, message.from_user.id, message.from_user.username)
    tg_id = user.tg_id

    await ensure_default_subscription(session, tg_id)

    try:
        if model_key:
            await charge_photo_generation(session, tg_id, model_key=model_key)
        else:
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
        return

    sent_any = False
    try:
        results = await generate_image_wavespeed_from_telegram(
            bot=message.bot,
            session=session,
            tg_id=tg_id,
            prompt=prompt,
            telegram_photo_file_ids=photos,
            max_images=max_images,
            model_variant=model_variant,
        )

        if not results:
            raise RuntimeError("WaveSpeed returned empty result")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю результат…")

        for filename, img_bytes in results:
            await send_image_smart(
                message, img_bytes=img_bytes, filename=filename
            )
            sent_any = True

        await increment_generated_photos(session=session, tg_id=tg_id, delta=1, section=section)
        await state.clear()
        await message.answer(
            "Хотите ли что-то ещё сгенерировать?",
            reply_markup=photo_models_kb(),
        )
        return

    except WaveSpeedError as e:
        logger.warning("WaveSpeed rejected/failed: %s", e)
        if not sent_any:
            if model_key:
                await refund_photo_generation(session, tg_id, model_key=model_key)
            else:
                await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, wavespeed_error_to_user_text(e))
        await state.clear()
        return

    except Exception as e:
        logger.exception("NANO_BANANA generation failed: %s", e)
        if not sent_any:
            if model_key:
                await refund_photo_generation(session, tg_id, model_key=model_key)
            else:
                await refund_photo_generation(session, tg_id)
        await stop_progress(stop, progress_task)
        await edit_text_safe(
            progress_msg,
            with_support(
                "Не получилось сгенерировать 😅\n"
                "Попробуй ещё раз или вернись в меню."
            ),
            reply_markup=photo_models_kb(),
        )
        await state.clear()
        return
