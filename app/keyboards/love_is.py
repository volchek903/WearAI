from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class LoveIsCallbacks:
    ANIMATE = "love_is:animate"


def love_is_post_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💞 Оживить любовь", callback_data=LoveIsCallbacks.ANIMATE)
    kb.adjust(1)
    return kb.as_markup()
