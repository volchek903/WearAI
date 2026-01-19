from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
import os
from app.db.init_db import init_db
from app.db import engine, session_factory
from app.middlewares import DbSessionMiddleware, UserActionLogMiddleware
from app.handlers.faq import router as faq_router
from app.handlers.feedback import router as feedback_router
from app.handlers.start import router as start_router
from app.handlers.scenario_model import router as model_router
from app.handlers.scenario_tryon import router as tryon_router
from app.handlers.help import router as help_router
from app.handlers.settings import router as settings_router
from app.handlers.animate_photo import router as animate_router
from app.handlers.feedback_offer_video import router as feedback_offer_video_router
from app.handlers.admin_panel import router as admin_panel_router


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_bot_token() -> str:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Export it: export BOT_TOKEN='...'")
    return token


def setup_routers(dp: Dispatcher) -> None:
    # ВАЖНО: feedback_router должен быть ПЕРВЫМ,
    # чтобы message-хендлеры FeedbackFlow не перехватывались другими роутерами.
    dp.include_router(feedback_router)

    dp.include_router(start_router)
    dp.include_router(model_router)
    dp.include_router(tryon_router)
    dp.include_router(animate_router)
    dp.include_router(faq_router)
    dp.include_router(feedback_offer_video_router)
    dp.include_router(admin_panel_router)
    # Роутеры с более “общими” хендлерами — ниже
    dp.include_router(help_router)
    dp.include_router(settings_router)


def setup_middlewares(dp: Dispatcher) -> None:
    dp.update.outer_middleware(UserActionLogMiddleware())
    dp.update.outer_middleware(DbSessionMiddleware(session_factory))


async def main() -> None:
    setup_logging()
    log = logging.getLogger(__name__)

    bot = Bot(
        token=get_bot_token(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    setup_middlewares(dp)
    setup_routers(dp)

    await init_db()

    try:
        log.info("Bot started. Polling...")
        await dp.start_polling(bot)
    finally:
        await engine.dispose()
        log.info("Shutdown OK: DB engine disposed.")


if __name__ == "__main__":
    asyncio.run(main())
