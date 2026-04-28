from __future__ import annotations

import asyncio
import logging
import os
import sys
from decimal import Decimal

from aiogram import Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import admin_menu_kb
from app.models.subscription import Subscription
from app.repository.admin import is_admin
from app.repository.admin_actions import log_admin_action

router = Router()
logger = logging.getLogger(__name__)


async def ensure_admin(
    call: CallbackQuery,
    session: AsyncSession,
    action: str,
) -> bool:
    tg_id = call.from_user.id
    if await is_admin(session, tg_id):
        await log_admin_action(
            session,
            tg_id=tg_id,
            action=action,
            data=str(call.data or ""),
        )
        return True
    logger.warning("ADMIN_DENY action=%s tg_id=%s data=%s", action, tg_id, call.data)
    await call.answer("Недостаточно прав", show_alert=True)
    return False


async def restart_process(message: Message) -> None:
    await message.answer("🔄 Перезапускаю бота…")
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)


def plan_info(plan: Subscription) -> str:
    price = "Бесплатно" if float(plan.price) == 0 else f"{int(float(plan.price))} ₽"
    stars_price = int(getattr(plan, "stars_price", 0) or 0)
    stars = "Бесплатно" if stars_price == 0 else f"{stars_price} ⭐"
    return (
        "📦 <b>Пакет</b>\n\n"
        f"Название: <b>{plan.name}</b>\n"
        f"Кредиты: <b>{int(getattr(plan, 'credit_amount', 0) or 0)}</b>\n"
        f"Цена: <b>{price}</b>\n"
        f"Цена в ⭐: <b>{stars}</b>"
    )


def new_plan_preview(data: dict) -> str:
    name = str(data.get("name", "")).strip()
    credits = int(data.get("credit_amount") or 0)
    price = data.get("price")
    stars_price = int(data.get("stars_price") or 0)
    if price is None or Decimal(price) == 0:
        price_text = "Бесплатно"
    else:
        price_text = f"{int(price)} ₽"
    stars_text = "Бесплатно" if stars_price == 0 else f"{stars_price} ⭐"
    return (
        "📦 <b>Новый пакет</b>\n\n"
        f"Название: <b>{name}</b>\n"
        f"Кредиты: <b>{credits}</b>\n"
        f"Цена: <b>{price_text}</b>\n"
        f"Цена в ⭐: <b>{stars_text}</b>\n\n"
        "Все верно?"
    )


def parse_users_page(data: str) -> int:
    try:
        _, page = data.rsplit(":", 1)
        return max(1, int(page))
    except Exception:
        return 1


__all__ = [
    "admin_menu_kb",
    "ensure_admin",
    "logger",
    "new_plan_preview",
    "parse_users_page",
    "plan_info",
    "restart_process",
    "router",
]
