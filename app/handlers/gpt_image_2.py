from __future__ import annotations

import asyncio
import html
import logging
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.photo_defaults import ASPECT_RATIOS
from app.keyboards.extra import buy_generations_kb
from app.keyboards.menu import MenuCallbacks, photo_models_kb
from app.keyboards.utils import add_button
from app.repository.app_settings import (
    MODEL_PRICE_GPT_IMAGE_2_EDIT_KEY,
    MODEL_PRICE_GPT_IMAGE_2_TEXT_TO_IMAGE_KEY,
    get_scaled_model_price_credits,
)
from app.repository.generations import (
    NoGenerationsLeft,
    charge_photo_generation,
    ensure_default_subscription,
    is_launch_subscription,
    refund_photo_generation,
)
from app.repository.users import increment_generated_photos, upsert_user
from app.services.album_collector import AlbumCollector
from app.services.generation import (
    generate_gpt_image_2_edit_from_telegram,
    generate_gpt_image_2_text_to_image,
    get_user_photo_settings,
)
from app.services.wavespeed_ai import WaveSpeedError
from app.states.gpt_image_2_flow import GptImage2Flow
from app.utils.launch_guard import block_launch_for_call
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.support_text import launch_limits_message, with_support
from app.utils.tg_callback import safe_answer
from app.utils.tg_edit import edit_text_safe
from app.utils.tg_send import send_image_smart
from app.utils.validators import MAX_TEXT_LEN, is_text_too_long
from app.utils.wavespeed_errors import wavespeed_error_to_user_text

router = Router()
logger = logging.getLogger(__name__)
_album = AlbumCollector(debounce_seconds=0.8)

GPT_IMAGE_2_EDIT_MAX_IMAGES = 5
GPT_IMAGE_2_QUALITY_OPTIONS = ["low", "medium", "high"]
GPT_IMAGE_2_EDIT_RESOLUTION_OPTIONS = ["1k", "2k"]
GPT_IMAGE_2_TEXT_RESOLUTION_OPTIONS = ["1k", "2k", "4k"]

GPT_IMAGE_2_SETTINGS_ASPECT = "gpt_image_2:settings:aspect"
GPT_IMAGE_2_SETTINGS_RESOLUTION = "gpt_image_2:settings:resolution"
GPT_IMAGE_2_SETTINGS_QUALITY = "gpt_image_2:settings:quality"
GPT_IMAGE_2_SETTINGS_PHOTOS = "gpt_image_2:settings:photos"
GPT_IMAGE_2_SETTINGS_GENERATE = "gpt_image_2:settings:generate"
GPT_IMAGE_2_CANCEL = "gpt_image_2:cancel"

MODEL_CFG = {
    MenuCallbacks.GPT_IMAGE_2_EDIT: {
        "title": "GPT Image 2 / Edit",
        "mode": "edit",
        "section": "gpt_image_2_edit",
        "model_key": MODEL_PRICE_GPT_IMAGE_2_EDIT_KEY,
        "caption": (
            "🖌 <b>GPT Image 2 / Edit</b>\n\n"
            "Пришли от 1 до 5 фото одним сообщением или альбомом 📸\n\n"
            "После этого я попрошу промпт и дам настроить aspect ratio, resolution и quality."
        ),
    },
    MenuCallbacks.GPT_IMAGE_2_TEXT_TO_IMAGE: {
        "title": "GPT Image 2 / Text to Image",
        "mode": "text_to_image",
        "section": "gpt_image_2_text_to_image",
        "model_key": MODEL_PRICE_GPT_IMAGE_2_TEXT_TO_IMAGE_KEY,
        "caption": (
            "🎨 <b>GPT Image 2 / Text to Image</b>\n\n"
            "Пришли текстовый промпт ✍️\n\n"
            "После этого можно будет настроить aspect ratio, resolution и quality."
        ),
    },
}

GPT_IMAGE_2_PROVIDER_COSTS = {
    "edit": {
        "1k": {
            "low": Decimal("0.030"),
            "medium": Decimal("0.060"),
            "high": Decimal("0.220"),
        },
        "2k": {
            "low": Decimal("0.060"),
            "medium": Decimal("0.120"),
            "high": Decimal("0.440"),
        },
    },
    "text_to_image": {
        "1k": {
            "low": Decimal("0.010"),
            "medium": Decimal("0.060"),
            "high": Decimal("0.220"),
        },
        "2k": {
            "low": Decimal("0.020"),
            "medium": Decimal("0.120"),
            "high": Decimal("0.440"),
        },
        "4k": {
            "low": Decimal("0.030"),
            "medium": Decimal("0.180"),
            "high": Decimal("0.660"),
        },
    },
}


