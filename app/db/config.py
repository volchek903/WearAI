from __future__ import annotations

import os


def get_database_url() -> str:
    # Пример: sqlite+aiosqlite:///./wearai.db
    # Можно переопределить в .env: DATABASE_URL="sqlite+aiosqlite:///./wearai.db"
    return os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./wearai.db")
