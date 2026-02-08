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
    BUY_ORBIT = "extra:buy:orbit:sbp"
    BUY_NOVA = "extra:buy:nova:sbp"
    BUY_COSMIC = "extra:buy:cosmic:sbp"
    BUY_ORBIT_CRYPTO = "extra:buy:orbit:crypto"
    BUY_NOVA_CRYPTO = "extra:buy:nova:crypto"
    BUY_COSMIC_CRYPTO = "extra:buy:cosmic:crypto"

    # NEW: ручная проверка оплаты (polling)
    CHECK_PREFIX = "extra:check:"  # + <payment_id>

    # навигация
    BACK = "extra:back"
    TO_MENU = "extra:to_menu"

    # free generation for channel subscribe
    FREE = "extra:free"
    FREE_CHECK = "extra:free:check"
    FREE_INFO = "extra:free:info"
    FREE_PROMO = "extra:free:promo"


def extra_menu_kb(current_plan_name: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="Как получить бесплатную генерацию", callback_data=ExtraCallbacks.FREE_INFO)

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
        kb.button(text="💳 Купить (СБП)", callback_data=ExtraCallbacks.BUY_ORBIT)
        kb.button(text="₿ Купить (Крипто)", callback_data=ExtraCallbacks.BUY_ORBIT_CRYPTO)
    elif plan_name == "Nova":
        kb.button(text="💳 Купить (СБП)", callback_data=ExtraCallbacks.BUY_NOVA)
        kb.button(text="₿ Купить (Крипто)", callback_data=ExtraCallbacks.BUY_NOVA_CRYPTO)
    elif plan_name == "Cosmic":
        kb.button(text="💳 Купить (СБП)", callback_data=ExtraCallbacks.BUY_COSMIC)
        kb.button(text="₿ Купить (Крипто)", callback_data=ExtraCallbacks.BUY_COSMIC_CRYPTO)

    kb.button(text="⬅️ Назад", callback_data=ExtraCallbacks.BACK)

    kb.adjust(1, 1)
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
