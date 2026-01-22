from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription
from app.models.user_subscription import UserSubscription


class NoGenerationsLeft(Exception):
    pass


async def ensure_default_subscription(session: AsyncSession, user_id: int) -> None:
    active_id = await session.scalar(
        select(UserSubscription.id)
        .where(UserSubscription.user_id == user_id, UserSubscription.status == 1)
        .limit(1)
    )
    if active_id:
        return

    sub = await session.scalar(
        select(Subscription).order_by(Subscription.id.asc()).limit(1)
    )
    if not sub:
        return

    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=int(sub.duration_days))

    session.add(
        UserSubscription(
            user_id=user_id,
            subscription_id=sub.id,
            expires_at=expires,
            remaining_photo=int(sub.photo_generations),
            remaining_video=int(sub.video_generations),
            status=1,
        )
    )
    await session.commit()


async def _get_active_us_id(session: AsyncSession, user_id: int) -> int | None:
    return await session.scalar(
        select(UserSubscription.id)
        .where(UserSubscription.user_id == user_id, UserSubscription.status == 1)
        .order_by(UserSubscription.activated_at.desc())
        .limit(1)
    )


async def charge_photo_generation(session: AsyncSession, user_id: int) -> None:
    us_id = await _get_active_us_id(session, user_id)
    if not us_id:
        raise NoGenerationsLeft()

    new_left = await session.scalar(
        update(UserSubscription)
        .where(UserSubscription.id == us_id, UserSubscription.remaining_photo > 0)
        .values(remaining_photo=UserSubscription.remaining_photo - 1)
        .returning(UserSubscription.remaining_photo)
    )

    if new_left is None:
        raise NoGenerationsLeft()

    await session.commit()


async def refund_photo_generation(session: AsyncSession, user_id: int) -> None:
    us_id = await _get_active_us_id(session, user_id)
    if not us_id:
        return

    await session.execute(
        update(UserSubscription)
        .where(UserSubscription.id == us_id)
        .values(remaining_photo=UserSubscription.remaining_photo + 1)
    )
    await session.commit()


async def charge_video_generation(session: AsyncSession, user_id: int) -> None:
    us_id = await _get_active_us_id(session, user_id)
    if not us_id:
        raise NoGenerationsLeft()

    new_left = await session.scalar(
        update(UserSubscription)
        .where(UserSubscription.id == us_id, UserSubscription.remaining_video > 0)
        .values(remaining_video=UserSubscription.remaining_video - 1)
        .returning(UserSubscription.remaining_video)
    )

    if new_left is None:
        raise NoGenerationsLeft()

    await session.commit()


async def refund_video_generation(session: AsyncSession, user_id: int) -> None:
    us_id = await _get_active_us_id(session, user_id)
    if not us_id:
        return

    await session.execute(
        update(UserSubscription)
        .where(UserSubscription.id == us_id)
        .values(remaining_video=UserSubscription.remaining_video + 1)
    )
    await session.commit()
