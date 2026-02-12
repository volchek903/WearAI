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


async def get_users_stats(session: AsyncSession) -> tuple[int, int, int, int]:
    total_users = await session.scalar(select(func.count(User.id)))

    active_subs = await session.scalar(
        select(func.count(func.distinct(UserSubscription.user_id))).where(
            UserSubscription.status == 1,
            UserSubscription.expires_at > func.now(),
        )
    )

    total_photos = await session.scalar(select(func.sum(User.generated_photos)))
    total_videos = await session.scalar(select(func.sum(User.generated_videos)))

    return (
        int(total_users or 0),
        int(active_subs or 0),
        int(total_photos or 0),
        int(total_videos or 0),
    )


async def get_top_referrers(
    session: AsyncSession,
    limit: int = 10,
) -> list[tuple[int, int, str | None, int]]:
    result = await session.execute(
        select(User.id, User.tg_id, User.username, User.referrals_count)
        .where(User.referrals_count > 0)
        .order_by(User.referrals_count.desc(), User.id.asc())
        .limit(limit)
    )
    return [
        (int(uid), int(tg_id), username, int(ref_count or 0))
        for uid, tg_id, username, ref_count in result.all()
    ]


async def get_all_user_tg_ids(session: AsyncSession) -> list[int]:
    res = await session.execute(
        select(User.tg_id).where(User.tg_id.is_not(None))
    )
    return [int(tg_id) for tg_id in res.scalars().all() if tg_id]


async def get_users_page(
    session: AsyncSession,
    limit: int,
    offset: int,
) -> tuple[list[tuple[int, int, str | None, object, int, int]], int]:
    total_users = await session.scalar(select(func.count(User.id)))
    result = await session.execute(
        select(
            User.id,
            User.tg_id,
            User.username,
            User.created_at,
            User.generated_photos,
            User.generated_videos,
        )
        .order_by(User.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.all(), int(total_users or 0)
