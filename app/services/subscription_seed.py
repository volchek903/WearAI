from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription


PLANS = [
    # name, days, video, photo, price_rub, price_stars
    ("Base", 0, 0, 0, 0, 0),
    ("Launch", 2, 1, 1, 0, 0),
    ("Orbit", 30, 20, 28, 750, 500),
    ("Nova", 30, 100, 84, 3650, 3500),
    ("Cosmic", 30, 200, 334, 9850, 9500),
]


async def seed_subscriptions(session: AsyncSession) -> None:
    existing = set((await session.execute(select(Subscription.name))).scalars().all())

    for name, days, video, photo, price, stars_price in PLANS:
        if name in existing:
            continue

        session.add(
            Subscription(
                name=name,
                duration_days=days,
                video_generations=video,
                photo_generations=photo,
                price=price,
                stars_price=stars_price,
            )
        )

    await session.commit()
