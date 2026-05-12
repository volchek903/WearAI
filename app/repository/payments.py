# app/repository/payments.py
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, desc, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, PaymentStatus
from app.models.subscription import Subscription
from app.models.user import User
from app.repository.extra import get_user  # tg_id -> users row

logger = logging.getLogger(__name__)

CUSTOM_PLAN_PREFIX = "__custom__:"


class PaymentAlreadyProcessedError(RuntimeError):
    pass


class PaymentPlanNotFoundError(RuntimeError):
    pass


class PaymentUserNotFoundError(RuntimeError):
    pass


def make_custom_plan_name(credits: int) -> str:
    return f"{CUSTOM_PLAN_PREFIX}{int(credits)}"


def parse_custom_plan_credits(plan_name: str | None) -> int | None:
    raw = (plan_name or "").strip()
    if not raw.startswith(CUSTOM_PLAN_PREFIX):
        return None
    value = raw.replace(CUSTOM_PLAN_PREFIX, "", 1)
    try:
        credits = int(value)
    except Exception:
        return None
    return credits if credits > 0 else None


async def create_pending_payment(
    session: AsyncSession,
    *,
    tg_user_id: int,
    plan_name: str,
    amount: int,
    currency: str,
    tx_id: str,
    credit_amount_snapshot: int = 0,
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
        credit_amount_snapshot=max(0, int(credit_amount_snapshot)),
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


async def get_payment_by_tx_id(session: AsyncSession, tx_id: str) -> Payment | None:
    q = await session.execute(
        select(Payment).where(Payment.platega_transaction_id == tx_id).limit(1)
    )
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


async def confirm_payment_and_apply_credits(
    session: AsyncSession,
    payment: Payment,
) -> int:
    payment_id = int(payment.id)
    tx_id = str(payment.platega_transaction_id)
    tg_user_id = int(payment.tg_user_id)
    snapshot_credits = int(getattr(payment, "credit_amount_snapshot", 0) or 0)
    if snapshot_credits > 0:
        credits = snapshot_credits
    else:
        custom_credits = parse_custom_plan_credits(payment.plan_name)
        if custom_credits is not None:
            credits = int(custom_credits)
        else:
            plan = await session.scalar(
                select(Subscription).where(Subscription.name == payment.plan_name)
            )
            if plan is None:
                raise PaymentPlanNotFoundError(
                    f"payment plan not found: {payment.plan_name}"
                )
            credits = int(getattr(plan, "credit_amount", 0) or 0)

    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(Payment)
        .where(Payment.id == payment_id)
        .where(Payment.status == PaymentStatus.PENDING)
        .values(status=PaymentStatus.CONFIRMED, confirmed_at=now)
    )
    if result.rowcount == 0:
        await session.rollback()
        raise PaymentAlreadyProcessedError(
            f"payment already processed: payment_id={payment_id}"
        )

    user_result = await session.execute(
        update(User)
        .where(User.tg_id == tg_user_id)
        .values(credit_balance=User.credit_balance + credits)
    )
    if user_result.rowcount == 0:
        await session.rollback()
        raise PaymentUserNotFoundError(
            f"user not found for payment: tg_user_id={tg_user_id}"
        )

    await session.commit()
    payment.status = PaymentStatus.CONFIRMED
    payment.confirmed_at = now

    logger.info(
        "payments.confirm_payment_and_apply_credits: payment_id=%s tx_id=%s tg_user_id=%s credits=%s",
        payment_id,
        tx_id,
        tg_user_id,
        credits,
    )
    return credits


async def apply_plan_to_user(
    session: AsyncSession, tg_user_id: int, plan: Subscription
) -> None:
    logger.info(
        "payments.apply_plan_to_user: START tg_user_id=%s plan=%s plan_id=%s credits=%s",
        tg_user_id,
        getattr(plan, "name", None),
        getattr(plan, "id", None),
        getattr(plan, "credit_amount", None),
    )

    try:
        user = await get_user(session, tg_user_id)
        if not user:
            logger.warning(
                "payments.apply_plan_to_user: user NOT FOUND by tg_user_id=%s",
                tg_user_id,
            )
            return

        credits = int(getattr(plan, "credit_amount", 0) or 0)
        before_balance = int(user.credit_balance or 0)
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(credit_balance=User.credit_balance + credits)
        )
        await session.commit()
        await session.refresh(user)

        logger.info(
            "payments.apply_plan_to_user: DONE user_id=%s plan=%s credits=%s balance %s->%s",
            user.id,
            plan.name,
            credits,
            before_balance,
            int(user.credit_balance or 0),
        )

    except Exception:
        logger.exception(
            "payments.apply_plan_to_user: ERROR tg_user_id=%s plan=%s",
            tg_user_id,
            getattr(plan, "name", None),
        )
        raise


async def apply_credit_amount_to_user(
    session: AsyncSession, tg_user_id: int, credits: int
) -> None:
    logger.info(
        "payments.apply_credit_amount_to_user: START tg_user_id=%s credits=%s",
        tg_user_id,
        credits,
    )
    user = await get_user(session, tg_user_id)
    if not user:
        logger.warning(
            "payments.apply_credit_amount_to_user: user NOT FOUND by tg_user_id=%s",
            tg_user_id,
        )
        return

    before_balance = int(user.credit_balance or 0)
    await session.execute(
        update(User)
        .where(User.id == user.id)
        .values(credit_balance=User.credit_balance + int(credits))
    )
    await session.commit()
    await session.refresh(user)
    logger.info(
        "payments.apply_credit_amount_to_user: DONE user_id=%s balance %s->%s",
        user.id,
        before_balance,
        int(user.credit_balance or 0),
    )
