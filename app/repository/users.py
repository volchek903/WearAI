from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_user_by_tg_id(session: AsyncSession, tg_id: int) -> Optional[User]:
    return await session.scalar(select(User).where(User.tg_id == tg_id))


async def user_exists(session: AsyncSession, tg_id: int) -> bool:
    stmt = select(User.id).where(User.tg_id == tg_id).limit(1)
    return (await session.scalar(stmt)) is not None


async def upsert_user(
    session: AsyncSession, tg_id: int, username: Optional[str] = None
) -> User:
    user = await get_user_by_tg_id(session, tg_id)

    if user is None:
        user = User(tg_id=tg_id, username=username, generated_photos=0)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    if username is not None and user.username != username:
        user.username = username
        await session.commit()
        await session.refresh(user)

    return user


async def get_or_create_user(
    session: AsyncSession, tg_id: int, username: Optional[str] = None
) -> tuple[User, bool]:
    user = await get_user_by_tg_id(session, tg_id)
    if user is None:
        user = User(tg_id=tg_id, username=username, generated_photos=0)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user, True

    if username is not None and user.username != username:
        user.username = username
        await session.commit()
        await session.refresh(user)

    return user, False

async def increment_generated_photos(
    session: AsyncSession, tg_id: int, delta: int = 1
) -> None:
    await session.execute(
        update(User)
        .where(User.tg_id == tg_id)
        .values(generated_photos=User.generated_photos + delta)
    )
    await session.commit()
