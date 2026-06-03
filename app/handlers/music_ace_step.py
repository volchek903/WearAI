from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.menu import MenuCallbacks, music_menu_kb
from app.keyboards.extra import buy_generations_kb
from app.keyboards.music import (
    MusicCallbacks,
    confirm_keyboard,
    custom_structure_keyboard,
    duration_keyboard,
    music_done_keyboard,
    section_input_keyboard,
    structure_keyboard,
    tags_keyboard,
)
from app.repository.app_settings import MODEL_PRICE_ACE_STEP_KEY, get_model_price_credits
from app.repository.generations import (
    NoGenerationsLeft,
    charge_video_generation,
    ensure_default_subscription,
    is_launch_subscription,
    refund_video_generation,
    finalize_video_generation,
)
from app.repository.users import increment_generated_music, upsert_user
from app.services.wavespeed import WaveSpeedAceStepClient
from app.services.wavespeed_ai import WaveSpeedError
from app.states.music_ace_step_flow import MusicAceStepFlow
from app.utils.formatters import (
    compile_song_lyrics,
    format_song_summary,
    materialize_song_sections,
    should_skip_lyrics,
)
from app.utils.launch_guard import block_launch_for_call
from app.utils.progress_bar import progress_initial_text, progress_loop, stop_progress
from app.utils.support_text import launch_limits_message, with_support
from app.utils.tg_callback import safe_answer
from app.utils.tg_edit import edit_text_safe
from app.utils.content_media import get_content_file

router = Router()
logger = logging.getLogger(__name__)

MAX_TAGS = 7
DURATION_OPTIONS = [30, 60, 120, 180, 240]
DEFAULT_SEED = -1

TAG_CATEGORIES: dict[str, list[dict[str, str]]] = {
    "Жанр": [
        {"value": "pop", "label": "Поп"},
        {"value": "rock", "label": "Рок"},
        {"value": "rap", "label": "Рэп"},
        {"value": "lo-fi", "label": "Лоу-фай"},
        {"value": "jazz", "label": "Джаз"},
        {"value": "edm", "label": "EDM"},
        {"value": "synthwave", "label": "Синтвейв"},
        {"value": "acoustic", "label": "Акустика"},
    ],
    "Настроение": [
        {"value": "upbeat", "label": "Бодрое"},
        {"value": "sad", "label": "Грустное"},
        {"value": "chill", "label": "Расслабленное"},
        {"value": "romantic", "label": "Романтичное"},
        {"value": "dark", "label": "Мрачное"},
        {"value": "epic", "label": "Эпичное"},
        {"value": "dreamy", "label": "Мечтательное"},
    ],
    "Вокал": [
        {"value": "female vocals", "label": "Женский вокал"},
        {"value": "male vocals", "label": "Мужской вокал"},
        {"value": "duet", "label": "Дуэт"},
        {"value": "choir", "label": "Хор"},
        {"value": "instrumental", "label": "Без слов"},
    ],
    "Инструменты": [
        {"value": "piano", "label": "Пианино"},
        {"value": "guitar", "label": "Гитара"},
        {"value": "synth", "label": "Синтезатор"},
        {"value": "strings", "label": "Струнные"},
        {"value": "drums", "label": "Барабаны"},
        {"value": "bass", "label": "Бас"},
    ],
    "Темп": [
        {"value": "slow", "label": "Медленно"},
        {"value": "mid-tempo", "label": "Средний темп"},
        {"value": "fast", "label": "Быстро"},
        {"value": "90bpm", "label": "90 BPM"},
        {"value": "120bpm", "label": "120 BPM"},
        {"value": "140bpm", "label": "140 BPM"},
    ],
}

