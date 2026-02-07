from __future__ import annotations

import asyncio
import logging
import os
import sys

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import AdminCallbacks, admin_menu_kb
from app.repository.admin import is_admin, get_last_users, get_users_stats
from app.utils.tg_edit import edit_text_safe

router = Router()
logger = logging.getLogger(__name__)


async def _ensure_admin(call: CallbackQuery, session: AsyncSession, action: str) -> bool:
    tg_id = call.from_user.id
    if await is_admin(session, tg_id):
        return True
    logger.warning("ADMIN_DENY action=%s tg_id=%s data=%s", action, tg_id, call.data)
    await call.answer("Недостаточно прав", show_alert=True)
    return False


async def _restart_process(message: Message) -> None:
    # Give the bot time to send the confirmation message before restarting.
    await message.answer("🔄 Перезапускаю бота…")
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)


@router.message(Command("admin"))
async def admin_entry(message: Message, session: AsyncSession) -> None:
    if not await is_admin(session, message.from_user.id):
        return
    await message.answer("⚙️ Админка", reply_markup=admin_menu_kb())


@router.message(Command("restart"))
async def admin_restart(message: Message, session: AsyncSession) -> None:
    if message.from_user.id != 830091750:
        return
    await _restart_process(message)


@router.callback_query(F.data == AdminCallbacks.STATS)
async def admin_stats(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.stats"):
        return
    total_users, active_subs = await get_users_stats(session)

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей: <code>{total_users}</code>\n"
        f"✅ Активных подписок: <code>{active_subs}</code>"
    )

    await edit_text_safe(call, text, reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.USERS)
async def admin_users(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.users"):
        return
    rows = await get_last_users(session, limit=10)

    if not rows:
        text = "👥 <b>Пользователи</b>\n\nПока пусто 💤"
    else:
        lines: list[str] = []
        for uid, tg_id, username, created_at in rows:
            uname = username or "-"
            lines.append(f"• id={uid} tg={tg_id} @{uname} ({created_at:%Y-%m-%d})")
        text = "👥 <b>Последние 10 пользователей</b>\n\n" + "\n".join(lines)

    await edit_text_safe(call, text, reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.BACK)
async def admin_back(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.back"):
        return
    await edit_text_safe(call, "⚙️ Админка", reply_markup=admin_menu_kb())
    await call.answer()
