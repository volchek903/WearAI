# app/repository/payments.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, PaymentStatus
from app.models.subscription import Subscription
from app.models.user_subscription import UserSubscription
from app.repository.extra import get_user  # tg_id -> users row
from app.repository.access import give_subscription_plan

logger = logging.getLogger(__name__)


async def create_pending_payment(
    session: AsyncSession,
    *,
    tg_user_id: int,
    plan_name: str,
    amount: int,
    currency: str,
    tx_id: str,
) -> Payment:
    logger.info(
        "payments.create_pending_payment: tg_user_id=%s plan=%s amount=%s %s tx_id=%s",
        tg_user_id,
        plan_name,
        amount,
        currency,
        tx_id,
    )

    p = Payment(
        tg_user_id=tg_user_id,  # ✅ FIX: корректное имя атрибута
        plan_name=plan_name,
        amount=amount,
        currency=currency,
        platega_transaction_id=tx_id,
        status=PaymentStatus.PENDING,
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)

    logger.info(
        "payments.create_pending_payment: created payment_id=%s status=%s",
        p.id,
        p.status,
    )
    return p


async def get_latest_pending_payment(
    session: AsyncSession, tg_user_id: int
) -> Payment | None:
    logger.info("payments.get_latest_pending_payment: tg_user_id=%s", tg_user_id)

    q = await session.execute(
        select(Payment)
        .where(Payment.tg_user_id == tg_user_id)  # ✅ FIX: корректное имя атрибута
        .where(Payment.status == PaymentStatus.PENDING)
        .order_by(desc(Payment.id))
        .limit(1)
    )
    p = q.scalar_one_or_none()

    logger.info(
        "payments.get_latest_pending_payment: result=%s",
        f"payment_id={p.id} tx_id={p.platega_transaction_id}" if p else "None",
    )
    return p


async def get_pending_payments_batch(
    session: AsyncSession, limit: int = 50
) -> list[Payment]:
    """
    Для фонового polling: взять пачку PENDING платежей.
    """
    q = await session.execute(
        select(Payment)
        .where(Payment.status == PaymentStatus.PENDING)
        .order_by(desc(Payment.id))
        .limit(limit)
    )
    return list(q.scalars().all())


async def get_payment_by_id(session: AsyncSession, payment_id: int) -> Payment | None:
    q = await session.execute(select(Payment).where(Payment.id == payment_id))
    return q.scalar_one_or_none()


async def mark_payment_status(
    session: AsyncSession, payment: Payment, status: PaymentStatus
) -> None:
    logger.info(
        "payments.mark_payment_status: payment_id=%s tx_id=%s old=%s new=%s",
        payment.id,
        payment.platega_transaction_id,
        payment.status,
        status,
    )

    payment.status = status
    if status == PaymentStatus.CONFIRMED:
        payment.confirmed_at = datetime.now(timezone.utc)

    await session.commit()

    logger.info(
        "payments.mark_payment_status: done payment_id=%s status=%s confirmed_at=%s",
        payment.id,
        payment.status,
        payment.confirmed_at,
    )


async def _get_active_user_subscription(
    session: AsyncSession, user_id: int
) -> UserSubscription | None:
    logger.info("payments._get_active_user_subscription: user_id=%s", user_id)

    q = await session.execute(
        select(UserSubscription)
        .where(UserSubscription.user_id == user_id)
        .where(UserSubscription.status == 1)
        .order_by(desc(UserSubscription.id))
        .limit(1)
    )
    us = q.scalar_one_or_none()

    logger.info(
        "payments._get_active_user_subscription: result=%s",
        (
            f"user_sub_id={us.id} subscription_id={us.subscription_id} expires_at={us.expires_at} "
            f"remaining_video={us.remaining_video} remaining_photo={us.remaining_photo}"
            if us
            else "None"
        ),
    )
    return us


async def apply_plan_to_user(
    session: AsyncSession, tg_user_id: int, plan: Subscription
) -> None:
    """
    ✅ FIXED: теперь это "апгрейд тарифа", а не просто донат-пакет:
    - меняем subscription_id активной подписки на выбранный план
    - выставляем remaining_video/photo под лимиты плана (или можно прибавлять — см. ниже)
    - если duration_days > 0 — ставим expires_at от max(now, текущий expires_at)
    """
    logger.info(
        "payments.apply_plan_to_user: START tg_user_id=%s plan=%s plan_id=%s video=%s photo=%s duration_days=%s",
        tg_user_id,
        getattr(plan, "name", None),
        getattr(plan, "id", None),
        getattr(plan, "video_generations", None),
        getattr(plan, "photo_generations", None),
        getattr(plan, "duration_days", None),
    )

    try:
        user = await get_user(session, tg_user_id)
        if not user:
            logger.warning(
                "payments.apply_plan_to_user: user NOT FOUND by tg_user_id=%s",
                tg_user_id,
            )
            return

        active = await _get_active_user_subscription(session, user.id)
        if not active:
            logger.warning(
                "payments.apply_plan_to_user: active subscription NOT FOUND user_id=%s tg_user_id=%s",
                user.id,
                tg_user_id,
            )
            await give_subscription_plan(session, user, int(plan.id))
            return

        before_subscription_id = active.subscription_id
        before_video = int(active.remaining_video or 0)
        before_photo = int(active.remaining_photo or 0)
        before_expires = active.expires_at

        # --- 1) меняем план (это изменит имя тарифа в UI) ---
        active.subscription_id = int(plan.id)

        # --- 2) лимиты: как "тариф" логичнее ставить лимит плана ---
        # Если хочешь "прибавлять" к текущим — поменяй на before_* + plan.*
        active.remaining_video = int(plan.video_generations or 0)
        active.remaining_photo = int(plan.photo_generations or 0)

        # --- 3) срок ---
        # Если duration_days == 0 => бессрочно (не трогаем expires_at)
        if int(plan.duration_days or 0) > 0:
            now = datetime.now(timezone.utc)

            expires = active.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)

            base = expires if expires > now else now
            active.expires_at = base + timedelta(days=int(plan.duration_days))

        await session.commit()

        logger.info(
            "payments.apply_plan_to_user: DONE user_id=%s sub_id=%s "
            "subscription_id %s->%s plan=%s "
            "video %s->%s photo %s->%s expires %s->%s",
            user.id,
            active.id,
            before_subscription_id,
            active.subscription_id,
            plan.name,
            before_video,
            active.remaining_video,
            before_photo,
            active.remaining_photo,
            before_expires,
            active.expires_at,
        )

    except Exception:
        logger.exception(
            "payments.apply_plan_to_user: ERROR tg_user_id=%s plan=%s",
            tg_user_id,
            getattr(plan, "name", None),
        )
        raise
