from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def body_parts_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="Голова", callback_data="body:head")
    kb.button(text="Лицо", callback_data="body:face")
    kb.button(text="Шея", callback_data="body:neck")
    kb.button(text="Торс", callback_data="body:torso")
    kb.button(text="Талия", callback_data="body:waist")
    kb.button(text="Руки", callback_data="body:arms")
    kb.button(text="Запястье", callback_data="body:wrist")
    kb.button(text="Уши", callback_data="body:ears")
    kb.button(text="Ноги", callback_data="body:legs")
    kb.button(text="Стопы", callback_data="body:feet")

    kb.adjust(2, 2, 2, 2, 2)
    return kb.as_markup()
