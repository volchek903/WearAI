from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription
from app.models.user import User
from app.models.user_subscription import UserSubscription


async def get_user(session: AsyncSession, tg_id: int) -> User | None:
    return await session.scalar(select(User).where(User.tg_id == tg_id))


async def get_active_plan_name(session: AsyncSession, user_id: int) -> str:
    """
    Активная подписка берётся из user_subscription.status == 1.
    Если нет — считаем Launch.
    """
    stmt = (
        select(Subscription.name)
        .select_from(UserSubscription)
        .join(Subscription, Subscription.id == UserSubscription.subscription_id)
        .where(UserSubscription.user_id == user_id, UserSubscription.status == 1)
        .order_by(UserSubscription.activated_at.desc())
        .limit(1)
    )
    name = await session.scalar(stmt)
    return name or "Launch"


async def get_active_remaining(session: AsyncSession, user_id: int) -> tuple[int, int]:
    """
    Остатки берём из активной user_subscription (status == 1).
    Если нет — отдаём free остатки (2 видео, 3 фото) или можно 0/0.
    """
    stmt = (
        select(UserSubscription.remaining_video, UserSubscription.remaining_photo)
        .where(UserSubscription.user_id == user_id, UserSubscription.status == 1)
        .order_by(UserSubscription.activated_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if not row:
        return 2, 3
    return int(row[0]), int(row[1])


async def get_plan(session: AsyncSession, plan_name: str) -> Subscription | None:
    return await session.scalar(
        select(Subscription).where(Subscription.name == plan_name)
    )


async def get_all_plans(session: AsyncSession) -> list[Subscription]:
    res = await session.execute(select(Subscription).order_by(Subscription.id.asc()))
    return list(res.scalars().all())
