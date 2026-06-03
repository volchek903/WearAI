from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_message import AgentMessage
from app.models.user_agent_settings import UserAgentSettings


@dataclass(frozen=True, slots=True)
class AgentToggleState:
    web_search_enabled: bool
    documents_enabled: bool
    memory_enabled: bool
    deep_analysis_enabled: bool
    quick_mode_enabled: bool
    document_session_key: str


def _new_session_key() -> str:
    return uuid4().hex


async def get_agent_settings(
    session: AsyncSession, user_id: int
) -> UserAgentSettings | None:
    return await session.scalar(
        select(UserAgentSettings).where(UserAgentSettings.user_id == user_id)
    )


async def ensure_agent_settings(
    session: AsyncSession, user_id: int
) -> UserAgentSettings:
    settings = await get_agent_settings(session, user_id)
    if settings is not None:
        if not settings.document_session_key:
            settings.document_session_key = _new_session_key()
            await session.commit()
            await session.refresh(settings)
        return settings

    settings = UserAgentSettings(
        user_id=user_id,
        web_search_enabled=False,
        documents_enabled=False,
        memory_enabled=True,
        deep_analysis_enabled=False,
        quick_mode_enabled=False,
        document_session_key=_new_session_key(),
    )
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    return settings


async def toggle_agent_setting(
    session: AsyncSession,
    user_id: int,
    field_name: str,
) -> UserAgentSettings:
    settings = await ensure_agent_settings(session, user_id)
    allowed_fields = {
        "web_search_enabled",
        "documents_enabled",
        "memory_enabled",
        "deep_analysis_enabled",
        "quick_mode_enabled",
    }
    if field_name not in allowed_fields:
        raise KeyError(f"Unknown agent setting field: {field_name}")

    current = bool(getattr(settings, field_name))
    setattr(settings, field_name, not current)
    await session.commit()
    await session.refresh(settings)
    return settings


async def rotate_agent_document_session(
    session: AsyncSession, user_id: int
) -> UserAgentSettings:
    settings = await ensure_agent_settings(session, user_id)
    settings.document_session_key = _new_session_key()
    await session.commit()
    await session.refresh(settings)
    return settings


async def clear_agent_memory(session: AsyncSession, user_id: int) -> None:
    await session.execute(delete(AgentMessage).where(AgentMessage.user_id == user_id))
    await session.commit()


def snapshot_agent_settings(settings: UserAgentSettings) -> AgentToggleState:
    return AgentToggleState(
        web_search_enabled=bool(settings.web_search_enabled),
        documents_enabled=bool(settings.documents_enabled),
        memory_enabled=bool(settings.memory_enabled),
        deep_analysis_enabled=bool(settings.deep_analysis_enabled),
        quick_mode_enabled=bool(settings.quick_mode_enabled),
        document_session_key=str(settings.document_session_key),
    )