PRESET_STRUCTURES = [
    {"id": "v_c", "label": "Куплет → Припев", "sections": ["verse", "chorus"]},
    {
        "id": "v_c_v_c",
        "label": "Куплет → Припев → Куплет → Припев",
        "sections": ["verse", "chorus", "verse", "chorus"],
    },
    {
        "id": "v_c_b_c",
        "label": "Куплет → Припев → Бридж → Припев",
        "sections": ["verse", "chorus", "bridge", "chorus"],
    },
    {
        "id": "v_c_v_c_b_c",
        "label": "Куплет → Припев → Куплет → Припев → Бридж → Припев",
        "sections": ["verse", "chorus", "verse", "chorus", "bridge", "chorus"],
    },
]

SECTION_LABELS = {
    "verse": "Куплет",
    "chorus": "Припев",
    "bridge": "Бридж",
    "intro": "Интро",
    "outro": "Аутро",
}


def _all_tag_options() -> dict[str, dict[str, str]]:
    return {
        option["value"]: option
        for options in TAG_CATEGORIES.values()
        for option in options
    }


def _selected_tag_labels(selected_values: Sequence[str]) -> list[str]:
    all_options = _all_tag_options()
    return [all_options[v]["label"] for v in selected_values if v in all_options]


def _structure_line(sections: Sequence[dict[str, str]]) -> str:
    return " → ".join(section["label"] for section in sections) if sections else "—"


def _api_marker(section_type: str) -> str:
    mapping = {
        "verse": "Verse",
        "chorus": "Chorus",
        "bridge": "Bridge",
        "intro": "Intro",
        "outro": "Outro",
    }
    return mapping.get(section_type, section_type.title())


async def _render_tags_screen(
    target: CallbackQuery | Message,
    state: FSMContext,
    *,
    credits_per_second: int,
) -> None:
    text = await _build_tags_screen_text(state, credits_per_second=credits_per_second)
    data = await state.get_data()
    selected = set(data.get("selected_tags", []))
    markup = tags_keyboard(categories=TAG_CATEGORIES, selected_values=selected)
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")


async def _build_tags_screen_text(
    state: FSMContext,
    *,
    credits_per_second: int,
) -> str:
    data = await state.get_data()
    selected_line = ", ".join(_selected_tag_labels(data.get("selected_tags", []))) or "ничего"
    return (
        "🎵 Создадим песню. Сначала выбери стиль и теги.\n\n"
        f"🏷 Можно выбрать до {MAX_TAGS} тегов.\n"
        f"Сейчас выбрано: {selected_line}\n\n"
        f"💳 Стоимость: <b>{credits_per_second} кр.</b> за 1 секунду музыки.\n"
        "⏱ Минимальная длительность трека — <b>30 секунд</b>."
    )


async def _render_structure_screen(target: CallbackQuery | Message, state: FSMContext) -> None:
    data = await state.get_data()
    selected_line = ", ".join(_selected_tag_labels(data.get("selected_tags", []))) or "—"
    text = (
        "🧱 Теперь выбери структуру песни.\n\n"
        f"🏷 Теги: {selected_line}"
    )
    markup = structure_keyboard(presets=PRESET_STRUCTURES)
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def _render_custom_structure_screen(
    target: CallbackQuery | Message, state: FSMContext, notice: str | None = None
) -> None:
    data = await state.get_data()
    custom_sections = data.get("custom_sections", [])
    structure_preview = " → ".join(SECTION_LABELS.get(s, s.title()) for s in custom_sections) or "пока пусто"
    text = "🧩 Собери свою структуру песни.\n\n"
    if notice:
        text += f"{notice}\n\n"
    text += (
        f"Текущая структура:\n{structure_preview}\n\n"
        "Добавляй секции по порядку. Минимум 2 секции."
    )
    markup = custom_structure_keyboard()
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def _render_section_prompt(
    target: CallbackQuery | Message,
    state: FSMContext,
    *,
    index: int,
) -> None:
    data = await state.get_data()
    sections = data.get("sections", [])
    section = sections[index]
    section_texts = data.get("section_texts", {})
    existing = (section_texts.get(section["key"]) or "").strip()
    hint = f"\n\nТекущий текст:\n{existing}" if existing else ""
    text = (
        f"✍️ Шаг {index + 1} из {len(sections)}.\n"
        f"Введите текст для {section['label']}.\n"
        "Отправь текст одним сообщением."
        f"{hint}"
    )
    markup = section_input_keyboard()
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def _render_duration_screen(target: CallbackQuery | Message, state: FSMContext) -> None:
    data = await state.get_data()
    selected_duration = data.get("duration")
    text = (
        "⏱ Выбери длительность трека.\n\n"
        f"🎲 Seed будет использован по умолчанию: {data.get('seed', DEFAULT_SEED)}"
    )
    markup = duration_keyboard(
        durations=DURATION_OPTIONS,
        selected_duration=selected_duration,
    )
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


