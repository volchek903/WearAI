# app/keyboards/extra.py
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.menu import MenuCallbacks
from app.keyboards.utils import add_button, make_button

class ExtraCallbacks:
    # выбор пакета
    WANT_PREFIX = "extra:want:"

    # покупка
    BUY_PREFIX = "extra:buy:"  # extra:buy:<plan_id>:<method>

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

    @staticmethod
    def want(plan_id: int) -> str:
        return f"{ExtraCallbacks.WANT_PREFIX}{plan_id}"

    @staticmethod
    def buy(plan_id: int, method: str) -> str:
        return f"{ExtraCallbacks.BUY_PREFIX}{plan_id}:{method}"


def extra_menu_kb(plans, current_plan_name: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    add_button(
        kb,
        text="Как получить бесплатно",
        callback_data=ExtraCallbacks.FREE_INFO,
        style="success",
    )

    for p in plans:
        if current_plan_name and p.name == current_plan_name:
            continue
        add_button(
            kb,
            text=f"✨ Хочу {p.name}",
            callback_data=ExtraCallbacks.want(int(p.id)),
            style="success",
        )

    add_button(
        kb, text="⬅️ Назад", callback_data=ExtraCallbacks.TO_MENU, style="danger"
    )

    kb.adjust(1)
    return kb.as_markup()


def extra_buy_kb(plan, *, platega_available: bool = True) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    plan_id = int(plan.id)
    stars_price = int(getattr(plan, "stars_price", 0) or 0)
    rub_price = int(float(plan.price)) if float(plan.price) > 0 else 0

    if stars_price > 0:
        add_button(
            kb,
            text="⭐️ Оплата через Stars",
            callback_data=ExtraCallbacks.buy(plan_id, "stars"),
            style="success",
        )
    if platega_available and rub_price > 0:
        add_button(
            kb,
            text="💳 Купить (СБП)",
            callback_data=ExtraCallbacks.buy(plan_id, "sbp"),
            style="success",
        )
        add_button(
            kb,
            text="💳 Оплата картой",
            callback_data=ExtraCallbacks.buy(plan_id, "card"),
            style="success",
        )
        add_button(
            kb,
            text="₿ Купить (Крипто)",
            callback_data=ExtraCallbacks.buy(plan_id, "crypto"),
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


def buy_generations_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(
        kb,
        text="💳 Купить генерации",
        callback_data=MenuCallbacks.EXTRA,
        style="success",
    )
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
