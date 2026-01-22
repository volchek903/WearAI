from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.photo_defaults import DEFAULT_PHOTO_SETTINGS
from app.models.user_photo_settings import UserPhotoSettings


async def get_photo_settings(
    session: AsyncSession, user_id: int
) -> UserPhotoSettings | None:
    return await session.scalar(
        select(UserPhotoSettings).where(UserPhotoSettings.user_id == user_id)
    )


async def ensure_photo_settings(
    session: AsyncSession, user_id: int
) -> UserPhotoSettings:
    s = await get_photo_settings(session, user_id)
    if s is not None:
        return s

    s = UserPhotoSettings(
        user_id=user_id,
        aspect_ratio=DEFAULT_PHOTO_SETTINGS.aspect_ratio,
        resolution=DEFAULT_PHOTO_SETTINGS.resolution,
        output_format=DEFAULT_PHOTO_SETTINGS.output_format,
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return s


async def update_photo_settings(
    session: AsyncSession,
    user_id: int,
    *,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    output_format: str | None = None,
) -> UserPhotoSettings:
    s = await ensure_photo_settings(session, user_id)

    if aspect_ratio is not None:
        s.aspect_ratio = aspect_ratio
    if resolution is not None:
        s.resolution = resolution
    if output_format is not None:
        s.output_format = output_format

    await session.commit()
    await session.refresh(s)
    return s


async def reset_photo_settings(
    session: AsyncSession, user_id: int
) -> UserPhotoSettings:
    return await update_photo_settings(
        session,
        user_id,
        aspect_ratio=DEFAULT_PHOTO_SETTINGS.aspect_ratio,
        resolution=DEFAULT_PHOTO_SETTINGS.resolution,
        output_format=DEFAULT_PHOTO_SETTINGS.output_format,
    )
