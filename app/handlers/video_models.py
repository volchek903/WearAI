from __future__ import annotations

import asyncio
import html
import logging
from pathlib import Path
from urllib.parse import urlsplit

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.video_models import VideoModelConfig, get_video_model
from app.keyboards.extra import buy_generations_kb
from app.keyboards.video_models import (
    VideoCallbacks,
    options_kb,
    skip_kb,
    video_confirm_kb,
    video_media_continue_kb,
    video_model_details_kb,
    video_models_menu_kb,
)
from app.repository.app_settings import get_model_price_credits, get_scaled_model_price_credits
from app.repository.generations import (
    NoGenerationsLeft,
    charge_video_generation,
    ensure_default_subscription,
    refund_video_generation,
    finalize_video_generation,
)
from app.repository.users import (
    get_user_by_tg_id,
    increment_generated_videos,
    upsert_user,
)
from app.services.album_collector import AlbumCollector
from app.services.kie_ai import WaveSpeedClient
from app.services.wavespeed_ai import WaveSpeedError, get_wavespeed_api_key_from_env
from app.states.video_generation import VideoGenerationFlow
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.support_text import with_support
from app.utils.tg_callback import safe_answer
from app.utils.tg_edit import edit_text_safe
from app.utils.tg_files import tg_file_id_to_bytes
from app.utils.wavespeed_errors import wavespeed_error_to_user_text

router = Router()
logger = logging.getLogger(__name__)
_album = AlbumCollector(debounce_seconds=0.8)
MAX_INPUT_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_DOC_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}
CONTACT_TEXT = (
    "Если вам не понравился результат или что-то пошло не так, "
    "свяжитесь с администратором @wearaimanager"
)
SHOT_TYPE_LABELS = {
    "intelligent": "Авто",
    "customize": "Ручной",
}


def _document_looks_like_image(message: Message) -> bool:
    doc = message.document
    if doc is None:
        return False
    mime = (doc.mime_type or "").lower()
    if mime.startswith("image/"):
        return True
    ext = Path(doc.file_name or "").suffix.lower()
    return ext in IMAGE_DOC_EXTENSIONS


def _resolution_labels(model: VideoModelConfig) -> list[tuple[str, str]]:
    return [(item.value, item.value) for item in model.resolution_options]


def _aspect_ratio_labels(model: VideoModelConfig) -> list[tuple[str, str]]:
    return [(value.replace(":", "x"), value) for value in model.aspect_ratio_options]


def _cfg_scale_labels(model: VideoModelConfig) -> list[tuple[str, str]]:
    return [(value.replace(".", "_"), value) for value in model.cfg_scale_options]


def _bool_labels(*, yes_label: str, no_label: str) -> list[tuple[str, str]]:
    return [("yes", yes_label), ("no", no_label)]


def _selected_resolution(model: VideoModelConfig, data: dict) -> str:
    return str(data.get("resolution") or model.resolution_options[0].value)


def _selected_duration(model: VideoModelConfig, data: dict) -> int:
    raw = data.get("duration")
    if raw is None:
        return int(model.duration_options[0])
    return int(raw)


def _selected_sound_enabled(data: dict) -> bool:
    return bool(data.get("sound"))


async def _price_breakdown(
    session: AsyncSession,
    *,
    model: VideoModelConfig,
    data: dict,
) -> tuple[int, int]:
    duration = _selected_duration(model, data)
    resolution = _selected_resolution(model, data)
    provider_cost_per_second = model.provider_cost_per_second(
        resolution=resolution,
        sound_enabled=_selected_sound_enabled(data),
    )
    credits_per_second = await get_scaled_model_price_credits(
        session,
        model.pricing_model_key,
        provider_cost_per_second,
    )
    total_credits = max(1, int(credits_per_second) * int(duration))
    return int(credits_per_second), total_credits


async def _base_credits_per_second(session: AsyncSession, model: VideoModelConfig) -> int:
    return await get_model_price_credits(session, model.pricing_model_key)


