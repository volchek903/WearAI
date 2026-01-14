from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Optional

try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    # если python-dotenv не установлен — просто читаем из окружения
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    kie_api_key: str
    database_url: str
    log_level: str = "INFO"


def _getenv(name: str, default: Optional[str] = None) -> str:
    val = os.getenv(name, default)
    if val is None:
        return ""
    return val.strip()


def load_settings() -> Settings:
    bot_token = _getenv("BOT_TOKEN")
    kie_api_key = _getenv("KIE_API_KEY")
    database_url = _getenv("DATABASE_URL", "sqlite+aiosqlite:///./wearai.db")
    log_level = _getenv("LOG_LEVEL", "INFO")
    missing = []
    if not bot_token:
        missing.append("BOT_TOKEN")
    if not kie_api_key:
        missing.append("KIE_API_KEY")
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
    return Settings(
        bot_token=bot_token,
        kie_api_key=kie_api_key,
        database_url=database_url,
        log_level=log_level,
    )


# удобный singleton, если хотите импортировать settings напрямую
settings = load_settings()


def get_database_url() -> str:
    return settings.database_url
