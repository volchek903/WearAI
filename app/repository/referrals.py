from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription
from app.models.user import User
from app.models.referral import Referral
from app.models.user_subscription import UserSubscription
from app.repository.access import give_subscription_plan
from app.repository.users import get_user_by_tg_id

logger = logging.getLogger(__name__)


def parse_referrer_tg_id(start_payload: str) -> int | None:
    payload = (start_payload or "").strip()
    if not payload:
        return None
    if payload.startswith("ref_"):
        ref = payload[4:]
    elif payload.startswith("ref-"):
        ref = payload[4:]
    elif payload.startswith("ref"):
        ref = payload[3:]
    else:
        return None

    ref = ref.strip("_- ")
    return int(ref) if ref.isdigit() else None


async def _get_plan_by_index(session: AsyncSession, index: int) -> Subscription | None:
    if index < 0:
        return None
    return await session.scalar(
        select(Subscription).order_by(Subscription.id.asc()).offset(index).limit(1)
    )


async def _get_active_plan(session: AsyncSession, user_id: int) -> Subscription | None:
    q = await session.execute(
        select(Subscription)
        .select_from(UserSubscription)
        .join(Subscription, Subscription.id == UserSubscription.subscription_id)
        .where(UserSubscription.user_id == user_id)
        .where(UserSubscription.status == 1)
        .order_by(desc(UserSubscription.id))
        .limit(1)
    )
    return q.scalar_one_or_none()


async def get_referrals_count(session: AsyncSession, referrer_user_id: int) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(Referral)
        .where(Referral.referrer_user_id == referrer_user_id)
    )
    return int(count or 0)


async def process_referral_for_new_user(
    session: AsyncSession,
    *,
    new_user: User,
    referrer_tg_id: int,
) -> None:
    if new_user.referred_by_id is not None:
        return
    if new_user.tg_id == referrer_tg_id:
        return

    referrer = await get_user_by_tg_id(session, referrer_tg_id)
    if referrer is None:
        return

    existing = await session.scalar(
        select(Referral.id).where(Referral.referred_user_id == new_user.id)
    )
    if existing is not None:
        return

    new_user.referred_by_id = referrer.id
    session.add(
        Referral(referrer_user_id=referrer.id, referred_user_id=new_user.id)
    )
    await session.commit()
    await session.refresh(new_user)

    count = await get_referrals_count(session, referrer.id)
    await session.execute(
        update(User)
        .where(User.id == referrer.id)
        .values(referrals_count=count)
    )
    await session.commit()
    if count not in {10, 50}:
        return

    target_index = 1 if count == 10 else 2  # 2-я и 3-я подписка (0-based index)
    target_plan = await _get_plan_by_index(session, target_index)
    if target_plan is None:
        logger.warning(
            "referrals: target plan not found index=%s referrer_tg_id=%s",
            target_index,
            referrer_tg_id,
        )
        return

    active_plan = await _get_active_plan(session, referrer.id)
    if active_plan is not None:
        try:
            active_price = Decimal(active_plan.price or 0)
            target_price = Decimal(target_plan.price or 0)
        except Exception:
            active_price = Decimal(0)
            target_price = Decimal(target_plan.price or 0)

        if active_plan.id > target_plan.id and active_price > target_price:
            return

    await give_subscription_plan(session, referrer, int(target_plan.id))
    logger.info(
        "referrals: awarded plan=%s to tg_id=%s for referrals_count=%s",
        target_plan.name,
        referrer.tg_id,
        count,
    )
