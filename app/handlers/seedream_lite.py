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
from app.repository.app_settings import MODEL_PRICE_SEEDREAM_V5_LITE_KEY
from app.repository.generations import (
    NoGenerationsLeft,
    charge_photo_generation,
    ensure_default_subscription,
    is_launch_subscription,
    refund_photo_generation,
)
from app.repository.users import increment_generated_photos, upsert_user
from app.services.album_collector import AlbumCollector
from app.services.generation import generate_seedream_v5_lite, get_user_photo_settings
from app.services.wavespeed_ai import WaveSpeedError
from app.states.seedream_flow import SeedreamFlow
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

SEEDREAM_MAX_REFERENCE_IMAGES = 10
SEEDREAM_MIN_DIMENSION = 1440
SEEDREAM_MAX_DIMENSION = 4096
SEEDREAM_MIN_TOTAL_PIXELS = 2560 * 1440
SEEDREAM_MAX_TOTAL_PIXELS = 4096 * 4096
SEEDREAM_SIZE_OPTIONS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]
SEEDREAM_FORMAT_OPTIONS = ["png", "jpg"]

SEEDREAM_REFS_CONTINUE = "seedream:refs:continue"
SEEDREAM_REFS_CLEAR = "seedream:refs:clear"
SEEDREAM_SETTINGS_SIZE = "seedream:settings:size"
SEEDREAM_SETTINGS_WIDTH = "seedream:settings:width"
SEEDREAM_SETTINGS_HEIGHT = "seedream:settings:height"
SEEDREAM_SETTINGS_FORMAT = "seedream:settings:format"
SEEDREAM_SETTINGS_GENERATE = "seedream:settings:generate"
SEEDREAM_SETTINGS_TO_REFS = "seedream:settings:to_refs"
SEEDREAM_CANCEL = "seedream:cancel"

SEEDREAM_SIZE_PRESETS = {
    "1:1": "2048*2048",
    "16:9": "3072*1728",
    "9:16": "1728*3072",
    "4:3": "2048*1536",
    "3:4": "1536*2048",
    "3:2": "2304*1536",
    "2:3": "1536*2304",
}