def _model_intro_text(model: VideoModelConfig, *, credits_per_second: int) -> str:
    features = "\n".join(f"• {item}" for item in model.features)
    notes = "\n".join(f"• {item}" for item in model.input_notes)
    return (
        f"🎬 <b>{model.title}</b>\n\n"
        f"{model.blurb}\n\n"
        f"✨ <b>Что умеет</b>\n{features}\n\n"
        f"📥 <b>Входные параметры</b>\n{notes}\n\n"
        f"💳 <b>Цена</b>\n"
        f"Базовый тариф: <b>{credits_per_second} кр./сек</b>.\n"
        "Точная стоимость зависит от выбранных параметров модели."
    )


def _media_prompt_text(model: VideoModelConfig) -> str:
    if model.max_images == 1:
        limit_line = "Пришлите <b>одно фото</b>."
    elif model.end_image_field:
        limit_line = (
            f"Пришлите <b>{model.min_images}–{model.max_images} фото</b>.\n"
            "Первое фото станет стартовым кадром, второе можно добавить как финальный кадр "
            "следующим сообщением или альбомом."
        )
    else:
        limit_line = f"Пришлите от <b>{model.min_images}</b> до <b>{model.max_images}</b> фото."

    return (
        f"🖼 <b>{model.title}</b>\n\n"
        f"{limit_line}\n"
        "Можно отправить обычное фото или файл-изображение.\n"
        "Альбом поддерживается, если модель принимает больше одного фото."
    )


def _render_optional_text(value: str) -> str:
    text = (value or "").strip()
    return text if text else "—"


def _escaped_optional_text(value: str) -> str:
    return html.escape(_render_optional_text(value))


async def _render_confirm_text(
    session: AsyncSession,
    *,
    model: VideoModelConfig,
    data: dict,
) -> str:
    credits_per_second, total_credits = await _price_breakdown(
        session,
        model=model,
        data=data,
    )
    resolution = _selected_resolution(model, data)
    duration = _selected_duration(model, data)
    aspect_ratio = data.get("aspect_ratio") or "auto"
    images_count = len(data.get("image_file_ids") or [])
    prompt = _escaped_optional_text(str(data.get("prompt") or ""))
    negative_prompt = _escaped_optional_text(str(data.get("negative_prompt") or ""))
    seed_value = data.get("seed")
    seed = "—" if seed_value in (None, "", -1) else html.escape(str(seed_value))
    shot_type = SHOT_TYPE_LABELS.get(str(data.get("shot_type") or ""), "—")
    cfg_scale = _escaped_optional_text(str(data.get("cfg_scale") or ""))
    sound = "Вкл" if data.get("sound") else "Выкл"
    generate_audio = "Вкл" if data.get("generate_audio", True) else "Выкл"
    web_search = "Вкл" if data.get("enable_web_search") else "Выкл"

    lines = [
        f"🎬 <b>{model.title}</b>",
        "",
        f"🖼 Фото: <b>{images_count}</b>",
        f"✍️ Промпт: <b>{prompt}</b>",
        f"⏱ Длительность: <b>{duration} сек</b>",
    ]
    if model.supports_resolution:
        lines.append(f"🧾 Разрешение: <b>{resolution}</b>")
    if model.aspect_ratio_options:
        lines.append(f"📐 Соотношение: <b>{aspect_ratio}</b>")
    if model.supports_negative_prompt:
        lines.append(f"🚫 Негативный промпт: <b>{negative_prompt}</b>")
    if model.supports_sound:
        lines.append(f"🔊 Звук: <b>{sound}</b>")
    if model.supports_generate_audio:
        lines.append(f"🎧 Генерация аудио: <b>{generate_audio}</b>")
    if model.supports_web_search:
        lines.append(f"🌐 Web search: <b>{web_search}</b>")
    if model.supports_cfg_scale:
        lines.append(f"🎚 CFG scale: <b>{cfg_scale}</b>")
    if model.supports_shot_type:
        lines.append(f"🎞 Тип кадра: <b>{shot_type}</b>")
    if model.supports_seed:
        lines.append(f"🎲 Seed: <b>{seed}</b>")
    lines.extend(
        [
            "",
            f"💳 Цена: <b>{credits_per_second} кр./сек</b>",
            f"💸 К списанию: <b>{total_credits} кредитов</b>",
            "",
            "Все верно?",
        ]
    )
    return "\n".join(lines)


async def _get_model_from_state(state: FSMContext) -> VideoModelConfig | None:
    data = await state.get_data()
    return get_video_model(str(data.get("model_id") or ""))