async def _render_confirm_screen(target: CallbackQuery | Message, state: FSMContext) -> None:
    data = await state.get_data()
    lyrics = compile_song_lyrics(
        sections=data.get("sections", []),
        section_texts=data.get("section_texts", {}),
        instrumental=bool(data.get("instrumental")),
    )
    await state.update_data(lyrics=lyrics)
    summary = format_song_summary(
        tags_display=_selected_tag_labels(data.get("selected_tags", [])),
        sections=data.get("sections", []),
        lyrics=lyrics,
        duration=int(data.get("duration") or 0),
        seed=int(data.get("seed", DEFAULT_SEED)),
        instrumental=bool(data.get("instrumental")),
    )
    markup = confirm_keyboard()
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, summary, reply_markup=markup)
    else:
        await target.answer(summary, reply_markup=markup)


def _back_to_music_menu_text() -> str:
    return (
        "🎵 Модели для музыки\n\n"
        "Выберите, какие модели вы хотите использовать и для каких целей 👇"
    )


async def _send_intro_audio(message: Message) -> None:
    await message.answer_voice(
        get_content_file("ace_music.mp3"),
        caption="",
    )


async def _start_song_flow(
    target: CallbackQuery | Message,
    state: FSMContext,
    *,
    credits_per_second: int,
) -> None:
    await state.clear()
    await state.update_data(
        selected_tags=[],
        custom_sections=[],
        sections=[],
        section_texts={},
        duration=None,
        seed=DEFAULT_SEED,
        instrumental=False,
        credits_per_second=credits_per_second,
    )
    await state.set_state(MusicAceStepFlow.tags)
    await _render_tags_screen(target, state, credits_per_second=credits_per_second)


def _preset_by_id(preset_id: str) -> dict[str, str] | None:
    for preset in PRESET_STRUCTURES:
        if preset["id"] == preset_id:
            return preset
    return None


