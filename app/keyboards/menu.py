from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class MenuCallbacks:
    MODEL = "menu:model"
    TRYON = "menu:tryon"
    HELP = "menu:help"


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Модель с товаром", callback_data=MenuCallbacks.MODEL)
    kb.button(text="Примерить одежду", callback_data=MenuCallbacks.TRYON)
    kb.button(text="🪄 Помочь с описанием", callback_data=MenuCallbacks.HELP)
    kb.adjust(1)
    return kb.as_markup()