async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


def _next_in_cycle(current: str, options: list[str]) -> str:
    if current not in options:
        return options[0]
    idx = options.index(current)
    return options[(idx + 1) % len(options)]


def _aspect_options(mode: str) -> list[str]:
    return ["auto", *ASPECT_RATIOS] if mode == "edit" else list(ASPECT_RATIOS)


def _resolution_options(mode: str) -> list[str]:
    if mode == "edit":
        return GPT_IMAGE_2_EDIT_RESOLUTION_OPTIONS
    return GPT_IMAGE_2_TEXT_RESOLUTION_OPTIONS


def _aspect_label(value: str) -> str:
    return "Auto" if value == "auto" else value


def _resolution_label(value: str) -> str:
    return str(value or "1k").upper()


def _quality_label(value: str) -> str:
    return str(value or "medium").capitalize()


def _provider_cost(mode: str, resolution: str, quality: str) -> Decimal:
    return GPT_IMAGE_2_PROVIDER_COSTS[mode][resolution][quality]


def _settings_text(data: dict) -> str:
    prompt = html.escape(str(data.get("prompt") or "").strip())
    if len(prompt) > 300:
        prompt = f"{prompt[:300]}..."

    mode = str(data.get("mode") or "text_to_image")
    lines = [
        f"⚙️ <b>{html.escape(str(data.get('title') or 'GPT Image 2'))}</b>",
        "",
        f"<b>Промпт:</b>\n<blockquote>{prompt}</blockquote>",
        f"<b>Aspect ratio:</b> {_aspect_label(str(data.get('aspect_ratio') or '1:1'))}",
        f"<b>Resolution:</b> {_resolution_label(str(data.get('resolution') or '1k'))}",
        f"<b>Quality:</b> {_quality_label(str(data.get('quality') or 'medium'))}",
    ]
    if mode == "edit":
        lines.insert(
            3,
            f"<b>Фото:</b> {len(list(data.get('photos', []) or []))}/{GPT_IMAGE_2_EDIT_MAX_IMAGES}",
        )
    return "\n".join(lines)


def _settings_kb(data: dict):
    kb = InlineKeyboardBuilder()
    mode = str(data.get("mode") or "text_to_image")
    add_button(
        kb,
        text=f"📐 Aspect: {_aspect_label(str(data.get('aspect_ratio') or '1:1'))}",
        callback_data=GPT_IMAGE_2_SETTINGS_ASPECT,
    )
    add_button(
        kb,
        text=f"🖼 Resolution: {_resolution_label(str(data.get('resolution') or '1k'))}",
        callback_data=GPT_IMAGE_2_SETTINGS_RESOLUTION,
    )
    add_button(
        kb,
        text=f"✨ Quality: {_quality_label(str(data.get('quality') or 'medium'))}",
        callback_data=GPT_IMAGE_2_SETTINGS_QUALITY,
    )
    if mode == "edit":
        add_button(
            kb,
            text="📸 Изменить фото",
            callback_data=GPT_IMAGE_2_SETTINGS_PHOTOS,
        )
    add_button(
        kb,
        text="✅ Сгенерировать",
        callback_data=GPT_IMAGE_2_SETTINGS_GENERATE,
        style="success",
    )
    add_button(kb, text="⬅️ К моделям", callback_data=GPT_IMAGE_2_CANCEL, style="danger")
    kb.adjust(1)
    return kb.as_markup()


async def _render_settings(target: CallbackQuery | Message, state: FSMContext) -> None:
    data = await state.get_data()
    await edit_text_safe(
        target,
        _settings_text(data),
        reply_markup=_settings_kb(data),
    )


def _default_resolution(value: str, mode: str) -> str:
    normalized = str(value or "").strip().lower()
    options = _resolution_options(mode)
    if normalized not in options:
        return options[0]
    return normalized


def _default_aspect(value: str, mode: str) -> str:
    if mode == "edit":
        return "auto"
    normalized = str(value or "").strip()
    return normalized if normalized in ASPECT_RATIOS else "1:1"


