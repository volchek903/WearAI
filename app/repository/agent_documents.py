from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_document import AgentDocument


async def add_agent_document(
    session: AsyncSession,
    *,
    user_id: int,
    session_key: str,
    telegram_file_id: str,
    file_name: str | None,
    mime_type: str | None,
    extracted_text: str,
) -> AgentDocument:
    doc = AgentDocument(
        user_id=user_id,
        session_key=session_key,
        telegram_file_id=telegram_file_id,
        file_name=file_name,
        mime_type=mime_type,
        extracted_text=extracted_text,
        text_length=len(extracted_text or ""),
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc


async def list_agent_documents(
    session: AsyncSession,
    *,
    user_id: int,
    session_key: str,
    limit: int = 20,
) -> list[AgentDocument]:
    return (
        await session.execute(
            select(AgentDocument)
            .where(
                AgentDocument.user_id == user_id,
                AgentDocument.session_key == session_key,
            )
            .order_by(AgentDocument.created_at.asc(), AgentDocument.id.asc())
            .limit(max(1, int(limit)))
        )
    ).scalars().all()


async def count_agent_documents(
    session: AsyncSession,
    *,
    user_id: int,
    session_key: str,
) -> int:
    value = await session.scalar(
        select(func.count(AgentDocument.id)).where(
            AgentDocument.user_id == user_id,
            AgentDocument.session_key == session_key,
        )
    )
    return int(value or 0)
