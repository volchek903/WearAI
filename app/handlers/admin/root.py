from __future__ import annotations

from aiogram import F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import AdminCallbacks, admin_menu_kb
from app.repository.admin import is_admin
from app.utils.tg_edit import edit_text_safe

from .common import ensure_admin, restart_process, router


@router.message(Command("admin"))
async def admin_entry(message: Message, session: AsyncSession) -> None:
    if not await is_admin(session, message.from_user.id):
        return
    await message.answer("⚙️ Админка", reply_markup=admin_menu_kb())


@router.message(Command("restart"))
async def admin_restart(message: Message, session: AsyncSession) -> None:
    if message.from_user.id != 830091750:
        return
    await restart_process(message)


@router.callback_query(F.data == AdminCallbacks.BACK)
async def admin_back(call: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_admin(call, session, "admin_panel.back"):
        return
    await edit_text_safe(call, "⚙️ Админка", reply_markup=admin_menu_kb())
    await call.answer()
