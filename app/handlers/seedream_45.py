from __future__ import annotations

import asyncio
import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.extra import buy_generations_kb
from app.keyboards.menu import MenuCallbacks, photo_models_kb
from app.keyboards.utils import add_button
from app.repository.app_settings import MODEL_PRICE_SEEDREAM_V45_KEY
from app.repository.generations import (
    NoGenerationsLeft,
    charge_photo_generation,
    ensure_default_subscription,
    is_launch_subscription,
    refund_photo_generation,
    finalize_photo_generation,
)
from app.repository.users import increment_generated_photos, upsert_user
from app.services.generation import generate_seedream_v45_image
from app.services.wavespeed_ai import WaveSpeedError
from app.states.seedream_45_flow import Seedream45Flow
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

SEEDREAM45_MIN_DIMENSION = 1024
SEEDREAM45_MAX_DIMENSION = 4096
SEEDREAM45_MIN_TOTAL_PIXELS = 2560 * 1440
SEEDREAM45_MAX_TOTAL_PIXELS = 4096 * 4096
SEEDREAM45_SIZE_OPTIONS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]

SEEDREAM45_SETTINGS_SIZE = "seedream45:settings:size"
SEEDREAM45_SETTINGS_WIDTH = "seedream45:settings:width"
SEEDREAM45_SETTINGS_HEIGHT = "seedream45:settings:height"
SEEDREAM45_SETTINGS_GENERATE = "seedream45:settings:generate"
SEEDREAM45_CANCEL = "seedream45:cancel"

