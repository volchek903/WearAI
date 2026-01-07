from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from app.db.init_db import init_db

from app.db import engine, session_factory
from app.middlewares import DbSessionMiddleware, UserActionLogMiddleware
from app.handlers.start import router as start_router
from app.handlers.help import router as help_router
from app.handlers.scenario_model import router as model_router
from app.handlers.scenario_tryon import router as tryon_router


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_bot_token() -> str:
    token = "7998511134:AAFuWlxM9P5q3_HowJOkh9Tv11CgfuR9gBE"
    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not set. Put it into .env or export BOT_TOKEN=..."
        )
    return token


def setup_routers(dp: Dispatcher) -> None:
    dp.include_router(start_router)
    dp.include_router(model_router)
    dp.include_router(tryon_router)
    dp.include_router(help_router)


def setup_middlewares(dp: Dispatcher) -> None:
    # логирование действий пользователя
    dp.update.outer_middleware(UserActionLogMiddleware())
    # сессия БД в хендлеры как параметр session: AsyncSession
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

    # важно: создаём таблицы, если их ещё нет
    await init_db()

    try:
        log.info("Bot started. Polling...")
        await dp.start_polling(bot)
    finally:
        await engine.dispose()
        log.info("Shutdown OK: DB engine disposed.")


if __name__ == "__main__":
    asyncio.run(main())
