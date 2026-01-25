# app/repository/access.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.subscription import Subscription
from app.models.user import User
from app.models.user_subscription import UserSubscription

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


async def _deactivate_user_subscriptions(session: AsyncSession, user_id: int) -> None:
    """
    ✅ Под твою актуальную модель:
    status: 1 = active, 0 = inactive
    """
    await session.execute(
        update(UserSubscription)
        .where(UserSubscription.user_id == user_id)
        .where(UserSubscription.status == 1)
        .values(status=0)
    )


async def _get_active_user_subscription(
    session: AsyncSession, user_id: int
) -> UserSubscription | None:
    q = await session.execute(
        select(UserSubscription)
        .where(UserSubscription.user_id == user_id)
        .where(UserSubscription.status == 1)
        .order_by(desc(UserSubscription.id))
        .limit(1)
    )
    return q.scalar_one_or_none()


async def give_subscription_plan(
    session: AsyncSession, user: User, subscription_id: int
) -> None:
    """
    ✅ Выдать конкретную подписку (без выдачи по дням):
    - находим Subscription по subscription_id
    - деактивируем текущую активную подписку пользователя (status=0)
    - создаём новую активную подписку (status=1)
    - выставляем remaining_video/remaining_photo по лимитам плана
    - expires_at: now + duration_days (если duration_days==0 -> far future)

    ⚠️ ВАЖНО: НИКАКИХ used_photos/used_videos — их нет в твоей модели.
    """
    subscription = await session.scalar(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    if subscription is None:
        logger.warning(
            "give_subscription_plan: subscription not found subscription_id=%s",
            subscription_id,
        )
        return

    now = datetime.now(timezone.utc)

    if int(subscription.duration_days or 0) > 0:
        expires_at = now + timedelta(days=int(subscription.duration_days))
    else:
        expires_at = now + timedelta(days=365 * 100)

    active_before = await _get_active_user_subscription(session, user.id)
    if active_before:
        logger.info(
            "give_subscription_plan: deactivate current user_sub_id=%s user_id=%s sub_id=%s",
            active_before.id,
            user.id,
            active_before.subscription_id,
        )

    await _deactivate_user_subscriptions(session, user.id)

    new_sub = UserSubscription(
        user_id=user.id,
        subscription_id=subscription.id,
        expires_at=expires_at,
        remaining_video=int(subscription.video_generations or 0),
        remaining_photo=int(subscription.photo_generations or 0),
        status=1,
    )
    session.add(new_sub)
    await session.commit()
    await session.refresh(new_sub)

    logger.info(
        "give_subscription_plan: OK user_id=%s tg_id=%s plan_id=%s plan_name=%s new_user_sub_id=%s expires_at=%s",
        user.id,
        user.tg_id,
        subscription.id,
        subscription.name,
        new_sub.id,
        new_sub.expires_at,
    )


# ---- BACKWARD COMPAT (если где-то ещё вызывается give_subscription) ----
async def give_subscription(
    session: AsyncSession, user: User, subscription_id: int | None = None
) -> None:
    """
    Совместимость:
    - если subscription_id не задан — берём самый первый план (как было)
    - дальше вызываем give_subscription_plan
    """
    if subscription_id is None:
        subscription = await session.scalar(
            select(Subscription).order_by(Subscription.id.asc()).limit(1)
        )
        if subscription is None:
            logger.warning("give_subscription: no subscriptions found")
            return
        subscription_id = int(subscription.id)

    await give_subscription_plan(session, user, int(subscription_id))
