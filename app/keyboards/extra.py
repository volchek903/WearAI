from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class ExtraCallbacks:
    # выбор пакета
    WANT_ORBIT = "extra:want:orbit"
    WANT_NOVA = "extra:want:nova"
    WANT_COSMIC = "extra:want:cosmic"

    # покупка
    BUY_ORBIT = "extra:buy:orbit"
    BUY_NOVA = "extra:buy:nova"
    BUY_COSMIC = "extra:buy:cosmic"

    # навигация
    BACK = "extra:back"


def extra_menu_kb(current_plan_name: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    if current_plan_name != "Orbit":
        kb.button(text="Хочу Orbit", callback_data=ExtraCallbacks.WANT_ORBIT)
    if current_plan_name != "Nova":
        kb.button(text="Хочу Nova", callback_data=ExtraCallbacks.WANT_NOVA)
    if current_plan_name != "Cosmic":
        kb.button(text="Хочу Cosmic", callback_data=ExtraCallbacks.WANT_COSMIC)

    kb.adjust(1)
    return kb.as_markup()


def extra_buy_kb(plan_name: str) -> InlineKeyboardMarkup:
    """
    Кнопка Купить + Назад.
    """
    kb = InlineKeyboardBuilder()

    if plan_name == "Orbit":
        kb.button(text="💳 Купить", callback_data=ExtraCallbacks.BUY_ORBIT)
    elif plan_name == "Nova":
        kb.button(text="💳 Купить", callback_data=ExtraCallbacks.BUY_NOVA)
    elif plan_name == "Cosmic":
        kb.button(text="💳 Купить", callback_data=ExtraCallbacks.BUY_COSMIC)

    kb.button(text="⬅️ Назад", callback_data=ExtraCallbacks.BACK)

    kb.adjust(1)
    return kb.as_markup()
