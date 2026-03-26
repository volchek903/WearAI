from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.config import get_database_url


def create_engine():
    # echo=True можно включить на отладку
    db_url = get_database_url()
    connect_args = {}
    if db_url.startswith("sqlite+aiosqlite://"):
        # wait a bit longer on write locks instead of failing fast
        connect_args = {"timeout": 30}

    engine = create_async_engine(
        db_url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )

    if db_url.startswith("sqlite+aiosqlite://"):

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record) -> None:
            cur = dbapi_conn.cursor()
            # Better concurrent read/write characteristics for bot workloads.
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA temp_store=MEMORY")
            cur.execute("PRAGMA cache_size=-20000")  # ~20MB page cache
            cur.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
            cur.close()

    return engine
