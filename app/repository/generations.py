from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repository.app_settings import (
    MODEL_PRICE_WEARAI_AGENT_KEY,
    MODEL_PRICE_KLING_I2V_KEY,
    MODEL_PRICE_KLING_MOTION_KEY,
    MODEL_PRICE_NANO_BANANA_KEY,
    get_agent_daily_free_limit,
    get_launch_daily_limit,
    get_model_price_credits,
)


class NoGenerationsLeft(Exception):
    pass


class PendingGenerationInProgressError(NoGenerationsLeft):
    pass


PHOTO_MODEL_KEY = MODEL_PRICE_NANO_BANANA_KEY
VIDEO_MODEL_I2V_KEY = MODEL_PRICE_KLING_I2V_KEY
VIDEO_MODEL_MOTION_KEY = MODEL_PRICE_KLING_MOTION_KEY
AGENT_MODEL_KEY = MODEL_PRICE_WEARAI_AGENT_KEY

CHARGE_SOURCE_FREE = "free"
CHARGE_SOURCE_PAID = "paid"
CHARGE_SOURCE_MIXED = "mixed"
CHARGE_SOURCE_DAILY_FREE = "dailyfree"
PENDING_CHARGE_STALE_AFTER_S = 3 * 60 * 60


@dataclass(frozen=True, slots=True)
class ChargeResult:
    kind: str
    source: str
    amount: int
    model_key: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _msk_today_key() -> str:
    msk = timezone(timedelta(hours=3))
    return datetime.now(msk).date().isoformat()


async def _get_user(session: AsyncSession, tg_id: int) -> User | None:
    return await session.scalar(select(User).where(User.tg_id == tg_id))


async def get_launch_used_today(session: AsyncSession, tg_id: int | None = None) -> int:
    day_key = _msk_today_key()
    stmt = select(User.free_generations_used_today).where(User.free_generations_day == day_key)
    if tg_id is not None:
        stmt = stmt.where(User.tg_id == tg_id)
    result = await session.execute(stmt)
    return sum(int(v or 0) for v in result.scalars().all())


async def get_active_subscription_name(
    session: AsyncSession, tg_id: int
) -> str | None:
    user = await _get_user(session, tg_id)
    if not user:
        return None
    return "Credits"


async def is_launch_subscription(session: AsyncSession, tg_id: int) -> bool:
    del session, tg_id
    return False


async def ensure_default_subscription(session: AsyncSession, tg_id: int) -> None:
    del session, tg_id
    return


def _daily_free_count_for_user(user: User) -> int:
    if (user.free_generations_day or "") != _msk_today_key():
        return 0
    return int(user.free_generations_used_today or 0)


def _daily_free_agent_count_for_user(user: User) -> int:
    if (user.free_agent_requests_day or "") != _msk_today_key():
        return 0
    return int(user.free_agent_requests_used_today or 0)


def _has_enough_agent_balance(user: User, *, credits: int) -> bool:
    return (int(user.credit_balance or 0) + int(user.free_credit_balance or 0)) >= int(
        credits
    )


def _pending_charge_exists(user: User) -> bool:
    return bool((user.pending_charge_kind or "").strip()) and int(
        user.pending_charge_amount or 0
    ) > 0


def _pending_charge_is_stale(user: User, *, now_ts: int) -> bool:
    created_at = int(getattr(user, "pending_charge_created_at", 0) or 0)
    if created_at <= 0:
        return True
    return max(0, now_ts - created_at) >= PENDING_CHARGE_STALE_AFTER_S


async def get_pending_charge_kind(session: AsyncSession, tg_id: int) -> str | None:
    user = await _get_user(session, tg_id)
    if not user or not _pending_charge_exists(user):
        return None
    return (user.pending_charge_kind or "").strip() or None