@router.message(Command("create_song"))
async def create_song_command(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    await upsert_user(session, message.from_user.id, message.from_user.username)
    credits_per_second = await get_model_price_credits(session, MODEL_PRICE_ACE_STEP_KEY)
    await _start_song_flow(message, state, credits_per_second=credits_per_second)


@router.callback_query(F.data == MenuCallbacks.MUSIC_ACE_STEP)
async def create_song_from_menu(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await safe_answer(call)
    await upsert_user(session, call.from_user.id, call.from_user.username)
    if await block_launch_for_call(call, session):
        return
    credits_per_second = await get_model_price_credits(session, MODEL_PRICE_ACE_STEP_KEY)
    await state.clear()
    await state.update_data(
        selected_tags=[],
        custom_sections=[],
        sections=[],
        section_texts={},
        duration=None,
        seed=DEFAULT_SEED,
        instrumental=False,
        credits_per_second=credits_per_second,
    )
    await state.set_state(MusicAceStepFlow.tags)
    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass
        text = await _build_tags_screen_text(state, credits_per_second=credits_per_second)
        data = await state.get_data()
        selected = set(data.get("selected_tags", []))
        await call.message.answer_voice(
            get_content_file("ace_music.mp3"),
            caption=text,
            parse_mode="HTML",
            reply_markup=tags_keyboard(categories=TAG_CATEGORIES, selected_values=selected),
        )


@router.callback_query(F.data == "music:noop")
async def music_noop(call: CallbackQuery) -> None:
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.tags, F.data.startswith(f"{MusicCallbacks.TAG_TOGGLE}:"))
async def music_toggle_tag(call: CallbackQuery, state: FSMContext) -> None:
    value = call.data.split(":", 3)[-1]
    data = await state.get_data()
    selected = list(data.get("selected_tags", []))

    if value in selected:
        selected.remove(value)
    else:
        if len(selected) >= MAX_TAGS:
            await safe_answer(call, f"Можно выбрать максимум {MAX_TAGS} тегов", show_alert=True)
            return
        selected.append(value)

    await state.update_data(
        selected_tags=selected,
        instrumental=should_skip_lyrics(selected),
    )
    updated_data = await state.get_data()
    await _render_tags_screen(
        call,
        state,
        credits_per_second=int(updated_data.get("credits_per_second") or 1),
    )
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.tags, F.data == MusicCallbacks.TAG_RESET)
async def music_reset_tags(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(selected_tags=[], instrumental=False)
    data = await state.get_data()
    await _render_tags_screen(
        call,
        state,
        credits_per_second=int(data.get("credits_per_second") or 1),
    )
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.tags, F.data == MusicCallbacks.TAG_NEXT)
async def music_tags_next(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected = data.get("selected_tags", [])
    if not selected:
        await safe_answer(call, "Сначала выбери хотя бы один тег", show_alert=True)
        return
    await state.set_state(MusicAceStepFlow.structure)
    await _render_structure_screen(call, state)
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.tags, F.data == MusicCallbacks.BACK)
async def music_tags_back(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_text_safe(call, _back_to_music_menu_text(), reply_markup=music_menu_kb())
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.structure, F.data.startswith(f"{MusicCallbacks.STRUCT_PRESET}:"))
async def music_select_structure_preset(call: CallbackQuery, state: FSMContext) -> None:
    preset_id = call.data.split(":", 4)[-1]
    preset = _preset_by_id(preset_id)
    if preset is None:
        await safe_answer(call, "Не удалось определить структуру", show_alert=True)
        return

    sections = materialize_song_sections(preset["sections"])
    for section in sections:
        section["api_marker"] = _api_marker(section["type"])
    await state.update_data(
        structure_mode="preset",
        structure_preset_id=preset_id,
        custom_sections=[],
        sections=sections,
        section_texts={},
        current_section_index=0,
    )
    if should_skip_lyrics((await state.get_data()).get("selected_tags", [])):
        await state.set_state(MusicAceStepFlow.duration)
        await _render_duration_screen(call, state)
    else:
        await state.set_state(MusicAceStepFlow.section_text)
        await _render_section_prompt(call, state, index=0)
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.structure, F.data == MusicCallbacks.STRUCT_CUSTOM)
async def music_select_custom_structure(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(structure_mode="custom", custom_sections=[])
    await state.set_state(MusicAceStepFlow.custom_structure)
    await _render_custom_structure_screen(call, state)
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.structure, F.data == MusicCallbacks.BACK)
async def music_structure_back(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MusicAceStepFlow.tags)
    data = await state.get_data()
    await _render_tags_screen(
        call,
        state,
        credits_per_second=int(data.get("credits_per_second") or 1),
    )
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.custom_structure, F.data.startswith(f"{MusicCallbacks.CUSTOM_ADD}:"))
async def music_custom_add(call: CallbackQuery, state: FSMContext) -> None:
    section_type = call.data.split(":", 4)[-1]
    data = await state.get_data()
    custom_sections = list(data.get("custom_sections", []))
    custom_sections.append(section_type)
    await state.update_data(custom_sections=custom_sections)
    await _render_custom_structure_screen(call, state)
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.custom_structure, F.data == MusicCallbacks.CUSTOM_CLEAR)
async def music_custom_clear(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(custom_sections=[])
    await _render_custom_structure_screen(call, state)
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.custom_structure, F.data == MusicCallbacks.CUSTOM_DONE)
async def music_custom_done(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    custom_sections = list(data.get("custom_sections", []))
    if len(custom_sections) < 2:
        await _render_custom_structure_screen(
            call,
            state,
            notice="Нужно минимум 2 секции для своей структуры.",
        )
        await safe_answer(call)
        return

    sections = materialize_song_sections(custom_sections)
    for section in sections:
        section["api_marker"] = _api_marker(section["type"])
    await state.update_data(
        sections=sections,
        section_texts={},
        current_section_index=0,
    )
    if should_skip_lyrics(data.get("selected_tags", [])):
        await state.set_state(MusicAceStepFlow.duration)
        await _render_duration_screen(call, state)
    else:
        await state.set_state(MusicAceStepFlow.section_text)
        await _render_section_prompt(call, state, index=0)
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.custom_structure, F.data == MusicCallbacks.BACK)
async def music_custom_back(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MusicAceStepFlow.structure)
    await _render_structure_screen(call, state)
    await safe_answer(call)


