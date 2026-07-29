from __future__ import annotations

import hashlib
import os
import re
import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repository.agent_settings import ensure_agent_settings, snapshot_agent_settings
from app.repository.users import get_or_create_user

WEB_USERNAME_PREFIX = "web"
TELEGRAM_CLIENT_ID_RE = re.compile(r"^tg-(\d+)$")


def generate_client_id() -> str:
    return uuid.uuid4().hex


def web_tg_id_from_client_id(client_id: str) -> int:
    raw = (client_id or "").strip()
    if not raw:
        raise ValueError("client_id is required")

    match = TELEGRAM_CLIENT_ID_RE.fullmatch(raw)
    if match:
        return int(match.group(1))

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    numeric = int(digest[:15], 16)
    return -1 * max(1, numeric)


async def ensure_web_user(
    session: AsyncSession,
    *,
    client_id: str,
    username: str | None = None,
) -> User:
    tg_id = web_tg_id_from_client_id(client_id)
    user, created = await get_or_create_user(
        session,
        tg_id=tg_id,
        username=username or f"{WEB_USERNAME_PREFIX}_{client_id[:12]}",
    )

    grant = max(0, int(os.getenv("WEB_INITIAL_FREE_CREDITS", "3") or "0"))
    if created and grant > 0:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(free_credit_balance=User.free_credit_balance + grant)
        )
        await session.commit()
        await session.refresh(user)

    return user


async def build_web_profile(
    session: AsyncSession,
    *,
    client_id: str,
    username: str | None = None,
) -> dict[str, object]:
    user = await ensure_web_user(session, client_id=client_id, username=username)
    settings = await ensure_agent_settings(session, user.id)
    snapshot = snapshot_agent_settings(settings)
    return {
        "client_id": client_id,
        "tg_id": user.tg_id,
        "username": user.username,
        "balances": {
            "paid": int(user.credit_balance or 0),
            "free": int(user.free_credit_balance or 0),
            "total": int(user.credit_balance or 0) + int(user.free_credit_balance or 0),
        },
        "usage": {
            "photos": int(user.generated_photos or 0),
            "videos": int(user.generated_videos or 0),
        },
        "agent_settings": {
            "web_search_enabled": bool(snapshot.web_search_enabled),
            "documents_enabled": bool(snapshot.documents_enabled),
            "memory_enabled": bool(snapshot.memory_enabled),
            "deep_analysis_enabled": bool(snapshot.deep_analysis_enabled),
            "quick_mode_enabled": bool(snapshot.quick_mode_enabled),
        },
    }
