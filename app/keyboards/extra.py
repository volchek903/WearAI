# app/keyboards/extra.py
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.utils import add_button, make_button

class ExtraCallbacks:
    # выбор пакета
    WANT_ORBIT = "extra:want:orbit"
    WANT_NOVA = "extra:want:nova"
    WANT_COSMIC = "extra:want:cosmic"

    # покупка
    BUY_ORBIT = "extra:buy:orbit:sbp"
    BUY_NOVA = "extra:buy:nova:sbp"
    BUY_COSMIC = "extra:buy:cosmic:sbp"
    BUY_ORBIT_CARD = "extra:buy:orbit:card"
    BUY_NOVA_CARD = "extra:buy:nova:card"
    BUY_COSMIC_CARD = "extra:buy:cosmic:card"
    BUY_ORBIT_CRYPTO = "extra:buy:orbit:crypto"
    BUY_NOVA_CRYPTO = "extra:buy:nova:crypto"
    BUY_COSMIC_CRYPTO = "extra:buy:cosmic:crypto"
    BUY_ORBIT_STARS = "extra:buy:orbit:stars"
    BUY_NOVA_STARS = "extra:buy:nova:stars"
    BUY_COSMIC_STARS = "extra:buy:cosmic:stars"

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

    add_button(
        kb,
        text="Как получить бесплатно",
        callback_data=ExtraCallbacks.FREE_INFO,
        style="success",
    )

    if current_plan_name != "Orbit":
        add_button(
            kb,
            text="✨ Хочу Orbit",
            callback_data=ExtraCallbacks.WANT_ORBIT,
            style="success",
        )
    if current_plan_name != "Nova":
        add_button(
            kb,
            text="🚀 Хочу Nova",
            callback_data=ExtraCallbacks.WANT_NOVA,
            style="success",
        )
    if current_plan_name != "Cosmic":
        add_button(
            kb,
            text="🌌 Хочу Cosmic",
            callback_data=ExtraCallbacks.WANT_COSMIC,
            style="success",
        )

    add_button(
        kb, text="⬅️ Назад", callback_data=ExtraCallbacks.TO_MENU, style="danger"
    )

    kb.adjust(1)
    return kb.as_markup()


def extra_buy_kb(plan_name: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    if plan_name == "Orbit":
        add_button(
            kb,
            text="⭐️ Оплата через Stars",
            callback_data=ExtraCallbacks.BUY_ORBIT_STARS,
            style="success",
        )
        add_button(
            kb,
            text="💳 Купить (СБП)",
            callback_data=ExtraCallbacks.BUY_ORBIT,
            style="success",
        )
        add_button(
            kb,
            text="💳 Оплата картой",
            callback_data=ExtraCallbacks.BUY_ORBIT_CARD,
            style="success",
        )
        add_button(
            kb,
            text="₿ Купить (Крипто)",
            callback_data=ExtraCallbacks.BUY_ORBIT_CRYPTO,
            style="success",
        )
    elif plan_name == "Nova":
        add_button(
            kb,
            text="⭐️ Оплата через Stars",
            callback_data=ExtraCallbacks.BUY_NOVA_STARS,
            style="success",
        )
        add_button(
            kb,
            text="💳 Купить (СБП)",
            callback_data=ExtraCallbacks.BUY_NOVA,
            style="success",
        )
        add_button(
            kb,
            text="💳 Оплата картой",
            callback_data=ExtraCallbacks.BUY_NOVA_CARD,
            style="success",
        )
        add_button(
            kb,
            text="₿ Купить (Крипто)",
            callback_data=ExtraCallbacks.BUY_NOVA_CRYPTO,
            style="success",
        )
    elif plan_name == "Cosmic":
        add_button(
            kb,
            text="⭐️ Оплата через Stars",
            callback_data=ExtraCallbacks.BUY_COSMIC_STARS,
            style="success",
        )
        add_button(
            kb,
            text="💳 Купить (СБП)",
            callback_data=ExtraCallbacks.BUY_COSMIC,
            style="success",
        )
        add_button(
            kb,
            text="💳 Оплата картой",
            callback_data=ExtraCallbacks.BUY_COSMIC_CARD,
            style="success",
        )
        add_button(
            kb,
            text="₿ Купить (Крипто)",
            callback_data=ExtraCallbacks.BUY_COSMIC_CRYPTO,
            style="success",
        )

    add_button(kb, text="⬅️ Назад", callback_data=ExtraCallbacks.BACK, style="danger")

    kb.adjust(1, 1)
    return kb.as_markup()


# Старый вариант (просто URL оплаты)
def extra_pay_url_kb(redirect_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(make_button(text="💳 Оплатить", url=redirect_url, style="success"))
    kb.row(make_button(text="⬅️ Назад", callback_data=ExtraCallbacks.BACK, style="danger"))
    kb.adjust(1)
    return kb.as_markup()


# NEW: вариант под polling (Оплатить + Проверить оплату)
def extra_pay_poll_kb(redirect_url: str, payment_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(make_button(text="💳 Оплатить", url=redirect_url, style="success"))
    kb.row(
        make_button(
            text="🔄 Проверить оплату",
            callback_data=f"{ExtraCallbacks.CHECK_PREFIX}{payment_id}",
            style="success",
        )
    )
    kb.row(make_button(text="⬅️ Назад", callback_data=ExtraCallbacks.BACK, style="danger"))
    kb.adjust(1)
    return kb.as_markup()
