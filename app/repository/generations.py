# app/repository/generations.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription
from app.models.user import User
from app.models.user_subscription import UserSubscription


class NoGenerationsLeft(Exception):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _get_user_db_id(session: AsyncSession, tg_id: int) -> int | None:
    user_id = await session.scalar(select(User.id).where(User.tg_id == tg_id))
    return int(user_id) if user_id is not None else None


async def _get_active_us_id(session: AsyncSession, user_id: int) -> int | None:
    us_id = await session.scalar(
        select(UserSubscription.id)
        .where(UserSubscription.user_id == user_id, UserSubscription.status == 1)
        .order_by(UserSubscription.activated_at.desc())
        .limit(1)
    )
    return int(us_id) if us_id is not None else None


async def ensure_default_subscription(session: AsyncSession, tg_id: int) -> None:
    user_id = await _get_user_db_id(session, tg_id)

    print(f"[DEBUG ensure_default_subscription] tg_id={tg_id} -> user_id={user_id}")

    if not user_id:
        print(f"[DEBUG ensure_default_subscription] FAIL: no user for tg_id={tg_id}")
        return

    active_id = await _get_active_us_id(session, user_id)
    print(
        f"[DEBUG ensure_default_subscription] user_id={user_id} active_us_id={active_id}"
    )
    if active_id:
        return

    sub = await session.scalar(
        select(Subscription).where(Subscription.name == "Base").limit(1)
    )
    if not sub:
        sub = await session.scalar(
            select(Subscription).order_by(Subscription.id.asc()).limit(1)
        )
    print(
        f"[DEBUG ensure_default_subscription] picked sub="
        f"{getattr(sub, 'id', None)} {getattr(sub, 'name', None)}"
    )
    if not sub:
        return

    now = _utcnow()

    # duration_days<=0 трактуем как "без срока" (очень далеко)
    if int(sub.duration_days) <= 0:
        expires = now + timedelta(days=365 * 100)  # 100 лет
    else:
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

    print(
        "[DEBUG ensure_default_subscription] CREATED default sub "
        f"user_id={user_id} sub_id={sub.id} expires_at={expires.isoformat()} "
        f"photo={int(sub.photo_generations)} video={int(sub.video_generations)}"
    )


async def charge_photo_generation(session: AsyncSession, tg_id: int) -> None:
    now = _utcnow()
    user_id = await _get_user_db_id(session, tg_id)
    print(
        f"[DEBUG charge_photo] tg_id={tg_id} -> user_id={user_id} now_utc={now.isoformat()}"
    )

    if not user_id:
        print("[DEBUG charge_photo] FAIL: user not found")
        raise NoGenerationsLeft()

    us_id = await _get_active_us_id(session, user_id)
    print(f"[DEBUG charge_photo] active_us_id={us_id}")

    if not us_id:
        print("[DEBUG charge_photo] FAIL: no active subscription")
        raise NoGenerationsLeft()

    before = await session.scalar(
        select(UserSubscription.remaining_photo, UserSubscription.expires_at).where(
            UserSubscription.id == us_id
        )
    )
    print(f"[DEBUG charge_photo] before (remaining_photo, expires_at) = {before}")

    new_left = await session.scalar(
        update(UserSubscription)
        .where(
            UserSubscription.id == us_id,
            UserSubscription.status == 1,
            UserSubscription.remaining_photo > 0,
            UserSubscription.expires_at > now,
        )
        .values(remaining_photo=UserSubscription.remaining_photo - 1)
        .returning(UserSubscription.remaining_photo)
    )
    print(f"[DEBUG charge_photo] update returning new_left={new_left}")

    if new_left is None:
        cur = await session.scalar(
            select(
                UserSubscription.remaining_photo,
                UserSubscription.remaining_video,
                UserSubscription.expires_at,
                UserSubscription.status,
            ).where(UserSubscription.id == us_id)
        )
        print(f"[DEBUG charge_photo] FAIL cur row={cur}")
        raise NoGenerationsLeft()

    await session.commit()
    print(f"[DEBUG charge_photo] COMMIT OK new_left={new_left}")


async def refund_photo_generation(session: AsyncSession, tg_id: int) -> None:
    user_id = await _get_user_db_id(session, tg_id)
    print(f"[DEBUG refund_photo] tg_id={tg_id} -> user_id={user_id}")

    if not user_id:
        return

    us_id = await _get_active_us_id(session, user_id)
    print(f"[DEBUG refund_photo] active_us_id={us_id}")
    if not us_id:
        return

    await session.execute(
        update(UserSubscription)
        .where(UserSubscription.id == us_id, UserSubscription.status == 1)
        .values(remaining_photo=UserSubscription.remaining_photo + 1)
    )
    await session.commit()
    print("[DEBUG refund_photo] COMMIT OK +1")


async def charge_video_generation(session: AsyncSession, tg_id: int) -> None:
    now = _utcnow()
    user_id = await _get_user_db_id(session, tg_id)
    print(
        f"[DEBUG charge_video] tg_id={tg_id} -> user_id={user_id} now_utc={now.isoformat()}"
    )

    if not user_id:
        print("[DEBUG charge_video] FAIL: user not found")
        raise NoGenerationsLeft()

    us_id = await _get_active_us_id(session, user_id)
    print(f"[DEBUG charge_video] active_us_id={us_id}")

    if not us_id:
        print("[DEBUG charge_video] FAIL: no active subscription")
        raise NoGenerationsLeft()

    before = await session.scalar(
        select(UserSubscription.remaining_video, UserSubscription.expires_at).where(
            UserSubscription.id == us_id
        )
    )
    print(f"[DEBUG charge_video] before (remaining_video, expires_at) = {before}")

    new_left = await session.scalar(
        update(UserSubscription)
        .where(
            UserSubscription.id == us_id,
            UserSubscription.status == 1,
            UserSubscription.remaining_video > 0,
            UserSubscription.expires_at > now,
        )
        .values(remaining_video=UserSubscription.remaining_video - 1)
        .returning(UserSubscription.remaining_video)
    )
    print(f"[DEBUG charge_video] update returning new_left={new_left}")

    if new_left is None:
        cur = await session.scalar(
            select(
                UserSubscription.remaining_photo,
                UserSubscription.remaining_video,
                UserSubscription.expires_at,
                UserSubscription.status,
            ).where(UserSubscription.id == us_id)
        )
        print(f"[DEBUG charge_video] FAIL cur row={cur}")
        raise NoGenerationsLeft()

    await session.commit()
    print(f"[DEBUG charge_video] COMMIT OK new_left={new_left}")


async def refund_video_generation(session: AsyncSession, tg_id: int) -> None:
    user_id = await _get_user_db_id(session, tg_id)
    print(f"[DEBUG refund_video] tg_id={tg_id} -> user_id={user_id}")

    if not user_id:
        return

    us_id = await _get_active_us_id(session, user_id)
    print(f"[DEBUG refund_video] active_us_id={us_id}")
    if not us_id:
        return

    await session.execute(
        update(UserSubscription)
        .where(UserSubscription.id == us_id, UserSubscription.status == 1)
        .values(remaining_video=UserSubscription.remaining_video + 1)
    )
    await session.commit()
    print("[DEBUG refund_video] COMMIT OK +1")
