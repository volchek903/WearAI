from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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
        stmt = sqlite_insert(User).values(
            tg_id=tg_id,
            username=username,
            generated_photos=0,
            generated_videos=0,
            free_channel_bonus_used=False,
            free_channel_bonus_pending=False,
            free_channel_reminder_sent=False,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["tg_id"])
        await session.execute(stmt)
        await session.commit()
        user = await get_user_by_tg_id(session, tg_id)
        if user is None:
            # Fallback: should not happen, but keep safe.
            raise RuntimeError("upsert_user: failed to create or fetch user")

    if username is not None and user.username != username:
        user.username = username
        await session.commit()
        await session.refresh(user)

    return user


async def get_or_create_user(
    session: AsyncSession, tg_id: int, username: Optional[str] = None
) -> tuple[User, bool]:
    user = await get_user_by_tg_id(session, tg_id)
    created = False
    if user is None:
        stmt = sqlite_insert(User).values(
            tg_id=tg_id,
            username=username,
            generated_photos=0,
            generated_videos=0,
            free_channel_bonus_used=False,
            free_channel_bonus_pending=False,
            free_channel_reminder_sent=False,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["tg_id"])
        result = await session.execute(stmt)
        await session.commit()
        user = await get_user_by_tg_id(session, tg_id)
        if user is None:
            raise RuntimeError("get_or_create_user: failed to create or fetch user")
        created = result.rowcount == 1

    if username is not None and user.username != username:
        user.username = username
        await session.commit()
        await session.refresh(user)

    return user, created

async def increment_generated_photos(
    session: AsyncSession, tg_id: int, delta: int = 1
) -> None:
    await session.execute(
        update(User)
        .where(User.tg_id == tg_id)
        .values(generated_photos=User.generated_photos + delta)
    )
    await session.commit()


async def increment_generated_videos(
    session: AsyncSession, tg_id: int, delta: int = 1
) -> None:
    await session.execute(
        update(User)
        .where(User.tg_id == tg_id)
        .values(generated_videos=User.generated_videos + delta)
    )
    await session.commit()