async def _update_progress_message(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        return


def _refs_text(ref_count: int) -> str:
    return (
        "🌱 <b>Seedream 5 Lite</b>\n\n"
        "1) Отправь промпт.\n"
        "2) Необязательно добавь до <b>10</b> референсов.\n"
        "3) Настрой размер и формат.\n\n"
        f"Референсов добавлено: <b>{ref_count}/{SEEDREAM_MAX_REFERENCE_IMAGES}</b>\n\n"
        "Пришли фото одним или несколькими сообщениями.\n"
        "Если референсы не нужны, жми кнопку ниже."
    )


def _next_in_cycle(current: str, options: list[str]) -> str:
    if current not in options:
        return options[0]
    idx = options.index(current)
    return options[(idx + 1) % len(options)]


def _seedream_refs_kb(ref_count: int):
    kb = InlineKeyboardBuilder()
    continue_label = "➡️ К настройкам" if ref_count > 0 else "➡️ Продолжить без фото"
    add_button(kb, text=continue_label, callback_data=SEEDREAM_REFS_CONTINUE, style="success")
    if ref_count > 0:
        add_button(kb, text="🗑 Очистить фото", callback_data=SEEDREAM_REFS_CLEAR, style="danger")
    add_button(kb, text="⬅️ К моделям", callback_data=SEEDREAM_CANCEL, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def _size_label(data: dict) -> str:
    width = data.get("width")
    height = data.get("height")
    if width and height:
        return f"{width}x{height}"
    size_mode = str(data.get("size_mode") or "auto")
    return "Auto" if size_mode == "auto" else size_mode


def _format_label(data: dict) -> str:
    return str(data.get("output_format") or "png").upper()


def _settings_text(data: dict) -> str:
    prompt = html.escape(str(data.get("prompt") or "").strip())
    if len(prompt) > 300:
        prompt = f"{prompt[:300]}..."
    ref_count = len(list(data.get("photos", []) or []))
    width = data.get("width") or "—"
    height = data.get("height") or "—"
    size_line = _size_label(data)
    format_line = _format_label(data)
    mode_line = "edit mode" if ref_count > 0 else "text-to-image"
    return (
        "⚙️ <b>Настройки Seedream 5 Lite</b>\n\n"
        f"<b>Промпт:</b>\n<blockquote>{prompt}</blockquote>\n"
        f"<b>Режим:</b> {mode_line}\n"
        f"<b>Референсы:</b> {ref_count}/{SEEDREAM_MAX_REFERENCE_IMAGES}\n"
        f"<b>Size:</b> {size_line}\n"
        f"<b>Width:</b> {width}\n"
        f"<b>Height:</b> {height}\n"
        f"<b>Format:</b> {format_line}\n\n"
        "Если заданы и width, и height, они имеют приоритет над preset size."
    )


def _seedream_settings_kb(data: dict):
    kb = InlineKeyboardBuilder()
    add_button(kb, text=f"📐 Size: {_size_label(data)}", callback_data=SEEDREAM_SETTINGS_SIZE)
    add_button(kb, text=f"↔️ Width: {data.get('width') or '—'}", callback_data=SEEDREAM_SETTINGS_WIDTH)
    add_button(kb, text=f"↕️ Height: {data.get('height') or '—'}", callback_data=SEEDREAM_SETTINGS_HEIGHT)
    add_button(kb, text=f"🗂 Format: {_format_label(data)}", callback_data=SEEDREAM_SETTINGS_FORMAT)
    add_button(kb, text="🖼 Изменить фото", callback_data=SEEDREAM_SETTINGS_TO_REFS)
    add_button(kb, text="✅ Сгенерировать", callback_data=SEEDREAM_SETTINGS_GENERATE, style="success")
    add_button(kb, text="⬅️ К моделям", callback_data=SEEDREAM_CANCEL, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def _build_seedream_size(data: dict) -> str | None:
    width = data.get("width")
    height = data.get("height")
    if width and height:
        return f"{int(width)}*{int(height)}"
    size_mode = str(data.get("size_mode") or "auto")
    return SEEDREAM_SIZE_PRESETS.get(size_mode)


def _validate_custom_dimensions(width: int | None, height: int | None) -> str | None:
    if (width is None) != (height is None):
        return "Для custom size укажи и width, и height."
    if width is None or height is None:
        return None
    if (
        width < SEEDREAM_MIN_DIMENSION
        or width > SEEDREAM_MAX_DIMENSION
        or height < SEEDREAM_MIN_DIMENSION
        or height > SEEDREAM_MAX_DIMENSION
    ):
        return (
            f"Width и height должны быть в диапазоне "
            f"{SEEDREAM_MIN_DIMENSION}-{SEEDREAM_MAX_DIMENSION}."
        )
    total_pixels = width * height
    if total_pixels < SEEDREAM_MIN_TOTAL_PIXELS or total_pixels > SEEDREAM_MAX_TOTAL_PIXELS:
        return (
            "Для Seedream 5 Lite total pixels должны быть в диапазоне "
            "от 2560x1440 до 4096x4096."
        )
    return None


async def _render_settings(target: CallbackQuery | Message, state: FSMContext) -> None:
    data = await state.get_data()
    await edit_text_safe(
        target,
        _settings_text(data),
        reply_markup=_seedream_settings_kb(data),
    )


async def _append_reference_files(
    state: FSMContext,
    new_file_ids: list[str],
) -> tuple[int, int]:
    data = await state.get_data()
    current = list(data.get("photos", []) or [])
    remaining = max(0, SEEDREAM_MAX_REFERENCE_IMAGES - len(current))
    accepted = list(new_file_ids[:remaining])
    updated = current + accepted
    await state.update_data(photos=updated)
    return len(updated), len(new_file_ids) - len(accepted)


@router.callback_query(F.data == MenuCallbacks.SEEDREAM_LITE)
async def start_seedream_lite(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await safe_answer(call)
    await upsert_user(session, call.from_user.id, call.from_user.username)
    if await block_launch_for_call(call, session, reply_markup=buy_generations_kb()):
        return

    user_settings = await get_user_photo_settings(session, call.from_user.id)
    await state.clear()
    await state.update_data(
        prompt="",
        photos=[],
        size_mode="auto",
        width=None,
        height=None,
        output_format=user_settings.output_format,
    )
    await state.set_state(SeedreamFlow.prompt)

    if call.message:
        await edit_text_safe(
            call,
            "🌱 <b>Seedream 5 Lite</b>\n\n"
            "Пришли текстовый промпт для генерации изображения ✍️\n\n"
            "После этого можно будет добавить до 10 референсов и настроить size / width / height / format.",
            reply_markup=None,
        )


@router.message(SeedreamFlow.prompt)
async def seedream_lite_prompt_in(
    message: Message, state: FSMContext
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

    await state.update_data(prompt=prompt)
    await state.set_state(SeedreamFlow.references)
    await message.answer(
        _refs_text(0),
        reply_markup=_seedream_refs_kb(0),
    )


@router.message(SeedreamFlow.references)
async def seedream_lite_references_in(
    message: Message, state: FSMContext
) -> None:
    if not message.photo:
        await message.answer(
            "Отправь фото-референсы или нажми «Продолжить без фото» 👇",
            reply_markup=_seedream_refs_kb(len((await state.get_data()).get("photos", []) or [])),
        )
        return

    if not message.media_group_id:
        ref_count, dropped = await _append_reference_files(
            state,
            [message.photo[-1].file_id],
        )
        note = (
            f"\nЛишние фото не добавлены: {dropped}."
            if dropped > 0
            else ""
        )
        await message.answer(
            f"Добавлено референсов: <b>{ref_count}/{SEEDREAM_MAX_REFERENCE_IMAGES}</b>{note}",
            reply_markup=_seedream_refs_kb(ref_count),
        )
        return

    await _album.push(
        message.chat.id,
        message.media_group_id,
        message.photo[-1].file_id,
    )
    result = await _album.collect(message.chat.id, message.media_group_id)
    if not result.file_ids:
        return

    ref_count, dropped = await _append_reference_files(state, result.file_ids)
    note = (
        f"\nЛишние фото не добавлены: {dropped}."
        if dropped > 0
        else ""
    )
    await message.answer(
        f"Добавлено референсов: <b>{ref_count}/{SEEDREAM_MAX_REFERENCE_IMAGES}</b>{note}",
        reply_markup=_seedream_refs_kb(ref_count),
    )


@router.callback_query(SeedreamFlow.references, F.data == SEEDREAM_REFS_CLEAR)
async def seedream_refs_clear(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(photos=[])
    await edit_text_safe(
        call,
        _refs_text(0),
        reply_markup=_seedream_refs_kb(0),
    )
    await safe_answer(call)


@router.callback_query(SeedreamFlow.references, F.data == SEEDREAM_REFS_CONTINUE)
async def seedream_refs_continue(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SeedreamFlow.settings)
    await _render_settings(call, state)
    await safe_answer(call)


@router.callback_query(SeedreamFlow.settings, F.data == SEEDREAM_SETTINGS_SIZE)
async def seedream_settings_size(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    next_size = _next_in_cycle(str(data.get("size_mode") or "auto"), SEEDREAM_SIZE_OPTIONS)
    await state.update_data(size_mode=next_size)
    await _render_settings(call, state)
    await safe_answer(call)


@router.callback_query(SeedreamFlow.settings, F.data == SEEDREAM_SETTINGS_FORMAT)
async def seedream_settings_format(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    next_format = _next_in_cycle(
        str(data.get("output_format") or "png"),
        SEEDREAM_FORMAT_OPTIONS,
    )
    await state.update_data(output_format=next_format)
    await _render_settings(call, state)
    await safe_answer(call)


@router.callback_query(SeedreamFlow.settings, F.data == SEEDREAM_SETTINGS_TO_REFS)
async def seedream_settings_to_refs(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    ref_count = len(list(data.get("photos", []) or []))
    await state.set_state(SeedreamFlow.references)
    await edit_text_safe(
        call,
        _refs_text(ref_count),
        reply_markup=_seedream_refs_kb(ref_count),
    )
    await safe_answer(call)


@router.callback_query(SeedreamFlow.settings, F.data == SEEDREAM_SETTINGS_WIDTH)
async def seedream_settings_width(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SeedreamFlow.width)
    if call.message:
        await call.message.answer(
            f"Введи <b>width</b> от {SEEDREAM_MIN_DIMENSION} до {SEEDREAM_MAX_DIMENSION}.\n"
            "Отправь <code>0</code> или слово <code>очистить</code>, чтобы убрать значение."
        )
    await safe_answer(call)


@router.callback_query(SeedreamFlow.settings, F.data == SEEDREAM_SETTINGS_HEIGHT)
async def seedream_settings_height(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SeedreamFlow.height)
    if call.message:
        await call.message.answer(
            f"Введи <b>height</b> от {SEEDREAM_MIN_DIMENSION} до {SEEDREAM_MAX_DIMENSION}.\n"
            "Отправь <code>0</code> или слово <code>очистить</code>, чтобы убрать значение."
        )
    await safe_answer(call)


async def _update_seedream_dimension(
    message: Message,
    state: FSMContext,
    *,
    field: str,
) -> None:
    raw = (message.text or "").strip().lower()
    if raw in {"0", "очистить", "clear", "-"}:
        await state.update_data(**{field: None})
    else:
        try:
            value = int(raw)
        except Exception:
            await message.answer("Нужно целое число. Попробуй ещё раз ✍️")
            return
        if value < SEEDREAM_MIN_DIMENSION or value > SEEDREAM_MAX_DIMENSION:
            await message.answer(
                f"Значение должно быть в диапазоне {SEEDREAM_MIN_DIMENSION}-{SEEDREAM_MAX_DIMENSION}."
            )
            return
        await state.update_data(**{field: value})

    await state.set_state(SeedreamFlow.settings)
    await message.answer(
        _settings_text(await state.get_data()),
        reply_markup=_seedream_settings_kb(await state.get_data()),
    )


@router.message(SeedreamFlow.width)
async def seedream_width_value(message: Message, state: FSMContext) -> None:
    await _update_seedream_dimension(message, state, field="width")


@router.message(SeedreamFlow.height)
async def seedream_height_value(message: Message, state: FSMContext) -> None:
    await _update_seedream_dimension(message, state, field="height")


@router.callback_query(SeedreamFlow.settings, F.data == SEEDREAM_SETTINGS_GENERATE)
async def seedream_generate(
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
            model_key=MODEL_PRICE_SEEDREAM_V5_LITE_KEY,
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
        results = await generate_seedream_v5_lite(
            bot=call.message.bot,
            session=session,
            tg_id=tg_id,
            prompt=str(data.get("prompt") or "").strip(),
            telegram_photo_file_ids=list(data.get("photos", []) or []),
            size=_build_seedream_size(data),
            output_format=str(data.get("output_format") or "png"),
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
            section="seedream_v5_lite",
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
                model_key=MODEL_PRICE_SEEDREAM_V5_LITE_KEY,
            )
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, wavespeed_error_to_user_text(e))
        await state.clear()
        return

    except Exception as e:
        logger.exception("SEEDREAM_LITE generation failed: %s", e)
        if not sent_any:
            await refund_photo_generation(
                session,
                tg_id,
                model_key=MODEL_PRICE_SEEDREAM_V5_LITE_KEY,
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


@router.callback_query(F.data == SEEDREAM_CANCEL)
async def seedream_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_text_safe(call, "Выбор моделей 👇", reply_markup=photo_models_kb())
    await safe_answer(call)