async def _charge_credits(
    session: AsyncSession,
    *,
    tg_id: int,
    credits: int,
    kind: str,
    model_key: str,
) -> ChargeResult:
    user = await _get_user(session, tg_id)
    if not user:
        raise NoGenerationsLeft()

    now_ts = int(_utcnow().timestamp())
    if _pending_charge_exists(user):
        if _pending_charge_is_stale(user, now_ts=now_ts):
            await _refund_pending_charge(
                session,
                tg_id=tg_id,
                kind=(user.pending_charge_kind or "").strip(),
            )
            user = await _get_user(session, tg_id)
            if not user:
                raise NoGenerationsLeft()
        else:
            raise PendingGenerationInProgressError(
                f"Pending generation already in progress for tg_id={tg_id}"
            )

    day_key = _msk_today_key()
    free_limit = await get_launch_daily_limit(session)
    current_free_used = _daily_free_count_for_user(user)
    total_credits = int(credits)
    free_available = int(user.free_credit_balance or 0)
    paid_available = int(user.credit_balance or 0)
    free_allowed = int(free_limit) <= 0 or current_free_used < int(free_limit)
    free_to_charge = min(free_available, total_credits) if free_allowed else 0
    paid_to_charge = total_credits - free_to_charge

    if paid_available < paid_to_charge:
        raise NoGenerationsLeft()

    pending_source = CHARGE_SOURCE_PAID
    if free_to_charge and paid_to_charge:
        pending_source = f"{CHARGE_SOURCE_MIXED}:{free_to_charge}"
    elif free_to_charge:
        pending_source = CHARGE_SOURCE_FREE

    values: dict[str, object] = {
        "pending_charge_kind": kind,
        "pending_charge_source": pending_source,
        "pending_charge_amount": total_credits,
        "pending_charge_created_at": now_ts,
    }
    if free_to_charge:
        values["free_credit_balance"] = User.free_credit_balance - free_to_charge
        values["free_generations_day"] = day_key
        values["free_generations_used_today"] = current_free_used + 1
    if paid_to_charge:
        values["credit_balance"] = User.credit_balance - paid_to_charge

    updated = await session.execute(
        update(User)
        .where(
            User.id == user.id,
            User.free_credit_balance >= int(free_to_charge),
            User.credit_balance >= int(paid_to_charge),
        )
        .values(**values)
    )
    if updated.rowcount != 1:
        raise NoGenerationsLeft()

    await session.commit()
    return ChargeResult(
        kind=kind,
        source=(
            CHARGE_SOURCE_MIXED
            if free_to_charge and paid_to_charge
            else (CHARGE_SOURCE_FREE if free_to_charge else CHARGE_SOURCE_PAID)
        ),
        amount=total_credits,
        model_key=model_key,
    )


async def _refund_pending_charge(
    session: AsyncSession,
    *,
    tg_id: int,
    kind: str,
) -> None:
    user = await _get_user(session, tg_id)
    if not user:
        return

    pending_kind = (user.pending_charge_kind or "").strip()
    pending_source_raw = (user.pending_charge_source or "").strip()
    pending_amount = int(user.pending_charge_amount or 0)
    if pending_kind != kind or pending_amount <= 0:
        return

    pending_source = pending_source_raw
    mixed_free_amount = 0
    if pending_source_raw.startswith(f"{CHARGE_SOURCE_MIXED}:"):
        pending_source = CHARGE_SOURCE_MIXED
        try:
            mixed_free_amount = int(pending_source_raw.split(":", 1)[1])
        except Exception:
            mixed_free_amount = 0

    values: dict[str, object] = {
        "pending_charge_kind": None,
        "pending_charge_source": None,
        "pending_charge_amount": 0,
        "pending_charge_created_at": 0,
    }
    if pending_source == CHARGE_SOURCE_DAILY_FREE:
        if (user.free_agent_requests_day or "") == _msk_today_key():
            values["free_agent_requests_used_today"] = max(
                0, int(user.free_agent_requests_used_today or 0) - 1
            )
    elif pending_source == CHARGE_SOURCE_FREE:
        values["free_credit_balance"] = User.free_credit_balance + pending_amount
        if (user.free_generations_day or "") == _msk_today_key():
            values["free_generations_used_today"] = max(
                0, int(user.free_generations_used_today or 0) - 1
            )
    elif pending_source == CHARGE_SOURCE_MIXED:
        free_refund = max(0, min(int(mixed_free_amount), pending_amount))
        paid_refund = max(0, pending_amount - free_refund)
        if free_refund:
            values["free_credit_balance"] = User.free_credit_balance + free_refund
            if (user.free_generations_day or "") == _msk_today_key():
                values["free_generations_used_today"] = max(
                    0, int(user.free_generations_used_today or 0) - 1
                )
        if paid_refund:
            values["credit_balance"] = User.credit_balance + paid_refund
    else:
        values["credit_balance"] = User.credit_balance + pending_amount

    await session.execute(update(User).where(User.id == user.id).values(**values))
    await session.commit()


async def _finalize_pending_charge(
    session: AsyncSession,
    *,
    tg_id: int,
    kind: str,
) -> None:
    user = await _get_user(session, tg_id)
    if not user:
        return
    if (user.pending_charge_kind or "").strip() != kind:
        return
    await session.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            pending_charge_kind=None,
            pending_charge_source=None,
            pending_charge_amount=0,
            pending_charge_created_at=0,
        )
    )
    await session.commit()


async def charge_photo_generation(
    session: AsyncSession,
    tg_id: int,
    model_key: str = PHOTO_MODEL_KEY,
    credits_override: int | None = None,
) -> ChargeResult:
    credits = (
        int(credits_override)
        if credits_override is not None
        else await get_model_price_credits(session, model_key)
    )
    return await _charge_credits(
        session,
        tg_id=tg_id,
        credits=credits,
        kind="photo",
        model_key=model_key,
    )


async def refund_photo_generation(
    session: AsyncSession, tg_id: int, model_key: str = PHOTO_MODEL_KEY
) -> None:
    del model_key
    await _refund_pending_charge(session, tg_id=tg_id, kind="photo")


