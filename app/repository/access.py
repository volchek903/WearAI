from __future__ import annotations

import logging

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.subscription import Subscription
from app.models.user import User

logger = logging.getLogger(__name__)


async def get_user_by_tg_id(session: AsyncSession, tg_id: int) -> User | None:
    return await session.scalar(select(User).where(User.tg_id == tg_id))


async def is_user_admin(session: AsyncSession, user: User) -> bool:
    return (
        await session.scalar(select(Admin.id).where(Admin.user_id == user.id))
    ) is not None


async def add_admin(session: AsyncSession, user: User) -> None:
    session.add(Admin(user_id=user.id))
    await session.commit()


async def remove_admin(session: AsyncSession, user: User) -> None:
    await session.execute(delete(Admin).where(Admin.user_id == user.id))
    await session.commit()


async def give_subscription_plan(
    session: AsyncSession, user: User, subscription_id: int
) -> None:
    subscription = await session.scalar(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    if subscription is None:
        logger.warning(
            "give_subscription_plan: subscription not found subscription_id=%s",
            subscription_id,
        )
        return

    credits = int(getattr(subscription, "credit_amount", 0) or 0)
    await session.execute(
        update(User)
        .where(User.id == user.id)
        .values(credit_balance=User.credit_balance + credits)
    )
    await session.commit()
    logger.info(
        "give_subscription_plan: OK user_id=%s tg_id=%s plan=%s credits=%s",
        user.id,
        user.tg_id,
        subscription.name,
        credits,
    )


async def give_subscription(
    session: AsyncSession, user: User, subscription_id: int | None = None
) -> None:
    if subscription_id is None:
        subscription = await session.scalar(
            select(Subscription).order_by(Subscription.id.asc()).limit(1)
        )
        if subscription is None:
            logger.warning("give_subscription: no subscriptions found")
            return
        subscription_id = int(subscription.id)

    await give_subscription_plan(session, user, int(subscription_id))
