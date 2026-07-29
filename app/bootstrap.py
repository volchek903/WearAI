from __future__ import annotations

import logging

from app.db.init_db import init_db
from app.repository.app_settings import ensure_model_pricing_settings
from app.services.admin_seed import ensure_root_admin
from app.services.subscription_seed import seed_subscriptions


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def initialize_application_state(session) -> None:
    await init_db()
    await seed_subscriptions(session)
    await ensure_model_pricing_settings(session)
    await ensure_root_admin(session)
