from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.subscription import Subscription
from app.models.user import User
from app.models.user_subscription import UserSubscription


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


async def _deactivate_user_subscriptions(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        update(UserSubscription)
        .where(UserSubscription.user_id == user_id, UserSubscription.status == "active")
        .values(status="expired")
    )


async def give_subscription(
    session: AsyncSession, user: User, subscription_id: int | None = None
) -> None:
    if subscription_id is None:
        subscription = await session.scalar(
            select(Subscription).order_by(Subscription.id.asc()).limit(1)
        )
    else:
        subscription = await session.scalar(
            select(Subscription).where(Subscription.id == subscription_id)
        )

    if subscription is None:
        return

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=int(subscription.duration_days))

    await _deactivate_user_subscriptions(session, user.id)

    session.add(
        UserSubscription(
            user_id=user.id,
            subscription_id=subscription.id,
            status="active",
            activated_at=now,
            expires_at=expires_at,
            used_photos=0,
            used_videos=0,
        )
    )
    await session.commit()


async def give_subscription_days(session: AsyncSession, user: User, days: int) -> None:
    subscription = await session.scalar(
        select(Subscription).order_by(Subscription.id.asc()).limit(1)
    )
    if subscription is None:
        return

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=int(days))

    await _deactivate_user_subscriptions(session, user.id)

    session.add(
        UserSubscription(
            user_id=user.id,
            subscription_id=subscription.id,
            status="active",
            activated_at=now,
            expires_at=expires_at,
            used_photos=0,
            used_videos=0,
        )
    )
    await session.commit()
