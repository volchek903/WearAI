from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription
from app.models.user import User


async def get_user(session: AsyncSession, tg_id: int) -> User | None:
    return await session.scalar(select(User).where(User.tg_id == tg_id))


async def get_active_plan_name(session: AsyncSession, user_id: int) -> str:
    del session, user_id
    return "Кредитный баланс"


async def get_active_remaining(session: AsyncSession, user_id: int) -> tuple[int, int]:
    user = await session.scalar(select(User).where(User.id == user_id))
    paid = int(getattr(user, "credit_balance", 0) or 0) if user else 0
    free = int(getattr(user, "free_credit_balance", 0) or 0) if user else 0
    return paid, free


async def get_plan(session: AsyncSession, plan_name: str) -> Subscription | None:
    return await session.scalar(
        select(Subscription).where(Subscription.name == plan_name)
    )


async def get_all_plans(session: AsyncSession) -> list[Subscription]:
    res = await session.execute(select(Subscription).order_by(Subscription.id.asc()))
    return list(res.scalars().all())
