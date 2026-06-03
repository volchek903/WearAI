from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_message import AgentMessage


async def add_agent_message(
    session: AsyncSession,
    *,
    user_id: int,
    role: str,
    content: str,
) -> AgentMessage:
    message = AgentMessage(user_id=user_id, role=role, content=content)
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message


async def list_recent_agent_messages(
    session: AsyncSession,
    *,
    user_id: int,
    limit: int,
) -> list[AgentMessage]:
    rows = (
        await session.execute(
            select(AgentMessage)
            .where(AgentMessage.user_id == user_id)
            .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
            .limit(max(1, int(limit)))
        )
    ).scalars().all()
    return list(reversed(rows))


async def clear_agent_messages(session: AsyncSession, *, user_id: int) -> None:
    await session.execute(delete(AgentMessage).where(AgentMessage.user_id == user_id))
    await session.commit()