async def _charge_credits_for_current_selection(
    session: AsyncSession,
    *,
    tg_id: int,
    model_key: str,
    mode: str,
    resolution: str,
    quality: str,
) -> None:
    credits_to_charge = await get_scaled_model_price_credits(
        session,
        model_key,
        _provider_cost(mode, resolution, quality),
    )
    await charge_photo_generation(
        session,
        tg_id,
        model_key=model_key,
        credits_override=credits_to_charge,
    )


@router.callback_query(
    F.data.in_(
        {
            MenuCallbacks.GPT_IMAGE_2_EDIT,
            MenuCallbacks.GPT_IMAGE_2_TEXT_TO_IMAGE,
        }
    )
)
async def start_gpt_image_2(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await safe_answer(call)
    await upsert_user(session, call.from_user.id, call.from_user.username)
    if await block_launch_for_call(call, session, reply_markup=buy_generations_kb()):
        return

    cfg = MODEL_CFG.get(str(call.data))
    if not cfg:
        return

    user_settings = await get_user_photo_settings(session, call.from_user.id)

    await state.clear()
    await state.update_data(
        title=cfg["title"],
        mode=cfg["mode"],
        section=cfg["section"],
        model_key=cfg["model_key"],
        prompt="",
        photos=[],
        aspect_ratio=_default_aspect(user_settings.aspect_ratio, str(cfg["mode"])),
        resolution=_default_resolution(user_settings.resolution, str(cfg["mode"])),
        quality="medium",
    )

    if cfg["mode"] == "edit":
        await state.set_state(GptImage2Flow.photos)
    else:
        await state.set_state(GptImage2Flow.prompt)

    await edit_text_safe(
        call,
        str(cfg["caption"]),
        reply_markup=None,
        parse_mode="HTML",
    )


@router.message(GptImage2Flow.photos)
async def gpt_image_2_photos_in(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if str(data.get("mode") or "") != "edit":
        return

    if not message.photo:
        await message.answer(
            f"Нужно отправить от 1 до {GPT_IMAGE_2_EDIT_MAX_IMAGES} фото одним сообщением или альбомом 📸"
        )
        return

    file_ids: list[str]
    if not message.media_group_id:
        file_ids = [message.photo[-1].file_id]
    else:
        await _album.push(
            message.chat.id,
            message.media_group_id,
            message.photo[-1].file_id,
        )
        result = await _album.collect(message.chat.id, message.media_group_id)
        if not result.file_ids:
            return
        file_ids = result.file_ids

    if not (1 <= len(file_ids) <= GPT_IMAGE_2_EDIT_MAX_IMAGES):
        await message.answer(
            f"Нужно отправить от 1 до {GPT_IMAGE_2_EDIT_MAX_IMAGES} фото одним сообщением или альбомом 📸"
        )
        return

    await state.update_data(photos=file_ids)
    prompt_exists = bool(str(data.get("prompt") or "").strip())
    if prompt_exists:
        await state.set_state(GptImage2Flow.settings)
        await _render_settings(message, state)
        return

    await state.set_state(GptImage2Flow.prompt)
    await message.answer("Отлично! Теперь пришли промпт ✍️")


@router.message(GptImage2Flow.prompt)
async def gpt_image_2_prompt_in(message: Message, state: FSMContext) -> None:
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

    await state.update_data(prompt=prompt)
    await state.set_state(GptImage2Flow.settings)
    await _render_settings(message, state)


@router.callback_query(GptImage2Flow.settings, F.data == GPT_IMAGE_2_SETTINGS_ASPECT)
async def gpt_image_2_settings_aspect(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    mode = str(data.get("mode") or "text_to_image")
    next_value = _next_in_cycle(
        str(data.get("aspect_ratio") or _default_aspect("", mode)),
        _aspect_options(mode),
    )
    await state.update_data(aspect_ratio=next_value)
    await _render_settings(call, state)
    await safe_answer(call)


@router.callback_query(GptImage2Flow.settings, F.data == GPT_IMAGE_2_SETTINGS_RESOLUTION)
async def gpt_image_2_settings_resolution(
    call: CallbackQuery, state: FSMContext
) -> None:
    data = await state.get_data()
    mode = str(data.get("mode") or "text_to_image")
    next_value = _next_in_cycle(
        str(data.get("resolution") or _default_resolution("", mode)),
        _resolution_options(mode),
    )
    await state.update_data(resolution=next_value)
    await _render_settings(call, state)
    await safe_answer(call)


@router.callback_query(GptImage2Flow.settings, F.data == GPT_IMAGE_2_SETTINGS_QUALITY)
async def gpt_image_2_settings_quality(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    next_value = _next_in_cycle(
        str(data.get("quality") or "medium"),
        GPT_IMAGE_2_QUALITY_OPTIONS,
    )
    await state.update_data(quality=next_value)
    await _render_settings(call, state)
    await safe_answer(call)


@router.callback_query(GptImage2Flow.settings, F.data == GPT_IMAGE_2_SETTINGS_PHOTOS)
async def gpt_image_2_settings_photos(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(photos=[])
    await state.set_state(GptImage2Flow.photos)
    if call.message:
        await call.message.answer(
            f"Пришли новые фото для редактирования: от 1 до {GPT_IMAGE_2_EDIT_MAX_IMAGES} штук одним сообщением или альбомом 📸"
        )
    await safe_answer(call)


@router.callback_query(GptImage2Flow.settings, F.data == GPT_IMAGE_2_SETTINGS_GENERATE)
async def gpt_image_2_generate(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    mode = str(data.get("mode") or "text_to_image")
    prompt = str(data.get("prompt") or "").strip()
    photos = list(data.get("photos", []) or [])
    model_key = str(data.get("model_key") or "")
    resolution = str(data.get("resolution") or "1k")
    quality = str(data.get("quality") or "medium")

    if not prompt:
        await safe_answer(call, "Сначала пришли промпт.", show_alert=True)
        return
    if mode == "edit" and not photos:
        await safe_answer(call, "Сначала пришли фото для редактирования.", show_alert=True)
        return

    await safe_answer(call)
    progress_msg = await call.message.answer(progress_initial_text())
    stop = asyncio.Event()
    progress_task = asyncio.create_task(
        progress_loop(lambda t: _update_progress_message(progress_msg, t), stop)
    )

    user = await upsert_user(session, call.from_user.id, call.from_user.username)
    tg_id = user.tg_id
    await ensure_default_subscription(session, tg_id)

    try:
        await _charge_credits_for_current_selection(
            session,
            tg_id=tg_id,
            model_key=model_key,
            mode=mode,
            resolution=resolution,
            quality=quality,
        )
    except NoGenerationsLeft:
        await stop_progress(stop, progress_task)
        if await is_launch_subscription(session, tg_id):
            await edit_text_safe(
                progress_msg,
                launch_limits_message(),
                reply_markup=buy_generations_kb(),
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
        aspect_ratio = str(data.get("aspect_ratio") or "").strip() or None
        if aspect_ratio == "auto":
            aspect_ratio = None

        if mode == "edit":
            results = await generate_gpt_image_2_edit_from_telegram(
                bot=call.message.bot,
                session=session,
                tg_id=tg_id,
                prompt=prompt,
                telegram_photo_file_ids=photos,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                quality=quality,
                max_images=GPT_IMAGE_2_EDIT_MAX_IMAGES,
            )
        else:
            results = await generate_gpt_image_2_text_to_image(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                quality=quality,
            )

        if not results:
            raise RuntimeError("WaveSpeed returned empty result")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю результат…")

        for filename, img_bytes in results:
            await send_image_smart(call.message, img_bytes=img_bytes, filename=filename)
            sent_any = True

        await increment_generated_photos(
            session=session,
            tg_id=tg_id,
            delta=1,
            section=str(data.get("section") or mode),
        )
        await state.clear()
        await call.message.answer(
            "Можно сгенерировать ещё что-нибудь.",
            reply_markup=photo_models_kb(),
        )
        return

    except WaveSpeedError as e:
        logger.warning("WaveSpeed rejected/failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id, model_key=model_key)
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, wavespeed_error_to_user_text(e))
        await state.clear()
        return

    except Exception as e:
        logger.exception("GPT_IMAGE_2 generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(session, tg_id, model_key=model_key)
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


@router.callback_query(F.data == GPT_IMAGE_2_CANCEL)
async def gpt_image_2_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_text_safe(call, "Выбор моделей 👇", reply_markup=photo_models_kb())
    await safe_answer(call)
