from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription


STAR_USD_RATE = 23.99 / 1000
USD_TO_RUB = 79
RUB_PER_STAR = STAR_USD_RATE * USD_TO_RUB


def _stars_for_rub(rub_amount: int) -> int:
    if rub_amount <= 0:
        return 0
    raw = max(1, round(int(rub_amount) / RUB_PER_STAR))
    return ((raw + 9) // 10) * 10


PLANS = [
    # name, credit_amount, price_rub
    ("Base", 0, 0),
    ("Orbit", 840, 20),
    ("Nova", 4300, 3650),
    ("Cosmic", 13140, 9850),
]


async def seed_subscriptions(session: AsyncSession) -> None:
    existing = set((await session.execute(select(Subscription.name))).scalars().all())

    for name, credit_amount, price in PLANS:
        stars_price = _stars_for_rub(int(price))
        if name in existing:
            plan = await session.scalar(select(Subscription).where(Subscription.name == name))
            if plan is not None:
                plan.credit_amount = int(credit_amount)
                plan.price = price
                plan.stars_price = stars_price
            continue

        session.add(
            Subscription(
                name=name,
                duration_days=0,
                video_generations=0,
                photo_generations=0,
                credit_amount=credit_amount,
                price=price,
                stars_price=stars_price,
            )
        )

    await session.commit()
