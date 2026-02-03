from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.user import User
from app.repository.users import upsert_user

logger = logging.getLogger(__name__)


async def ensure_root_admin(session: AsyncSession, tg_id: int = 830091750) -> None:
    user = await upsert_user(session, tg_id=tg_id, username=None)
    exists = await session.scalar(select(Admin.id).where(Admin.user_id == user.id))
    if exists:
        return

    session.add(Admin(user_id=user.id))
    await session.commit()
    logger.info("admin_seed: root admin ensured tg_id=%s user_id=%s", tg_id, user.id)
