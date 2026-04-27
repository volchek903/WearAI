from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repository.app_settings import (
    MODEL_PRICE_KLING_I2V_KEY,
    MODEL_PRICE_KLING_MOTION_KEY,
    MODEL_PRICE_NANO_BANANA_KEY,
    get_launch_daily_limit,
    get_model_price_credits,
)


class NoGenerationsLeft(Exception):
    pass


PHOTO_MODEL_KEY = MODEL_PRICE_NANO_BANANA_KEY
VIDEO_MODEL_I2V_KEY = MODEL_PRICE_KLING_I2V_KEY
VIDEO_MODEL_MOTION_KEY = MODEL_PRICE_KLING_MOTION_KEY

CHARGE_SOURCE_FREE = "free"
CHARGE_SOURCE_PAID = "paid"


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


async def get_launch_used_today(session: AsyncSession) -> int:
    day_key = _msk_today_key()
    result = await session.execute(
        select(User.free_generations_used_today).where(User.free_generations_day == day_key)
    )
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

    day_key = _msk_today_key()
    free_limit = await get_launch_daily_limit(session)
    current_free_used = _daily_free_count_for_user(user)

    can_use_free = (
        int(user.free_credit_balance or 0) >= int(credits)
        and (int(free_limit) <= 0 or current_free_used < int(free_limit))
    )

    if can_use_free:
        await session.execute(
            update(User)
            .where(User.id == user.id, User.free_credit_balance >= int(credits))
            .values(
                free_credit_balance=User.free_credit_balance - int(credits),
                free_generations_day=day_key,
                free_generations_used_today=current_free_used + 1,
                pending_charge_kind=kind,
                pending_charge_source=CHARGE_SOURCE_FREE,
                pending_charge_amount=int(credits),
            )
        )
        await session.commit()
        return ChargeResult(
            kind=kind,
            source=CHARGE_SOURCE_FREE,
            amount=int(credits),
            model_key=model_key,
        )

    updated = await session.execute(
        update(User)
        .where(User.id == user.id, User.credit_balance >= int(credits))
        .values(
            credit_balance=User.credit_balance - int(credits),
            pending_charge_kind=kind,
            pending_charge_source=CHARGE_SOURCE_PAID,
            pending_charge_amount=int(credits),
        )
    )
    if updated.rowcount != 1:
        raise NoGenerationsLeft()

    await session.commit()
    return ChargeResult(
        kind=kind,
        source=CHARGE_SOURCE_PAID,
        amount=int(credits),
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
    pending_source = (user.pending_charge_source or "").strip()
    pending_amount = int(user.pending_charge_amount or 0)
    if pending_kind != kind or pending_amount <= 0:
        return

    values: dict[str, object] = {
        "pending_charge_kind": None,
        "pending_charge_source": None,
        "pending_charge_amount": 0,
    }
    if pending_source == CHARGE_SOURCE_FREE:
        values["free_credit_balance"] = User.free_credit_balance + pending_amount
        if (user.free_generations_day or "") == _msk_today_key():
            values["free_generations_used_today"] = max(
                0, int(user.free_generations_used_today or 0) - 1
            )
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
