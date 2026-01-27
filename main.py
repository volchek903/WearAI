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
from app.handlers.extra import router as extra_router
from app.handlers.admin_access import router as admin_access_router
from app.handlers.referrals import router as referrals_router

from app.services.subscription_seed import seed_subscriptions
from app.services.subscription_expirer import run_subscription_expirer
from app.services.payment_poller import run_payment_poller  # NEW


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
    dp.include_router(extra_router)
    dp.include_router(admin_access_router)
    dp.include_router(referrals_router)
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
    async with session_factory() as session:
        await seed_subscriptions(session)

    # NEW: запускаем polling платежей (без вебхуков)
    poller_task = asyncio.create_task(
        run_payment_poller(
            bot=bot,
            sessionmaker=session_factory,  # у тебя это async_sessionmaker[AsyncSession]
            interval_sec=int(os.getenv("PAYMENTS_POLL_INTERVAL", "20")),
            batch_size=int(os.getenv("PAYMENTS_POLL_BATCH", "50")),
        )
    )
    # NEW: ежедневная проверка просроченных подписок в 00:01 UTC+3
    expirer_task = asyncio.create_task(
        run_subscription_expirer(sessionmaker=session_factory)
    )

    try:
        log.info("Bot started. Polling...")
        await dp.start_polling(bot)
    finally:
        poller_task.cancel()
        expirer_task.cancel()
        try:
            await poller_task
            await expirer_task
        except asyncio.CancelledError:
            pass

        await engine.dispose()
        log.info("Shutdown OK: DB engine disposed.")


if __name__ == "__main__":
    asyncio.run(main())
