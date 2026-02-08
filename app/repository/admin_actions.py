from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_action_log import AdminActionLog
from app.models.user import User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def log_admin_action(
    session: AsyncSession,
    *,
    tg_id: int,
    action: str,
    data: str | None = None,
) -> None:
    user_id = await session.scalar(select(User.id).where(User.tg_id == tg_id))
    if not user_id:
        return
    session.add(
        AdminActionLog(
            user_id=int(user_id),
            tg_id=tg_id,
            action=action,
            data=(data or "")[:1024] if data else None,
        )
    )
    await session.commit()


async def cleanup_admin_actions(session: AsyncSession, *, days: int = 30) -> int:
    cutoff = _utcnow() - timedelta(days=days)
    result = await session.execute(
        delete(AdminActionLog).where(AdminActionLog.created_at < cutoff)
    )
    await session.commit()
    return int(result.rowcount or 0)
