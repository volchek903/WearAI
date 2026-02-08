from __future__ import annotations

import asyncio
import logging

from app.db import session_factory
from app.repository.admin_actions import cleanup_admin_actions

logger = logging.getLogger(__name__)


async def run_admin_log_cleanup(*, interval_sec: int = 24 * 60 * 60) -> None:
    logger.info("admin_log_cleanup: started interval_sec=%s", interval_sec)
    while True:
        try:
            async with session_factory() as session:
                deleted = await cleanup_admin_actions(session, days=30)
                if deleted:
                    logger.info("admin_log_cleanup: deleted=%s", deleted)
        except Exception:
            logger.exception("admin_log_cleanup: failed")
        await asyncio.sleep(interval_sec)
