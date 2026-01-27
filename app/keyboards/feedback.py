from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class FeedbackCallbacks:
    BUG = "fb:bug"
    OK = "fb:ok"
    MENU = "fb:menu"
    ANIMATE = "fb:animate"

    # алиасы для старого кода
    GOOD = OK
    BAD = BUG


def feedback_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛠 Сообщить об ошибке", callback_data=FeedbackCallbacks.BUG)
    kb.button(text="✅ Всё отлично", callback_data=FeedbackCallbacks.OK)
    kb.adjust(1)
    return kb.as_markup()


def feedback_offer_video_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎬 Оживить фото", callback_data=FeedbackCallbacks.ANIMATE)
    kb.button(text="⬅️ Вернуться в меню", callback_data=FeedbackCallbacks.MENU)
    kb.adjust(1)
    return kb.as_markup()


def back_to_menu_kb(text: str = "⬅️ В меню") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=text, callback_data=FeedbackCallbacks.MENU)
    kb.adjust(1)
    return kb.as_markup()
