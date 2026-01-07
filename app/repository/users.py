from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_user_by_tg_id(session: AsyncSession, tg_id: int) -> Optional[User]:
    res = await session.execute(select(User).where(User.tg_id == tg_id))
    return res.scalar_one_or_none()


async def upsert_user(
    session: AsyncSession, tg_id: int, username: Optional[str] = None
) -> User:
    """
    Создаём пользователя при /start и в ключевых шагах сценариев.
    Если уже есть — обновляем username и updated_at.
    """
    user = await get_user_by_tg_id(session, tg_id)

    now = datetime.now(timezone.utc)

    if user is None:
        user = User(
            tg_id=tg_id,
            username=username,
            role="user",
            subscription_active=False,
            subscription_until=None,
            generations_left=0,
            generated_photos=0,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    changed = False
    if username is not None and user.username != username:
        user.username = username
        changed = True

    user.updated_at = now
    if changed:
        await session.commit()
    else:
        # даже если username не менялся, updated_at поменяли — фиксируем
        await session.commit()

    await session.refresh(user)
    return user


async def increment_generated_photos(
    session: AsyncSession, tg_id: int, delta: int = 1
) -> None:
    """
    Вызывать в хендлерах 'ОТЛИЧНО' и 'ХОРОШО'
    """
    await session.execute(
        update(User)
        .where(User.tg_id == tg_id)
        .values(generated_photos=User.generated_photos + delta)
    )
    await session.commit()


async def set_subscription(
    session: AsyncSession,
    tg_id: int,
    active: bool,
    until: Optional[datetime],
    generations_left: Optional[int] = None,
) -> None:
    """
    На будущее: админка/оплата/подписка.
    """
    values = {
        "subscription_active": active,
        "subscription_until": until,
    }
    if generations_left is not None:
        values["generations_left"] = generations_left

    await session.execute(update(User).where(User.tg_id == tg_id).values(**values))
    await session.commit()