async def _ask_prompt(target: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VideoGenerationFlow.prompt)
    text = (
        "✍️ Напиши промпт для генерации видео.\n\n"
        "Опиши движение, камеру, атмосферу, свет и настроение сцены."
    )
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text)
    else:
        await target.answer(text)


async def _ask_negative_prompt(target: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VideoGenerationFlow.negative_prompt)
    text = (
        "🚫 Напиши negative prompt.\n\n"
        "Например: blur, artifacts, extra limbs, distortions.\n"
        "Если не нужен — нажми «Пропустить»."
    )
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=skip_kb("negative_prompt"))
    else:
        await target.answer(text, reply_markup=skip_kb("negative_prompt"))


async def _ask_duration(target: Message | CallbackQuery, state: FSMContext, model: VideoModelConfig) -> None:
    await state.set_state(VideoGenerationFlow.duration)
    options = [(str(value), f"{value} сек") for value in model.duration_options]
    text = "⏱ Выбери длительность видео."
    markup = options_kb(field="duration", options=options)
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def _ask_resolution(target: Message | CallbackQuery, state: FSMContext, model: VideoModelConfig) -> None:
    await state.set_state(VideoGenerationFlow.resolution)
    text = "🧾 Выбери разрешение."
    markup = options_kb(field="resolution", options=_resolution_labels(model))
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def _ask_aspect_ratio(target: Message | CallbackQuery, state: FSMContext, model: VideoModelConfig) -> None:
    await state.set_state(VideoGenerationFlow.aspect_ratio)
    text = "📐 Выбери aspect ratio."
    markup = options_kb(field="aspect_ratio", options=_aspect_ratio_labels(model))
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def _ask_sound(target: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VideoGenerationFlow.sound)
    markup = options_kb(
        field="sound",
        options=_bool_labels(yes_label="🔊 Со звуком", no_label="🔇 Без звука"),
    )
    text = "🔊 Включить генерацию звука?"
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def _ask_generate_audio(target: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VideoGenerationFlow.generate_audio)
    markup = options_kb(
        field="generate_audio",
        options=_bool_labels(yes_label="🎧 Да", no_label="🚫 Нет"),
    )
    text = "🎧 Генерировать нативное аудио вместе с видео?"
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def _ask_web_search(target: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VideoGenerationFlow.web_search)
    markup = options_kb(
        field="enable_web_search",
        options=_bool_labels(yes_label="🌐 Да", no_label="🚫 Нет"),
    )
    text = "🌐 Включить web search?"
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def _ask_cfg_scale(target: Message | CallbackQuery, state: FSMContext, model: VideoModelConfig) -> None:
    await state.set_state(VideoGenerationFlow.cfg_scale)
    markup = options_kb(field="cfg_scale", options=_cfg_scale_labels(model))
    text = "🎚 Выбери CFG scale."
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def _ask_shot_type(target: Message | CallbackQuery, state: FSMContext, model: VideoModelConfig) -> None:
    await state.set_state(VideoGenerationFlow.shot_type)
    options = [(item, SHOT_TYPE_LABELS.get(item, item)) for item in model.shot_type_options]
    text = "🎞 Выбери shot type."
    markup = options_kb(field="shot_type", options=options)
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def _ask_seed(target: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VideoGenerationFlow.seed)
    text = (
        "🎲 Введи seed для повторяемости.\n\n"
        "Если seed не нужен, нажми «Пропустить»."
    )
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=skip_kb("seed"))
    else:
        await target.answer(text, reply_markup=skip_kb("seed"))


async def _go_to_confirm(
    target: Message | CallbackQuery,
    *,
    state: FSMContext,
    session: AsyncSession,
    model: VideoModelConfig,
) -> None:
    await state.set_state(VideoGenerationFlow.confirm)
    data = await state.get_data()
    text = await _render_confirm_text(session, model=model, data=data)
    markup = video_confirm_kb()
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")