async def charge_video_generation(
    session: AsyncSession,
    tg_id: int,
    model_key: str = VIDEO_MODEL_I2V_KEY,
    credits_override: int | None = None,
) -> ChargeResult:
    credits = (
        int(credits_override)
        if credits_override is not None
        else await get_model_price_credits(session, model_key)
    )
    return await _charge_credits(
        session,
        tg_id=tg_id,
        credits=credits,
        kind="video",
        model_key=model_key,
    )


async def refund_video_generation(
    session: AsyncSession, tg_id: int, model_key: str = VIDEO_MODEL_I2V_KEY
) -> None:
    del model_key
    await _refund_pending_charge(session, tg_id=tg_id, kind="video")


async def charge_agent_request(
    session: AsyncSession,
    tg_id: int,
    credits_override: int | None = None,
    prefer_paid: bool = False,
) -> ChargeResult:
    user = await _get_user(session, tg_id)
    if not user:
        raise NoGenerationsLeft()

    now_ts = int(_utcnow().timestamp())
    if _pending_charge_exists(user):
        if _pending_charge_is_stale(user, now_ts=now_ts):
            await _refund_pending_charge(
                session,
                tg_id=tg_id,
                kind=(user.pending_charge_kind or "").strip(),
            )
            user = await _get_user(session, tg_id)
            if not user:
                raise NoGenerationsLeft()
        else:
            raise PendingGenerationInProgressError(
                f"Pending generation already in progress for tg_id={tg_id}"
            )

    credits = (
        int(credits_override)
        if credits_override is not None
        else await get_model_price_credits(session, AGENT_MODEL_KEY)
    )
    if prefer_paid and _has_enough_agent_balance(user, credits=credits):
        return await _charge_credits(
            session,
            tg_id=tg_id,
            credits=credits,
            kind="agent",
            model_key=AGENT_MODEL_KEY,
        )

    free_limit = await get_agent_daily_free_limit(session)
    current_free_used = _daily_free_agent_count_for_user(user)
    if int(free_limit) > 0 and current_free_used < int(free_limit):
        updated = await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                pending_charge_kind="agent",
                pending_charge_source=CHARGE_SOURCE_DAILY_FREE,
                pending_charge_amount=1,
                pending_charge_created_at=now_ts,
                free_agent_requests_day=_msk_today_key(),
                free_agent_requests_used_today=current_free_used + 1,
            )
        )
        if updated.rowcount != 1:
            raise NoGenerationsLeft()
        await session.commit()
        return ChargeResult(
            kind="agent",
            source=CHARGE_SOURCE_DAILY_FREE,
            amount=0,
            model_key=AGENT_MODEL_KEY,
        )

    return await _charge_credits(
        session,
        tg_id=tg_id,
        credits=credits,
        kind="agent",
        model_key=AGENT_MODEL_KEY,
    )


async def refund_agent_request(
    session: AsyncSession, tg_id: int, model_key: str = AGENT_MODEL_KEY
) -> None:
    del model_key
    await _refund_pending_charge(session, tg_id=tg_id, kind="agent")


async def settle_photo_generation_outcome(
    session: AsyncSession,
    tg_id: int,
    *,
    delivered: bool,
    model_key: str = PHOTO_MODEL_KEY,
) -> None:
    if delivered:
        await finalize_photo_generation(session, tg_id)
    else:
        await refund_photo_generation(session, tg_id, model_key=model_key)


async def settle_video_generation_outcome(
    session: AsyncSession,
    tg_id: int,
    *,
    delivered: bool,
    model_key: str = VIDEO_MODEL_I2V_KEY,
) -> None:
    if delivered:
        await finalize_video_generation(session, tg_id)
    else:
        await refund_video_generation(session, tg_id, model_key=model_key)


async def finalize_agent_request(session: AsyncSession, tg_id: int) -> None:
    await _finalize_pending_charge(session, tg_id=tg_id, kind="agent")


async def grant_photo_generation(session: AsyncSession, tg_id: int, delta: int = 1) -> None:
    price = await get_model_price_credits(session, PHOTO_MODEL_KEY)
    user = await _get_user(session, tg_id)
    if not user:
        return
    await session.execute(
        update(User)
        .where(User.id == user.id)
        .values(free_credit_balance=User.free_credit_balance + price * max(0, int(delta)))
    )
    await session.commit()


async def grant_video_generation(session: AsyncSession, tg_id: int, delta: int = 1) -> None:
    price = await get_model_price_credits(session, VIDEO_MODEL_I2V_KEY)
    user = await _get_user(session, tg_id)
    if not user:
        return
    await session.execute(
        update(User)
        .where(User.id == user.id)
        .values(free_credit_balance=User.free_credit_balance + price * max(0, int(delta)))
    )
    await session.commit()


async def finalize_photo_generation(session: AsyncSession, tg_id: int) -> None:
    await _finalize_pending_charge(session, tg_id=tg_id, kind="photo")


async def finalize_video_generation(session: AsyncSession, tg_id: int) -> None:
    await _finalize_pending_charge(session, tg_id=tg_id, kind="video")
