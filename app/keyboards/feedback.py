from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.utils import add_button


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
    add_button(kb, text="🛠 Сообщить об ошибке", callback_data=FeedbackCallbacks.BUG)
    add_button(kb, text="✅ Всё отлично", callback_data=FeedbackCallbacks.OK)
    kb.adjust(1)
    return kb.as_markup()


def feedback_offer_video_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="🎬 Оживить фото", callback_data=FeedbackCallbacks.ANIMATE)
    add_button(
        kb,
        text="⬅️ Вернуться в меню",
        callback_data=FeedbackCallbacks.MENU,
        style="danger",
    )
    kb.adjust(1)
    return kb.as_markup()


def back_to_menu_kb(text: str = "⬅️ В меню") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text=text, callback_data=FeedbackCallbacks.MENU, style="danger")
    kb.adjust(1)
    return kb.as_markup()
