from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone, time as dtime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.subscription import Subscription
from app.models.user_subscription import UserSubscription

logger = logging.getLogger(__name__)

# UTC+3
TZ_MSK = timezone(timedelta(hours=3))


def _seconds_until_next_run(now_utc: datetime) -> int:
    """
    Следующий запуск: 00:01 по UTC+3
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    now_msk = now_utc.astimezone(TZ_MSK)
    target_time = dtime(hour=0, minute=1, second=0)

    target_msk = datetime.combine(now_msk.date(), target_time, tzinfo=TZ_MSK)
    if now_msk >= target_msk:
        target_msk = target_msk + timedelta(days=1)

    target_utc = target_msk.astimezone(timezone.utc)
    delta = target_utc - now_utc
    sec = int(delta.total_seconds())
    return max(sec, 1)


async def _get_base_subscription(session: AsyncSession) -> Subscription | None:
    """
    Базовая подписка = план с именем "Base".
    Если его нет — берём самый первый план по id.
    """
    base = await session.scalar(
        select(Subscription).where(Subscription.name == "Base").limit(1)
    )
    if base:
        return base
    logger.warning("subscription_expirer: base plan 'Base' not found, fallback to first")
    return await session.scalar(
        select(Subscription).order_by(Subscription.id.asc()).limit(1)
    )


def _calc_expires_at(now_utc: datetime, plan: Subscription) -> datetime:
    days = int(getattr(plan, "duration_days", 0) or 0)
    if days > 0:
        return now_utc + timedelta(days=days)
    # бессрочно — далеко в будущее
    return now_utc + timedelta(days=365 * 100)


async def expire_subscriptions_once(
    session: AsyncSession, *, batch_size: int = 500
) -> int:
    """
    Один прогон:
    - находим все активные подписки (status=1) у которых expires_at <= now
    - деактивируем (status=0)
    - создаём новую активную базовую подписку
    Возвращает: сколько пользователей обработали
    """
    now_utc = datetime.now(timezone.utc)

    base = await _get_base_subscription(session)
    if not base:
        logger.error("subscription_expirer: base subscription not found in DB")
        return 0

    # берём пачку истёкших активных подписок
    q = await session.execute(
        select(UserSubscription)
        .where(UserSubscription.status == 1)
        .where(UserSubscription.expires_at <= now_utc)
        .order_by(UserSubscription.id.asc())
        .limit(batch_size)
    )
    expired_list = list(q.scalars().all())

    if not expired_list:
        return 0

    logger.info(
        "subscription_expirer: found_expired=%s base_plan=%s",
        len(expired_list),
        base.name,
    )

    expires_base = _calc_expires_at(now_utc, base)

    processed = 0
    for us in expired_list:
        # 1) деактивируем текущую
        us.status = 0

        # 2) выдаём базовую (новой строкой — так сохраняется история)
        session.add(
            UserSubscription(
                user_id=us.user_id,
                subscription_id=base.id,
                expires_at=expires_base,
                remaining_video=int(base.video_generations or 0),
                remaining_photo=int(base.photo_generations or 0),
                status=1,
            )
        )
        processed += 1

    await session.commit()
    logger.info("subscription_expirer: processed=%s committed", processed)
    return processed


async def run_subscription_expirer(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    batch_size: int = 500,
) -> None:
    """
    Бесконечный цикл:
    - ждём до 00:01 UTC+3
    - прогоняем expire_subscriptions_once (в цикле, пока есть пачки)
    - снова ждём до следующего дня
    """
    logger.info("subscription_expirer: started (runs daily at 00:01 UTC+3)")

    while True:
        now_utc = datetime.now(timezone.utc)
        sleep_sec = _seconds_until_next_run(now_utc)

        next_run_utc = now_utc + timedelta(seconds=sleep_sec)
        logger.info(
            "subscription_expirer: next_run_in=%ss at_utc=%s",
            sleep_sec,
            next_run_utc.isoformat(),
        )

        await asyncio.sleep(sleep_sec)

        try:
            total = 0
            async with sessionmaker() as session:
                # если истёкших много — обработаем несколькими пачками
                while True:
                    cnt = await expire_subscriptions_once(
                        session, batch_size=batch_size
                    )
                    total += cnt
                    if cnt < batch_size:
                        break

            logger.info(
                "subscription_expirer: daily_run_done total_processed=%s", total
            )

        except Exception:
            logger.exception("subscription_expirer: error during daily run")
