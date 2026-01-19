from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import AdminCallbacks, admin_menu_kb
from app.models.user import User
from app.repository.admin import is_admin
from app.utils.tg_edit import edit_text_safe  # если у тебя есть эта утилита

router = Router()


@router.message(Command("admin"))
async def admin_entry(message: Message, session: AsyncSession) -> None:
    if not await is_admin(session, message.from_user.id):
        await message.answer("⛔️ Доступ запрещён.")
        return

    await message.answer("⚙️ Админка", reply_markup=admin_menu_kb())


@router.callback_query(F.data == AdminCallbacks.STATS)
async def admin_stats(call: CallbackQuery, session: AsyncSession) -> None:
    # простая статистика
    total_users = await session.scalar(select(func.count(User.id)))
    active_subs = await session.scalar(
        select(func.count(User.id)).where(User.subscription_active.is_(True))
    )

    text = (
        "📊 *Статистика*\n\n"
        f"👥 Всего пользователей: `{total_users}`\n"
        f"✅ Активных подписок: `{active_subs}`"
    )

    await edit_text_safe(call.message, text, reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.USERS)
async def admin_users(call: CallbackQuery, session: AsyncSession) -> None:
    # последние 10 пользователей
    rows = (
        await session.execute(
            select(User.id, User.tg_id, User.username, User.created_at)
            .order_by(User.id.desc())
            .limit(10)
        )
    ).all()

    if not rows:
        text = "👥 Пользователи\n\nПока пусто."
    else:
        lines = []
        for uid, tg_id, username, created_at in rows:
            uname = username or "-"
            lines.append(f"• id={uid} tg={tg_id} @{uname} ({created_at:%Y-%m-%d})")
        text = "👥 *Последние 10 пользователей*\n\n" + "\n".join(lines)

    await edit_text_safe(call.message, text, reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.BACK)
async def admin_back(call: CallbackQuery) -> None:
    await edit_text_safe(call.message, "⚙️ Админка", reply_markup=admin_menu_kb())
    await call.answer()
