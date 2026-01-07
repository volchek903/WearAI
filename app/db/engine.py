from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine

from app.db.config import get_database_url


def create_engine():
    # echo=True можно включить на отладку
    return create_async_engine(get_database_url(), echo=False, future=True)