async def _advance_flow(
    target: Message | CallbackQuery,
    *,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    model = await _get_model_from_state(state)
    if model is None:
        await state.clear()
        if isinstance(target, CallbackQuery):
            await edit_text_safe(
                target,
                "Не вижу выбранную модель 😕 Выбери её заново.",
                reply_markup=video_models_menu_kb(),
            )
        else:
            await target.answer("Не вижу выбранную модель 😕 Выбери её заново.", reply_markup=video_models_menu_kb())
        return

    data = await state.get_data()
    if not data.get("prompt"):
        await _ask_prompt(target, state)
        return
    if model.supports_negative_prompt and "negative_prompt" not in data:
        await _ask_negative_prompt(target, state)
        return
    if "duration" not in data:
        await _ask_duration(target, state, model)
        return
    if model.supports_resolution and "resolution" not in data:
        await _ask_resolution(target, state, model)
        return
    if model.aspect_ratio_options and "aspect_ratio" not in data:
        await _ask_aspect_ratio(target, state, model)
        return
    if model.supports_sound and "sound" not in data:
        await _ask_sound(target, state)
        return
    if model.supports_generate_audio and "generate_audio" not in data:
        await _ask_generate_audio(target, state)
        return
    if model.supports_web_search and "enable_web_search" not in data:
        await _ask_web_search(target, state)
        return
    if model.supports_cfg_scale and "cfg_scale" not in data:
        await _ask_cfg_scale(target, state, model)
        return
    if model.supports_shot_type and "shot_type" not in data:
        await _ask_shot_type(target, state, model)
        return
    if model.supports_seed and "seed" not in data:
        await _ask_seed(target, state)
        return
    await _go_to_confirm(target, state=state, session=session, model=model)


async def _resolve_upload_name(message: Message, file_id: str, default_name: str) -> str:
    try:
        tg_file = await message.bot.get_file(file_id)
    except Exception:
        return default_name
    ext = Path(tg_file.file_path or "").suffix
    if ext:
        return f"{Path(default_name).stem}{ext}"
    return default_name


def _infer_output_filename(url: str, fallback: str = "video_result.mp4") -> str:
    path = urlsplit(url).path
    name = Path(path).name
    return name or fallback


@router.callback_query(F.data.startswith(VideoCallbacks.OPEN_PREFIX))
async def open_video_model_details(
    call: CallbackQuery,
    session: AsyncSession,
) -> None:
    model_id = (call.data or "").replace(VideoCallbacks.OPEN_PREFIX, "", 1)
    model = get_video_model(model_id)
    if model is None:
        await safe_answer(call, "Модель не найдена 😕", show_alert=True)
        return
    credits_per_second = await _base_credits_per_second(session, model)
    await edit_text_safe(
        call,
        _model_intro_text(model, credits_per_second=credits_per_second),
        reply_markup=video_model_details_kb(model),
        parse_mode="HTML",
    )
    await safe_answer(call)


@router.callback_query(F.data.startswith(VideoCallbacks.START_PREFIX))
async def start_video_model_flow(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    model_id = (call.data or "").replace(VideoCallbacks.START_PREFIX, "", 1)
    model = get_video_model(model_id)
    if model is None:
        await safe_answer(call, "Модель не найдена 😕", show_alert=True)
        return
    await upsert_user(session, call.from_user.id, call.from_user.username)
    await state.clear()
    await state.update_data(model_id=model.model_id)
    await state.set_state(VideoGenerationFlow.media)
    await edit_text_safe(call, _media_prompt_text(model), parse_mode="HTML")
    await safe_answer(call)


@router.message(VideoGenerationFlow.media, F.photo)
@router.message(VideoGenerationFlow.media, F.document)
async def video_media_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    model = await _get_model_from_state(state)
    if model is None:
        await state.clear()
        await message.answer("Сессия потеряна 😕 Выбери модель заново.", reply_markup=video_models_menu_kb())
        return

    data = await state.get_data()
    existing_file_ids = list(data.get("image_file_ids") or [])
    file_ids: list[str] = []

    if message.photo:
        if message.media_group_id:
            await _album.push(message.chat.id, message.media_group_id, message.photo[-1].file_id)
            result = await _album.collect(message.chat.id, message.media_group_id)
            if not result.file_ids:
                return
            file_ids = list(result.file_ids)
        else:
            file_ids = [message.photo[-1].file_id]
            if int(message.photo[-1].file_size or 0) > MAX_INPUT_IMAGE_BYTES:
                await message.answer("Фото слишком большое 😕 Отправь изображение до 10 МБ.")
                return
    elif _document_looks_like_image(message):
        doc = message.document
        assert doc is not None
        if int(doc.file_size or 0) > MAX_INPUT_IMAGE_BYTES:
            await message.answer("Изображение слишком большое 😕 Отправь файл до 10 МБ.")
            return
        file_ids = [doc.file_id]
    else:
        await message.answer("Нужно изображение 📸 Отправь фото или файл-изображение.")
        return

    combined_file_ids = existing_file_ids + file_ids

    if len(combined_file_ids) > model.max_images:
        if model.max_images == 1:
            await message.answer("Эта модель принимает только одно фото 📸")
        else:
            await message.answer(
                f"Эта модель принимает до {model.max_images} фото 📸\n"
                "Если хочешь заменить кадры, нажми «Начать заново»."
            )
        return

    await state.update_data(
        image_file_ids=combined_file_ids,
        start_image_file_id=combined_file_ids[0],
        end_image_file_id=(
            combined_file_ids[1]
            if len(combined_file_ids) > 1 and model.end_image_field
            else None
        ),
    )

    if len(combined_file_ids) < model.min_images:
        await message.answer(
            f"Нужно минимум {model.min_images} фото 📸",
            reply_markup=video_media_continue_kb(),
        )
        return

    if model.max_images > 1 and len(combined_file_ids) == 1:
        await message.answer(
            "✅ Первое фото сохранено.\n\n"
            "Если хочешь, отправь ещё одно фото как финальный кадр.\n"
            "Если одного фото достаточно, нажми кнопку ниже.",
            reply_markup=video_media_continue_kb(),
        )
        return

    await _advance_flow(message, state=state, session=session)


@router.message(VideoGenerationFlow.media)
async def video_media_wrong(message: Message) -> None:
    await message.answer("Сейчас нужно изображение 📸 Отправь фото или файл-изображение.")


@router.callback_query(F.data == VideoCallbacks.MEDIA_CONTINUE)
async def video_media_continue(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    model = await _get_model_from_state(state)
    if model is None:
        await state.clear()
        await edit_text_safe(
            call,
            "Сессия потеряна 😕 Выбери модель заново.",
            reply_markup=video_models_menu_kb(),
        )
        await safe_answer(call)
        return

    data = await state.get_data()
    image_file_ids = list(data.get("image_file_ids") or [])
    if len(image_file_ids) < model.min_images:
        await safe_answer(call, "Сначала пришли фото 📸", show_alert=True)
        return

    await _advance_flow(call, state=state, session=session)
    await safe_answer(call)


@router.message(VideoGenerationFlow.prompt, F.text)
async def video_prompt_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    prompt = (message.text or "").strip()
    if not prompt:
        await message.answer("Промпт пустой ✍️ Напиши, что должно происходить в видео.")
        return
    await state.update_data(prompt=prompt)
    await _advance_flow(message, state=state, session=session)


@router.message(VideoGenerationFlow.prompt)
async def video_prompt_wrong(message: Message) -> None:
    await message.answer("Нужен текстовый промпт ✍️")


@router.message(VideoGenerationFlow.negative_prompt, F.text)
async def video_negative_prompt_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await state.update_data(negative_prompt=(message.text or "").strip())
    await _advance_flow(message, state=state, session=session)


@router.message(VideoGenerationFlow.negative_prompt)
async def video_negative_prompt_wrong(message: Message) -> None:
    await message.answer("Нужен текст или нажми «Пропустить».")


@router.message(VideoGenerationFlow.seed, F.text)
async def video_seed_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Введите число для seed или нажми «Пропустить».")
        return
    try:
        value = int(raw)
    except Exception:
        await message.answer("Seed должен быть целым числом.")
        return
    await state.update_data(seed=value)
    await _advance_flow(message, state=state, session=session)


@router.message(VideoGenerationFlow.seed)
async def video_seed_wrong(message: Message) -> None:
    await message.answer("Seed должен быть числом.")


@router.callback_query(F.data.startswith(VideoCallbacks.SKIP_PREFIX))
async def video_skip_field(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    field = (call.data or "").replace(VideoCallbacks.SKIP_PREFIX, "", 1)
    if field == "negative_prompt":
        await state.update_data(negative_prompt="")
    elif field == "seed":
        await state.update_data(seed=-1)
    else:
        await safe_answer(call)
        return
    await _advance_flow(call, state=state, session=session)
    await safe_answer(call)


@router.callback_query(F.data.startswith(VideoCallbacks.SET_PREFIX))
async def video_set_option(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    raw = (call.data or "").replace(VideoCallbacks.SET_PREFIX, "", 1)
    field, _, token = raw.partition(":")
    if not field or not token:
        await safe_answer(call)
        return

    if field == "duration":
        await state.update_data(duration=int(token))
    elif field == "resolution":
        await state.update_data(resolution=token)
    elif field == "aspect_ratio":
        await state.update_data(aspect_ratio=token.replace("x", ":"))
    elif field == "sound":
        await state.update_data(sound=(token == "yes"))
    elif field == "generate_audio":
        await state.update_data(generate_audio=(token == "yes"))
    elif field == "enable_web_search":
        await state.update_data(enable_web_search=(token == "yes"))
    elif field == "cfg_scale":
        await state.update_data(cfg_scale=float(token.replace("_", ".")))
    elif field == "shot_type":
        await state.update_data(shot_type=token)
    else:
        await safe_answer(call)
        return

    await _advance_flow(call, state=state, session=session)
    await safe_answer(call)


@router.callback_query(F.data == VideoCallbacks.RESTART)
async def video_restart(
    call: CallbackQuery,
    state: FSMContext,
) -> None:
    model = await _get_model_from_state(state)
    if model is None:
        await state.clear()
        await edit_text_safe(
            call,
            "Не вижу выбранную модель 😕",
            reply_markup=video_models_menu_kb(),
        )
        await safe_answer(call)
        return

    model_id = model.model_id
    await state.clear()
    await state.update_data(model_id=model_id)
    await state.set_state(VideoGenerationFlow.media)
    await edit_text_safe(call, _media_prompt_text(model), parse_mode="HTML")
    await safe_answer(call)


@router.callback_query(F.data == VideoCallbacks.CONFIRM)
async def video_confirm(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    model = await _get_model_from_state(state)
    if model is None:
        await state.clear()
        await safe_answer(call, "Сессия потеряна 😕", show_alert=True)
        return

    data = await state.get_data()
    start_image_id = data.get("start_image_file_id")
    if not start_image_id:
        await state.clear()
        await safe_answer(call, "Не вижу фото для генерации 😕", show_alert=True)
        return
    if call.message is None:
        await safe_answer(call)
        return

    await upsert_user(session, call.from_user.id, call.from_user.username)
    credits_per_second, total_credits = await _price_breakdown(
        session,
        model=model,
        data=data,
    )
    user = await get_user_by_tg_id(session, call.from_user.id)
    current_balance = int(getattr(user, "credit_balance", 0) or 0) + int(
        getattr(user, "free_credit_balance", 0) or 0
    )
    if current_balance < total_credits:
        await edit_text_safe(
            call,
            "⛔️ Недостаточно баланса.\n\n"
            f"Нужно: <b>{total_credits}</b> кредитов\n"
            f"Доступно: <b>{current_balance}</b> кредитов",
            reply_markup=buy_generations_kb(),
            parse_mode="HTML",
        )
        await state.clear()
        await safe_answer(call)
        return

    try:
        await ensure_default_subscription(session, call.from_user.id)
        await charge_video_generation(
            session,
            call.from_user.id,
            model_key=model.pricing_model_key,
            credits_override=total_credits,
        )
    except NoGenerationsLeft:
        await edit_text_safe(
            call,
            "⛔️ Недостаточно баланса.\n\nПополните его, чтобы запустить генерацию 💳",
            reply_markup=buy_generations_kb(),
        )
        await state.clear()
        await safe_answer(call)
        return

    progress_msg = await call.message.answer(progress_initial_text())
    stop = asyncio.Event()

    async def _update(text: str) -> None:
        try:
            await progress_msg.edit_text(text)
        except Exception:
            return

    progress_task = asyncio.create_task(progress_loop(_update, stop, interval_s=7.0))
    wavespeed = WaveSpeedClient(api_key=get_wavespeed_api_key_from_env())
    sent_any = False

    try:
        start_name = await _resolve_upload_name(call.message, start_image_id, f"{call.from_user.id}_start.jpg")
        start_bytes = await tg_file_id_to_bytes(call.bot, start_image_id, tg_id=call.from_user.id)
        start_url = await wavespeed.upload_image_bytes(
            data=start_bytes,
            filename=start_name,
            upload_path=f"wearai/video/{call.from_user.id}",
        )

        payload: dict[str, object] = {
            "prompt": str(data.get("prompt") or ""),
            "image": start_url,
            "duration": _selected_duration(model, data),
            "enable_safety_checker": True,
            "enable_sync_mode": False,
            "enable_base64_output": False,
        }

        end_image_id = data.get("end_image_file_id")
        if model.end_image_field and end_image_id:
            end_name = await _resolve_upload_name(call.message, end_image_id, f"{call.from_user.id}_end.jpg")
            end_bytes = await tg_file_id_to_bytes(call.bot, end_image_id, tg_id=call.from_user.id)
            end_url = await wavespeed.upload_image_bytes(
                data=end_bytes,
                filename=end_name,
                upload_path=f"wearai/video/{call.from_user.id}",
            )
            payload[model.end_image_field] = end_url

        if model.supports_resolution:
            payload["resolution"] = _selected_resolution(model, data)
        if model.aspect_ratio_options:
            payload["aspect_ratio"] = str(data.get("aspect_ratio") or model.aspect_ratio_options[0])
        if model.supports_negative_prompt:
            payload["negative_prompt"] = str(data.get("negative_prompt") or "")
        if model.supports_sound:
            payload["sound"] = bool(data.get("sound"))
        if model.supports_generate_audio:
            payload["generate_audio"] = bool(data.get("generate_audio", True))
        if model.supports_web_search:
            payload["enable_web_search"] = bool(data.get("enable_web_search"))
        if model.supports_cfg_scale:
            payload["cfg_scale"] = float(data.get("cfg_scale") or model.cfg_scale_options[0])
        if model.supports_shot_type:
            payload["shot_type"] = str(data.get("shot_type") or model.shot_type_options[0])
        if model.supports_seed:
            payload["seed"] = int(data.get("seed") if data.get("seed") is not None else -1)

        task_id = await wavespeed.create_video_prediction_task(
            endpoint=model.endpoint,
            body=payload,
        )
        result_urls = await wavespeed.wait_result_urls(task_id, max_wait_s=30 * 60)
        if not result_urls:
            raise WaveSpeedError("WaveSpeed returned empty result")

        video_url = result_urls[0]
        video_bytes = await wavespeed.download_bytes(video_url)
        filename = _infer_output_filename(video_url)

        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, "✅ Готово! Отправляю видео…")

        await call.message.answer_video(
            video=BufferedInputFile(video_bytes, filename=filename),
            caption="🎉 Видео готово!",
            supports_streaming=True,
        )
        sent_any = True
        await finalize_video_generation(session, call.from_user.id)
        await call.message.answer_document(
            document=BufferedInputFile(video_bytes, filename=filename),
            caption="Исходный файл результата",
        )
        await call.message.answer(CONTACT_TEXT)

        await increment_generated_videos(
            session=session,
            tg_id=call.from_user.id,
            delta=1,
            section=f"video_{model.model_id}",
        )
        await state.clear()
        await call.message.answer(
            "Хочешь сгенерировать ещё одно видео? 👇",
            reply_markup=video_models_menu_kb(),
        )
        return
    except WaveSpeedError as e:
        logger.warning("Video model generation failed: %s", e)
        if not sent_any:
            await refund_video_generation(
                session,
                call.from_user.id,
                model_key=model.pricing_model_key,
            )
        await stop_progress(stop, progress_task)
        await edit_text_safe(progress_msg, wavespeed_error_to_user_text(e), reply_markup=video_models_menu_kb())
        await state.clear()
        return
    except Exception as e:
        logger.exception("Video model generation crashed: model=%s", model.model_id)
        if not sent_any:
            await refund_video_generation(
                session,
                call.from_user.id,
                model_key=model.pricing_model_key,
            )
        await stop_progress(stop, progress_task)
        await edit_text_safe(
            progress_msg,
            with_support(
                "Не получилось сгенерировать видео 😕\n"
                "Попробуй ещё раз или выбери другую модель."
            ),
            reply_markup=video_models_menu_kb(),
        )
        await state.clear()
        return