@router.message(MusicAceStepFlow.section_text)
async def music_section_text_in(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Нужен текст секции. Отправь его одним сообщением.")
        return

    data = await state.get_data()
    index = int(data.get("current_section_index", 0))
    sections = data.get("sections", [])
    section = sections[index]
    section_texts = dict(data.get("section_texts", {}))
    section_texts[section["key"]] = message.text.strip()
    await state.update_data(section_texts=section_texts)

    next_index = index + 1
    if next_index >= len(sections):
        await state.set_state(MusicAceStepFlow.duration)
        await _render_duration_screen(message, state)
        return

    await state.update_data(current_section_index=next_index)
    await _render_section_prompt(message, state, index=next_index)


@router.callback_query(MusicAceStepFlow.section_text, F.data == MusicCallbacks.SECTION_BACK)
async def music_section_back(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    index = int(data.get("current_section_index", 0))
    if index <= 0:
        structure_mode = data.get("structure_mode")
        if structure_mode == "custom":
            await state.set_state(MusicAceStepFlow.custom_structure)
            await _render_custom_structure_screen(call, state)
        else:
            await state.set_state(MusicAceStepFlow.structure)
            await _render_structure_screen(call, state)
        await safe_answer(call)
        return

    prev_index = index - 1
    await state.update_data(current_section_index=prev_index)
    await _render_section_prompt(call, state, index=prev_index)
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.duration, F.data.startswith(f"{MusicCallbacks.DURATION_SET}:"))
async def music_duration_set(call: CallbackQuery, state: FSMContext) -> None:
    duration = int(call.data.split(":")[-1])
    await state.update_data(duration=duration)
    await _render_duration_screen(call, state)
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.duration, F.data == MusicCallbacks.DURATION_NEXT)
async def music_duration_next(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("duration"):
        await safe_answer(call, "Сначала выбери длительность", show_alert=True)
        return
    await state.set_state(MusicAceStepFlow.confirm)
    await _render_confirm_screen(call, state)
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.duration, F.data == MusicCallbacks.BACK)
async def music_duration_back(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if bool(data.get("instrumental")):
        if data.get("structure_mode") == "custom":
            await state.set_state(MusicAceStepFlow.custom_structure)
            await _render_custom_structure_screen(call, state)
        else:
            await state.set_state(MusicAceStepFlow.structure)
            await _render_structure_screen(call, state)
    else:
        sections = data.get("sections", [])
        prev_index = max(0, len(sections) - 1)
        await state.update_data(current_section_index=prev_index)
        await state.set_state(MusicAceStepFlow.section_text)
        await _render_section_prompt(call, state, index=prev_index)
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.confirm, F.data == MusicCallbacks.BACK)
async def music_confirm_back(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MusicAceStepFlow.duration)
    await _render_duration_screen(call, state)
    await safe_answer(call)


