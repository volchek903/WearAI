# app/keyboards/extra.py
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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

    # NEW: ручная проверка оплаты (polling)
    CHECK_PREFIX = "extra:check:"  # + <payment_id>

    # навигация
    BACK = "extra:back"
    TO_MENU = "extra:to_menu"


def extra_menu_kb(current_plan_name: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    if current_plan_name != "Orbit":
        kb.button(text="✨ Хочу Orbit", callback_data=ExtraCallbacks.WANT_ORBIT)
    if current_plan_name != "Nova":
        kb.button(text="🚀 Хочу Nova", callback_data=ExtraCallbacks.WANT_NOVA)
    if current_plan_name != "Cosmic":
        kb.button(text="🌌 Хочу Cosmic", callback_data=ExtraCallbacks.WANT_COSMIC)

    kb.button(text="⬅️ Назад", callback_data=ExtraCallbacks.TO_MENU)

    kb.adjust(1)
    return kb.as_markup()


def extra_buy_kb(plan_name: str) -> InlineKeyboardMarkup:
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


# Старый вариант (просто URL оплаты)
def extra_pay_url_kb(redirect_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💳 Оплатить", url=redirect_url))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=ExtraCallbacks.BACK))
    kb.adjust(1)
    return kb.as_markup()


# NEW: вариант под polling (Оплатить + Проверить оплату)
def extra_pay_poll_kb(redirect_url: str, payment_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💳 Оплатить", url=redirect_url))
    kb.row(
        InlineKeyboardButton(
            text="🔄 Проверить оплату",
            callback_data=f"{ExtraCallbacks.CHECK_PREFIX}{payment_id}",
        )
    )
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=ExtraCallbacks.BACK))
    kb.adjust(1)
    return kb.as_markup()
