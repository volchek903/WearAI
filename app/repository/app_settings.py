from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting


LAUNCH_DAILY_LIMIT_KEY = "launch_daily_limit"


async def get_launch_daily_limit(session: AsyncSession) -> int:
    val = await session.scalar(
        select(AppSetting.int_value).where(AppSetting.key == LAUNCH_DAILY_LIMIT_KEY)
    )
    if val is None:
        session.add(AppSetting(key=LAUNCH_DAILY_LIMIT_KEY, int_value=0))
        await session.commit()
        return 0
    return int(val)


async def set_launch_daily_limit(session: AsyncSession, value: int) -> None:
    value = int(value)
    updated = await session.execute(
        update(AppSetting)
        .where(AppSetting.key == LAUNCH_DAILY_LIMIT_KEY)
        .values(int_value=value)
    )
    if updated.rowcount == 0:
        session.add(AppSetting(key=LAUNCH_DAILY_LIMIT_KEY, int_value=value))
    await session.commit()
