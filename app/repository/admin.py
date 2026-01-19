from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.user import User


async def is_admin(session: AsyncSession, tg_id: int) -> bool:
    stmt = (
        select(Admin.id)
        .join(User, User.id == Admin.user_id)
        .where(User.tg_id == tg_id)
        .limit(1)
    )
    return (await session.scalar(stmt)) is not None
