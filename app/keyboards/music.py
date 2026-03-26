from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.menu import MenuCallbacks
from app.keyboards.utils import add_button


class MusicCallbacks:
    PREFIX = "music"

    TAG_TOGGLE = f"{PREFIX}:tag"
    TAG_NEXT = f"{PREFIX}:tags:next"
    TAG_RESET = f"{PREFIX}:tags:reset"

    STRUCT_PRESET = f"{PREFIX}:struct:preset"
    STRUCT_CUSTOM = f"{PREFIX}:struct:custom"

    CUSTOM_ADD = f"{PREFIX}:custom:add"
    CUSTOM_DONE = f"{PREFIX}:custom:done"
    CUSTOM_CLEAR = f"{PREFIX}:custom:clear"

    SECTION_BACK = f"{PREFIX}:section:back"

    DURATION_SET = f"{PREFIX}:duration:set"
    DURATION_NEXT = f"{PREFIX}:duration:next"

    CONFIRM = f"{PREFIX}:confirm"
    BACK = f"{PREFIX}:back"
    CANCEL = f"{PREFIX}:cancel"


def tags_keyboard(
    *,
    categories: dict[str, Sequence[dict[str, str]]],
    selected_values: set[str],
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    sizes: list[int] = []

    for category_label, options in categories.items():
        add_button(kb, text=f"— {category_label} —", callback_data="music:noop")
        sizes.append(1)
        for option in options:
            selected = option["value"] in selected_values
            prefix = "✅ " if selected else ""
            add_button(
                kb,
                text=f"{prefix}{option['label']}",
                callback_data=f"{MusicCallbacks.TAG_TOGGLE}:{option['value']}",
            )
        sizes.extend([2] * (len(options) // 2))
        if len(options) % 2:
            sizes.append(1)

    add_button(kb, text="➡️ Далее", callback_data=MusicCallbacks.TAG_NEXT)
    add_button(kb, text="🔄 Сбросить выбор", callback_data=MusicCallbacks.TAG_RESET)
    add_button(kb, text="⬅️ Назад", callback_data=MusicCallbacks.BACK)
    add_button(kb, text="❌ Отмена", callback_data=MusicCallbacks.CANCEL)
    sizes.extend([1, 1, 2])
    kb.adjust(*sizes)
    return kb.as_markup()


def structure_keyboard(
    *,
    presets: Sequence[dict[str, str]],
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for preset in presets:
        add_button(
            kb,
            text=preset["label"],
            callback_data=f"{MusicCallbacks.STRUCT_PRESET}:{preset['id']}",
        )
    add_button(kb, text="🧩 Своя структура", callback_data=MusicCallbacks.STRUCT_CUSTOM)
    add_button(kb, text="⬅️ Назад", callback_data=MusicCallbacks.BACK)
    add_button(kb, text="❌ Отмена", callback_data=MusicCallbacks.CANCEL)
    kb.adjust(1)
    return kb.as_markup()


def custom_structure_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="➕ Verse", callback_data=f"{MusicCallbacks.CUSTOM_ADD}:verse")
    add_button(kb, text="➕ Chorus", callback_data=f"{MusicCallbacks.CUSTOM_ADD}:chorus")
    add_button(kb, text="➕ Bridge", callback_data=f"{MusicCallbacks.CUSTOM_ADD}:bridge")
    add_button(kb, text="➕ Intro", callback_data=f"{MusicCallbacks.CUSTOM_ADD}:intro")
    add_button(kb, text="➕ Outro", callback_data=f"{MusicCallbacks.CUSTOM_ADD}:outro")
    add_button(kb, text="✅ Готово", callback_data=MusicCallbacks.CUSTOM_DONE)
    add_button(kb, text="🗑 Очистить", callback_data=MusicCallbacks.CUSTOM_CLEAR)
    add_button(kb, text="⬅️ Назад", callback_data=MusicCallbacks.BACK)
    add_button(kb, text="❌ Отмена", callback_data=MusicCallbacks.CANCEL)
    kb.adjust(2, 2, 1, 2, 2)
    return kb.as_markup()


def section_input_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="⬅️ Назад", callback_data=MusicCallbacks.SECTION_BACK)
    add_button(kb, text="❌ Отмена", callback_data=MusicCallbacks.CANCEL)
    kb.adjust(2)
    return kb.as_markup()


def duration_keyboard(
    *,
    durations: Sequence[int],
    selected_duration: int | None,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for duration in durations:
        selected = duration == selected_duration
        prefix = "✅ " if selected else ""
        add_button(
            kb,
            text=f"{prefix}{duration} сек",
            callback_data=f"{MusicCallbacks.DURATION_SET}:{duration}",
        )
    add_button(kb, text="➡️ Далее", callback_data=MusicCallbacks.DURATION_NEXT)
    add_button(kb, text="⬅️ Назад", callback_data=MusicCallbacks.BACK)
    add_button(kb, text="❌ Отмена", callback_data=MusicCallbacks.CANCEL)
    kb.adjust(2, 2, 1, 2)
    return kb.as_markup()


def confirm_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="✅ Подтвердить", callback_data=MusicCallbacks.CONFIRM)
    add_button(kb, text="⬅️ Назад", callback_data=MusicCallbacks.BACK)
    add_button(kb, text="❌ Отменить", callback_data=MusicCallbacks.CANCEL)
    kb.adjust(1)
    return kb.as_markup()


def music_done_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="🎼 Создать ещё музыку", callback_data=MenuCallbacks.MUSIC_ACE_STEP)
    add_button(kb, text="⬅️ В раздел музыки", callback_data=MenuCallbacks.MUSIC)
    kb.adjust(1)
    return kb.as_markup()
