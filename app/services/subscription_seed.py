from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription


PLANS = [
    # name, days, video, photo, price
    ("Launch", 2, 2, 4, 0),
    ("Orbit", 30, 20, 28, 20),
    ("Nova", 30, 100, 84, 59),
    ("Cosmic", 30, 200, 334, 129),
]


async def seed_subscriptions(session: AsyncSession) -> None:
    existing = set((await session.execute(select(Subscription.name))).scalars().all())

    for name, days, video, photo, price in PLANS:
        if name in existing:
            continue

        session.add(
            Subscription(
                name=name,
                duration_days=days,
                video_generations=video,
                photo_generations=photo,
                price=price,
            )
        )

    await session.commit()