SEEDREAM45_SIZE_PRESETS = {
    "1:1": "2048*2048",
    "16:9": "2560*1440",
    "9:16": "1440*2560",
    "4:3": "2688*2016",
    "3:4": "2016*2688",
    "3:2": "2688*1792",
    "2:3": "1792*2688",
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


def _size_label(data: dict) -> str:
    width = data.get("width")
    height = data.get("height")
    if width and height:
        return f"{width}x{height}"
    size_mode = str(data.get("size_mode") or "auto")
    return "Auto" if size_mode == "auto" else size_mode


def _validate_custom_dimensions(width: int | None, height: int | None) -> str | None:
    if (width is None) != (height is None):
        return "Для custom size укажи и width, и height."
    if width is None or height is None:
        return None
    if (
        width < SEEDREAM45_MIN_DIMENSION
        or width > SEEDREAM45_MAX_DIMENSION
        or height < SEEDREAM45_MIN_DIMENSION
        or height > SEEDREAM45_MAX_DIMENSION
    ):
        return (
            f"Width и height должны быть в диапазоне "
            f"{SEEDREAM45_MIN_DIMENSION}-{SEEDREAM45_MAX_DIMENSION}."
        )
    total_pixels = width * height
    if (
        total_pixels < SEEDREAM45_MIN_TOTAL_PIXELS
        or total_pixels > SEEDREAM45_MAX_TOTAL_PIXELS
    ):
        return (
            "Для Seedream 4.5 total pixels должны быть в диапазоне "
            "от 2560x1440 до 4096x4096."
        )
    return None


def _settings_text(data: dict) -> str:
    prompt = html.escape(str(data.get("prompt") or "").strip())
    if len(prompt) > 300:
        prompt = f"{prompt[:300]}..."
    width = data.get("width") or "—"
    height = data.get("height") or "—"
    return (
        "⚙️ <b>Настройки Seedream 4.5</b>\n\n"
        f"<b>Промпт:</b>\n<blockquote>{prompt}</blockquote>\n"
        f"<b>Size:</b> {_size_label(data)}\n"
        f"<b>Width:</b> {width}\n"
        f"<b>Height:</b> {height}\n\n"
        "Если заданы и width, и height, они имеют приоритет над preset size."
    )


def _seedream45_settings_kb(data: dict):
    kb = InlineKeyboardBuilder()
    add_button(kb, text=f"📐 Size: {_size_label(data)}", callback_data=SEEDREAM45_SETTINGS_SIZE)
    add_button(kb, text=f"↔️ Width: {data.get('width') or '—'}", callback_data=SEEDREAM45_SETTINGS_WIDTH)
    add_button(kb, text=f"↕️ Height: {data.get('height') or '—'}", callback_data=SEEDREAM45_SETTINGS_HEIGHT)
    add_button(kb, text="✅ Сгенерировать", callback_data=SEEDREAM45_SETTINGS_GENERATE, style="success")
    add_button(kb, text="⬅️ К моделям", callback_data=SEEDREAM45_CANCEL, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def _build_seedream45_size(data: dict) -> str | None:
    width = data.get("width")
    height = data.get("height")
    if width and height:
        return f"{int(width)}*{int(height)}"
    size_mode = str(data.get("size_mode") or "auto")
    return SEEDREAM45_SIZE_PRESETS.get(size_mode)


async def _render_settings(target: CallbackQuery | Message, state: FSMContext) -> None:
    data = await state.get_data()
    await edit_text_safe(
        target,
        _settings_text(data),
        reply_markup=_seedream45_settings_kb(data),
    )


@router.callback_query(F.data == MenuCallbacks.SEEDREAM_45)
async def start_seedream_45(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await safe_answer(call)
    await upsert_user(session, call.from_user.id, call.from_user.username)
    if await block_launch_for_call(call, session, reply_markup=buy_generations_kb()):
        return

    await state.clear()
    await state.update_data(
        prompt="",
        size_mode="auto",
        width=None,
        height=None,
    )
    await state.set_state(Seedream45Flow.prompt)

    await edit_text_safe(
        call,
        "🪧 <b>Seedream 4.5</b>\n\n"
        "Пришли текстовый промпт для генерации изображения ✍️\n\n"
        "После этого можно будет настроить size, width и height.",
        reply_markup=None,
    )


@router.message(Seedream45Flow.prompt)
async def seedream_45_prompt_in(message: Message, state: FSMContext) -> None:
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
    await state.set_state(Seedream45Flow.settings)
    await _render_settings(message, state)


@router.callback_query(Seedream45Flow.settings, F.data == SEEDREAM45_SETTINGS_SIZE)
async def seedream_45_settings_size(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    next_size = _next_in_cycle(
        str(data.get("size_mode") or "auto"),
        SEEDREAM45_SIZE_OPTIONS,
    )
    await state.update_data(size_mode=next_size)
    await _render_settings(call, state)
    await safe_answer(call)


@router.callback_query(Seedream45Flow.settings, F.data == SEEDREAM45_SETTINGS_WIDTH)
async def seedream_45_settings_width(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Seedream45Flow.width)
    if call.message:
        await call.message.answer(
            f"Введи <b>width</b> от {SEEDREAM45_MIN_DIMENSION} до {SEEDREAM45_MAX_DIMENSION}.\n"
            "Отправь <code>очистить</code>, чтобы убрать значение."
        )
    await safe_answer(call)


@router.callback_query(Seedream45Flow.settings, F.data == SEEDREAM45_SETTINGS_HEIGHT)
async def seedream_45_settings_height(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Seedream45Flow.height)
    if call.message:
        await call.message.answer(
            f"Введи <b>height</b> от {SEEDREAM45_MIN_DIMENSION} до {SEEDREAM45_MAX_DIMENSION}.\n"
            "Отправь <code>очистить</code>, чтобы убрать значение."
        )
    await safe_answer(call)


async def _update_seedream45_dimension(
    message: Message,
    state: FSMContext,
    *,
    field: str,
) -> None:
    raw = (message.text or "").strip().lower()
    if raw in {"очистить", "clear", "-", "0"}:
        await state.update_data(**{field: None})
    else:
        try:
            value = int(raw)
        except Exception:
            await message.answer("Нужно целое число. Попробуй ещё раз ✍️")
            return
        if value < SEEDREAM45_MIN_DIMENSION or value > SEEDREAM45_MAX_DIMENSION:
            await message.answer(
                f"Значение должно быть в диапазоне {SEEDREAM45_MIN_DIMENSION}-{SEEDREAM45_MAX_DIMENSION}."
            )
            return
        await state.update_data(**{field: value})

    await state.set_state(Seedream45Flow.settings)
    await message.answer(
        _settings_text(await state.get_data()),
        reply_markup=_seedream45_settings_kb(await state.get_data()),
    )


@router.message(Seedream45Flow.width)
async def seedream_45_width_value(message: Message, state: FSMContext) -> None:
    await _update_seedream45_dimension(message, state, field="width")


@router.message(Seedream45Flow.height)
async def seedream_45_height_value(message: Message, state: FSMContext) -> None:
    await _update_seedream45_dimension(message, state, field="height")


@router.callback_query(Seedream45Flow.settings, F.data == SEEDREAM45_SETTINGS_GENERATE)
async def seedream_45_generate(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    width = data.get("width")
    height = data.get("height")
    dims_error = _validate_custom_dimensions(width, height)
    if dims_error:
        await safe_answer(call, dims_error, show_alert=True)
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
        await charge_photo_generation(
            session,
            tg_id,
            model_key=MODEL_PRICE_SEEDREAM_V45_KEY,
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
        results = await generate_seedream_v45_image(
            prompt=str(data.get("prompt") or "").strip(),
            size=_build_seedream45_size(data),
        )

        if not results:
            raise RuntimeError("WaveSpeed returned empty result")

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю результат…")

        for filename, img_bytes in results:
            await send_image_smart(call.message, img_bytes=img_bytes, filename=filename)
            sent_any = True
            await finalize_photo_generation(session, tg_id)

        await increment_generated_photos(
            session=session,
            tg_id=tg_id,
            delta=1,
            section="seedream_v45",
        )
        await state.clear()
        await call.message.answer(
            "Можно сгенерировать ещё что-нибудь ✨",
            reply_markup=photo_models_kb(),
        )
        return

    except WaveSpeedError as e:
        logger.warning("WaveSpeed rejected/failed: %s", e)
        if not sent_any:
            await refund_photo_generation(
                session,
                tg_id,
                model_key=MODEL_PRICE_SEEDREAM_V45_KEY,
            )
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, wavespeed_error_to_user_text(e))
        await state.clear()
        return

    except Exception as e:
        logger.exception("SEEDREAM_45 generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(
                session,
                tg_id,
                model_key=MODEL_PRICE_SEEDREAM_V45_KEY,
            )
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


@router.callback_query(F.data == SEEDREAM45_CANCEL)
async def seedream_45_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_text_safe(call, "Выбор моделей 👇", reply_markup=photo_models_kb())
    await safe_answer(call)
