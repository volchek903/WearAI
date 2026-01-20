from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.user import User
from datetime import datetime, timedelta


async def get_user_by_tg_id(
    session: AsyncSession,
    tg_id: int,
) -> User | None:
    return await session.scalar(select(User).where(User.tg_id == tg_id))


async def is_user_admin(
    session: AsyncSession,
    user: User,
) -> bool:
    return (
        await session.scalar(select(Admin.id).where(Admin.user_id == user.id))
    ) is not None


async def add_admin(
    session: AsyncSession,
    user: User,
) -> None:
    session.add(Admin(user_id=user.id))
    await session.commit()


async def remove_admin(
    session: AsyncSession,
    user: User,
) -> None:
    await session.execute(delete(Admin).where(Admin.user_id == user.id))
    await session.commit()


async def give_subscription(
    session: AsyncSession,
    user: User,
) -> None:
    user.subscription_active = True
    await session.commit()


async def give_subscription_days(
    session: AsyncSession,
    user: User,
    days: int,
) -> None:
    user.subscription_active = True
    user.subscription_until = datetime.utcnow() + timedelta(days=days)
    await session.commit()
