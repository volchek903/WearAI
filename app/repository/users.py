from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

logger = logging.getLogger(__name__)


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
            credit_balance=0,
            free_credit_balance=0,
            free_generations_used_today=0,
            free_generations_day=None,
            free_agent_requests_used_today=0,
            free_agent_requests_day=None,
            pending_charge_kind=None,
            pending_charge_source=None,
            pending_charge_amount=0,
            pending_charge_created_at=0,
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
            credit_balance=0,
            free_credit_balance=0,
            free_generations_used_today=0,
            free_generations_day=None,
            free_agent_requests_used_today=0,
            free_agent_requests_day=None,
            pending_charge_kind=None,
            pending_charge_source=None,
            pending_charge_amount=0,
            pending_charge_created_at=0,
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
    session: AsyncSession, tg_id: int, delta: int = 1, section: str | None = None
) -> None:
    from app.repository.analytics import log_generation_event
    from app.repository.generations import finalize_photo_generation

    await finalize_photo_generation(session, tg_id)
    try:
        await session.execute(
            update(User)
            .where(User.tg_id == tg_id)
            .values(generated_photos=User.generated_photos + delta)
        )
        await session.commit()
    except Exception:
        logger.exception("Failed to increment generated_photos for tg_id=%s", tg_id)

    if delta > 0 and section:
        try:
            await log_generation_event(session, tg_id=tg_id, section=section, kind="photo")
        except Exception:
            logger.exception(
                "Failed to log photo generation analytics for tg_id=%s section=%s",
                tg_id,
                section,
            )


async def increment_generated_videos(
    session: AsyncSession, tg_id: int, delta: int = 1, section: str | None = None
) -> None:
    from app.repository.analytics import log_generation_event
    from app.repository.generations import finalize_video_generation

    await finalize_video_generation(session, tg_id)
    try:
        await session.execute(
            update(User)
            .where(User.tg_id == tg_id)
            .values(generated_videos=User.generated_videos + delta)
        )
        await session.commit()
    except Exception:
        logger.exception("Failed to increment generated_videos for tg_id=%s", tg_id)

    if delta > 0 and section:
        try:
            await log_generation_event(session, tg_id=tg_id, section=section, kind="video")
        except Exception:
            logger.exception(
                "Failed to log video generation analytics for tg_id=%s section=%s",
                tg_id,
                section,
            )


async def increment_generated_music(
    session: AsyncSession, tg_id: int, delta: int = 1, section: str | None = None
) -> None:
    from app.repository.analytics import log_generation_event
    from app.repository.generations import finalize_video_generation

    await finalize_video_generation(session, tg_id)
    if delta > 0 and section:
        try:
            for _ in range(int(delta)):
                await log_generation_event(session, tg_id=tg_id, section=section, kind="music")
        except Exception:
            logger.exception(
                "Failed to log music generation analytics for tg_id=%s section=%s",
                tg_id,
                section,
            )
