from __future__ import annotations

import logging

from aiogram import Router
from aiogram.fsm.state import State, StatesGroup

from app.models.subscription import Subscription

router = Router()
logger = logging.getLogger(__name__)

STAR_USD_RATE = 23.99 / 1000
USD_TO_RUB = 79
RUB_PER_STAR = STAR_USD_RATE * USD_TO_RUB


class FreePromoFlow(StatesGroup):
    code = State()


class CustomCreditsFlow(StatesGroup):
    amount = State()


def format_promo_bonus(promo) -> str:
    bonus_credits = int(getattr(promo, "bonus_credits", 0) or 0)
    if bonus_credits > 0:
        return f"{bonus_credits} кредитов"

    bonus_photo = int(getattr(promo, "bonus_photo", 0) or 0)
    bonus_video = int(getattr(promo, "bonus_video", 0) or 0)
    parts: list[str] = []
    if bonus_photo > 0:
        parts.append(f"🖼️ {bonus_photo} фото")
    if bonus_video > 0:
        parts.append(f"🎬 {bonus_video} видео")
    return " • ".join(parts) if parts else "0 кредитов"


def payment_tg_id(payment) -> int | None:
    return (
        getattr(payment, "tg_user_id", None)
        or getattr(payment, "user_tg_id", None)
        or getattr(payment, "user_tg", None)
    )


def stars_for_credits(credits: int) -> int:
    if credits <= 0:
        return 0
    raw = max(1, round(int(credits) / RUB_PER_STAR))
    return ((raw + 9) // 10) * 10


def custom_pitch(credits: int) -> str:
    stars = stars_for_credits(credits)
    return (
        "💠 <b>Своя сумма</b>\n\n"
        f"Вы выбрали пополнение на <b>{credits}</b> кредитов.\n"
        f"К оплате: <b>{credits} ₽</b> / <b>{stars} ⭐</b>\n\n"
        "Выберите удобный способ оплаты 👇"
    )


def escape_html(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def price_key(plan: Subscription) -> tuple:
    rub_price = int(float(plan.price)) if float(plan.price) > 0 else 0
    stars_price = int(getattr(plan, "stars_price", 0) or 0)
    effective = rub_price if rub_price > 0 else stars_price
    return (effective, rub_price, stars_price, plan.name.lower())


def purchasable_plans(plans: list[Subscription]) -> list[Subscription]:
    return [
        plan
        for plan in sorted(plans, key=price_key)
        if plan.name not in {"Base", "Launch"}
    ]


def package_discount_text(plan_name: str) -> str:
    if plan_name == "Pulse":
        return "10%"
    if plan_name == "Orbit":
        return "10%"
    if plan_name == "Nova":
        return "15%"
    if plan_name == "Cosmic":
        return "25%"
    return "0%"


def table_html(plans: list[Subscription]) -> str:
    lines = ["<b>Кредитные пакеты</b>"]

    for plan in purchasable_plans(plans):
        rub_price = int(float(plan.price)) if float(plan.price) > 0 else 0
        stars_price = int(getattr(plan, "stars_price", 0) or 0)

        if rub_price <= 0 and stars_price <= 0:
            rub_part = "Бесплатно"
            stars_part = "Бесплатно"
        else:
            rub_part = f"{rub_price} ₽" if rub_price > 0 else "—"
            stars_part = f"{stars_price} ⭐" if stars_price > 0 else "—"
        lines.append(
            "\n".join(
                [
                    f"<b>{escape_html(plan.name)}</b>",
                    f"Кредиты: <b>{int(getattr(plan, 'credit_amount', 0) or 0)}</b>",
                    f"Скидка: <b>{package_discount_text(plan.name)}</b>",
                    f"Цена: {rub_part} / {stars_part}",
                ]
            )
        )
        lines.append("────────────")

    if lines and lines[-1] == "────────────":
        lines.pop()

    return "\n".join(lines)


def extra_text(
    current_name: str,
    paid_credit_balance: int,
    free_credit_balance: int,
    table: str,
) -> str:
    return (
        "✨ <b>Дополнительные возможности</b>\n\n"
        f"Режим оплаты: <b>{escape_html(current_name)}</b>\n"
        f"Основные кредиты: <b>{int(paid_credit_balance)}</b>\n"
        f"Бесплатные кредиты: <b>{int(free_credit_balance)}</b>\n"
        f"Всего доступно: <b>{int(paid_credit_balance) + int(free_credit_balance)}</b>\n"
        "\n"
        f"{table}\n\n"
        "Выбирай пакет ниже, чтобы пополнить баланс 👇"
    )


def package_pitch(plan_name: str, plan: Subscription) -> str:
    if plan_name == "Pulse":
        intro = "Лёгкий старт с <b>Pulse</b> ⚡"
        vibe = "Подойдет, если хочешь быстро протестировать механику без большого пополнения."
    elif plan_name == "Orbit":
        intro = "Ооо, <b>Orbit</b> — быстрый старт 🚀"
        vibe = "Подойдет, если хочешь аккуратно тестировать гипотезы и не держать большой остаток."
    elif plan_name == "Nova":
        intro = "Йо! <b>Nova</b> — рабочий объём 😮‍💨✨"
        vibe = "Хватает для регулярной генерации фото и видео без постоянных пополнений."
    else:
        intro = "Воу… <b>Cosmic</b> — запас с комфортом 🤯🌌"
        vibe = "Большой баланс для постоянной работы и агрессивного продакшна."

    rub_price = int(float(plan.price)) if float(plan.price) > 0 else 0
    stars_price = int(getattr(plan, "stars_price", 0) or 0)
    if rub_price <= 0 and stars_price <= 0:
        price = "Бесплатно"
    else:
        rub_old = int(round(rub_price * 1.1)) if rub_price > 0 else 0
        stars_old = int(round(stars_price * 1.1)) if stars_price > 0 else 0

        rub_part = (
            f"<b>{rub_price} ₽</b> (скидка, было <s>{rub_old} ₽</s>)"
            if rub_price > 0
            else "—"
        )
        stars_part = (
            f"<b>{stars_price} ⭐</b> (скидка, было <s>{stars_old} ⭐</s>)"
            if stars_price > 0
            else "—"
        )
        price = f"{rub_part} / {stars_part}"
    return (
        f"{intro}\n\n"
        "Вот что ты получаешь:\n"
        f"• 💠 Кредиты: <b>{int(getattr(plan, 'credit_amount', 0) or 0)}</b>\n"
        f"• 🏷 Скидка: <b>{package_discount_text(plan.name)}</b>\n"
        f"• 💰 Стоимость: {price}\n\n"
        f"{vibe}\n\n"
        "Если готов — жми <b>Купить</b> 😉"
    )


__all__ = [
    "CustomCreditsFlow",
    "FreePromoFlow",
    "custom_pitch",
    "extra_text",
    "format_promo_bonus",
    "logger",
    "package_pitch",
    "payment_tg_id",
    "purchasable_plans",
    "router",
    "stars_for_credits",
    "table_html",
]