@router.callback_query(F.data == MusicCallbacks.CANCEL)
async def music_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_text_safe(call, "Создание песни отменено 🛑", reply_markup=music_menu_kb())
    await safe_answer(call)


@router.callback_query(MusicAceStepFlow.confirm, F.data == MusicCallbacks.CONFIRM)
async def music_confirm_submit(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await safe_answer(call)
    await upsert_user(session, call.from_user.id, call.from_user.username)
    data = await state.get_data()
    tags_values = list(data.get("selected_tags", []))
    sections = data.get("sections", [])
    lyrics = compile_song_lyrics(
        sections=sections,
        section_texts=data.get("section_texts", {}),
        instrumental=bool(data.get("instrumental")),
    )
    duration = int(data.get("duration") or 0)
    seed = int(data.get("seed", DEFAULT_SEED))
    tags = ", ".join(_selected_tag_labels(tags_values))
    credits_per_second = await get_model_price_credits(session, MODEL_PRICE_ACE_STEP_KEY)
    total_credits = max(1, credits_per_second * duration)

    progress_msg = await call.message.answer(progress_initial_text())
    stop = asyncio.Event()
    progress_task = asyncio.create_task(
        progress_loop(lambda t: progress_msg.edit_text(t), stop, interval_s=6.0)
    )

    try:
        await ensure_default_subscription(session, call.from_user.id)
        await charge_video_generation(
            session,
            call.from_user.id,
            model_key=MODEL_PRICE_ACE_STEP_KEY,
            credits_override=total_credits,
        )
    except NoGenerationsLeft:
        await stop_progress(stop, progress_task)
        if await is_launch_subscription(session, call.from_user.id):
            await progress_msg.edit_text(
                launch_limits_message(),
                reply_markup=buy_generations_kb(),
            )
        else:
            await progress_msg.edit_text(
                "⛔️ Недостаточно кредитов.\n\nПополните баланс 💳",
                reply_markup=buy_generations_kb(),
            )
        return

    delivered = False
    try:
        client = WaveSpeedAceStepClient()
        task_id = await client.create_ace_step_task(
            tags=tags,
            lyrics=lyrics,
            duration=duration,
            seed=seed,
        )
        await progress_msg.edit_text("⏳ Генерация запущена. Жду результат…")
        audio_url = await client.wait_audio_url(task_id)
        filename, audio_bytes = await client.download_audio_bytes(audio_url)

        await stop_progress(stop, progress_task)
        await progress_msg.edit_text("✅ Готово! Отправляю аудио…")
        await call.message.answer_audio(
            BufferedInputFile(audio_bytes, filename=filename),
            caption=(
                "🎵 Трек готов\n\n"
                f"Tags: {tags}\n"
                f"Длительность: {duration} сек\n"
                f"Структура: {_structure_line(sections)}"
            ),
        )
        delivered = True
        await finalize_video_generation(
            session,
            call.from_user.id,
        )
        await increment_generated_music(
            session=session,
            tg_id=call.from_user.id,
            delta=1,
            section="music_ace_step",
        )
        await state.clear()
        await call.message.answer(
            "Можно создать ещё один трек или вернуться в раздел музыки 🎵",
            reply_markup=music_done_keyboard(),
        )
        await safe_answer(call)
        return

    except WaveSpeedError as e:
        logger.warning("music ace-step failed: %s", e)
        if not delivered:
            await refund_video_generation(session, call.from_user.id, model_key=MODEL_PRICE_ACE_STEP_KEY)
        await stop_progress(stop, progress_task)
        await progress_msg.edit_text(with_support(f"Не удалось сгенерировать трек 😕\n{e}"))
    except Exception as e:
        logger.exception("music ace-step failed: %s", e)
        if not delivered:
            await refund_video_generation(session, call.from_user.id, model_key=MODEL_PRICE_ACE_STEP_KEY)
        await stop_progress(stop, progress_task)
        await progress_msg.edit_text(
            with_support("Не получилось сгенерировать музыку 😕 Попробуй ещё раз позже.")
        )
