from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.user import User
from app.models.user_subscription import UserSubscription


async def is_admin(session: AsyncSession, tg_id: int) -> bool:
    stmt = (
        select(Admin.id)
        .join(User, User.id == Admin.user_id)
        .where(User.tg_id == tg_id)
        .limit(1)
    )
    return (await session.scalar(stmt)) is not None


async def get_users_stats(session: AsyncSession) -> tuple[int, int]:
    total_users = await session.scalar(select(func.count(User.id)))

    active_subs = await session.scalar(
        select(func.count(func.distinct(UserSubscription.user_id))).where(
            UserSubscription.status == "active"
        )
    )

    return int(total_users or 0), int(active_subs or 0)


async def get_all_user_tg_ids(session: AsyncSession) -> list[int]:
    res = await session.execute(
        select(User.tg_id).where(User.tg_id.is_not(None))
    )
    return [int(tg_id) for tg_id in res.scalars().all() if tg_id]


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
