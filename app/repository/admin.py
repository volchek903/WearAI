from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.user import User


# =========================
# Проверка админа
# =========================
async def is_admin(session: AsyncSession, tg_id: int) -> bool:
    stmt = (
        select(Admin.id)
        .join(User, User.id == Admin.user_id)
        .where(User.tg_id == tg_id)
        .limit(1)
    )
    return (await session.scalar(stmt)) is not None


# =========================
# Статистика
# =========================
async def get_users_stats(session: AsyncSession) -> tuple[int, int]:
    total_users = await session.scalar(select(func.count(User.id)))

    active_subs = await session.scalar(
        select(func.count(User.id)).where(User.subscription_active.is_(True))
    )

    return total_users or 0, active_subs or 0


# =========================
# Последние пользователи
# =========================
async def get_last_users(
    session: AsyncSession,
    limit: int = 10,
) -> list[tuple[int, int, str | None, object]]:
    result = await session.execute(
        select(
            User.id,
            User.tg_id,
            User.username,
            User.created_at,
        )
        .order_by(User.id.desc())
        .limit(limit)
    )
    return result.all()
