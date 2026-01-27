from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class HelpCallbacks:
    START = "help:start"  # help:start:<kind>
    USE = "help:use"
    BACK = "help:back"


def help_button_kb(kind: str, text: str = "🪄 Нужна помощь") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=text, callback_data=f"{HelpCallbacks.START}:{kind}")
    kb.adjust(1)
    return kb.as_markup()


def help_choose_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text="🛍 Описание модели", callback_data=f"{HelpCallbacks.START}:model_desc"
    )
    kb.button(
        text="✨ Подача товара",
        callback_data=f"{HelpCallbacks.START}:presentation_desc",
    )
    kb.adjust(1)
    return kb.as_markup()


def help_use_back_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Использовать текст", callback_data=HelpCallbacks.USE)
    kb.button(text="⬅️ Назад", callback_data=HelpCallbacks.BACK)
    kb.adjust(2)
    return kb.as_markup()
