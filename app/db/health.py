from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ping_db(session: AsyncSession) -> None:
    await session.execute(text("SELECT 1"))
