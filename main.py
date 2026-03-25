from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from urllib.parse import quote
from urllib.parse import urlsplit

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.session.aiohttp import AiohttpSession

from app.db.init_db import init_db
from app.db import engine, session_factory
from app.middlewares import DbSessionMiddleware, UserActionLogMiddleware

from app.handlers.faq import router as faq_router
from app.handlers.feedback import router as feedback_router
from app.handlers.start import router as start_router
from app.handlers.scenario_model import router as model_router
from app.handlers.nano_banana import router as nano_banana_router
from app.handlers.drift_heart import router as drift_heart_router
from app.handlers.rear_view_mirror import router as rear_view_mirror_router
from app.handlers.motion_control import router as motion_control_router
from app.handlers.car_in_hand import router as car_in_hand_router
from app.handlers.scenario_tryon import router as tryon_router
from app.handlers.settings import router as settings_router
from app.handlers.animate_photo import router as animate_router
from app.handlers.menu import router as menu_router
from app.handlers.love_is import router as love_is_router
from app.handlers.disney_family_heart import router as disney_family_heart_router
from app.handlers.disney_family_wall import router as disney_family_wall_router
from app.handlers.radar import router as radar_router
from app.handlers.feb23 import router as feb23_router
from app.handlers.march8 import router as march8_router
from app.handlers.main_defender import router as main_defender_router
from app.handlers.cinema_bw import router as cinema_bw_router
from app.handlers.second_life import router as second_life_router
from app.handlers.gta_style import router as gta_style_router
from app.handlers.lego_style import router as lego_style_router
from app.handlers.sims_style import router as sims_style_router
from app.handlers.glam_collage import router as glam_collage_router
from app.handlers.feedback_offer_video import router as feedback_offer_video_router
from app.handlers.admin_panel import router as admin_panel_router
from app.handlers.admin_broadcast import router as admin_broadcast_router
from app.handlers.extra import router as extra_router
from app.handlers.admin_access import router as admin_access_router
from app.handlers.referrals import router as referrals_router
from app.handlers.errors import router as errors_router

from app.services.subscription_seed import seed_subscriptions
from app.services.subscription_expirer import run_subscription_expirer
from app.services.payment_poller import run_payment_poller  # NEW
from app.services.admin_log_cleanup import run_admin_log_cleanup
from app.services.platega_callback import run_platega_callback_server
from app.utils.tg_logging import install_tg_error_logging
from app.services.admin_seed import ensure_root_admin
from app.repository.app_settings import ensure_model_pricing_settings


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


def _secret_fingerprint(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return "empty"
    digest = hashlib.sha256(v.encode("utf-8")).hexdigest()[:10]
    return f"len={len(v)} sha256[:10]={digest}"


def _build_proxy_url() -> str | None:
    # Preferred: full URL, e.g. http://user:pass@host:port or socks5://...
    raw_url = (os.getenv("PROXY_URL") or "").strip()
    if raw_url:
        return raw_url

    # Legacy compact format: host:port:user:password
    compact = (os.getenv("BOT_PROXY") or "").strip()
    if not compact:
        return None
    parts = compact.split(":")
    if len(parts) == 4:
        host, port, user, password = parts
        user_enc = quote(user, safe="")
        pass_enc = quote(password, safe="")
        return f"http://{user_enc}:{pass_enc}@{host}:{port}"
    if len(parts) == 2:
        host, port = parts
        return f"http://{host}:{port}"
    return None


def _proxy_log_view(proxy_url: str) -> str:
    try:
        parsed = urlsplit(proxy_url)
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        user = f"{parsed.username}@" if parsed.username else ""
        scheme = parsed.scheme or "http"
        return f"{scheme}://{user}{host}{port}"
    except Exception:
        return "<invalid-proxy-url>"


def setup_routers(dp: Dispatcher) -> None:
    # ВАЖНО: feedback_router должен быть ПЕРВЫМ,
    # чтобы message-хендлеры FeedbackFlow не перехватывались другими роутерами.
    dp.include_router(feedback_router)

    dp.include_router(start_router)
    dp.include_router(menu_router)
    dp.include_router(model_router)
    dp.include_router(nano_banana_router)
    dp.include_router(drift_heart_router)
    dp.include_router(rear_view_mirror_router)
    dp.include_router(motion_control_router)
    dp.include_router(car_in_hand_router)
    dp.include_router(tryon_router)
    dp.include_router(love_is_router)
    dp.include_router(disney_family_heart_router)
    dp.include_router(disney_family_wall_router)
    dp.include_router(feb23_router)
    dp.include_router(march8_router)
    dp.include_router(main_defender_router)
    dp.include_router(cinema_bw_router)
    dp.include_router(second_life_router)
    dp.include_router(radar_router)
    dp.include_router(gta_style_router)
    dp.include_router(lego_style_router)
    dp.include_router(sims_style_router)
    dp.include_router(glam_collage_router)
    dp.include_router(animate_router)
    dp.include_router(faq_router)
    dp.include_router(feedback_offer_video_router)
    dp.include_router(admin_panel_router)
    dp.include_router(admin_broadcast_router)
    dp.include_router(extra_router)
    dp.include_router(admin_access_router)
    dp.include_router(referrals_router)
    # Роутеры с более “общими” хендлерами — ниже
    dp.include_router(settings_router)
    dp.include_router(errors_router)


def setup_middlewares(dp: Dispatcher) -> None:
    dp.update.outer_middleware(UserActionLogMiddleware())
    dp.update.outer_middleware(DbSessionMiddleware(session_factory))


async def main() -> None:
    setup_logging()
    log = logging.getLogger(__name__)
    wavespeed_key = os.getenv("WAVESPEED_API_KEY", "").strip() or os.getenv("KIE_API_KEY", "").strip()
    log.info("startup: wavespeed_api_key_fingerprint=%s", _secret_fingerprint(wavespeed_key))

    proxy_url = _build_proxy_url()
    if proxy_url:
        log.info("startup: telegram proxy enabled (%s)", _proxy_log_view(proxy_url))
        try:
            bot_session = AiohttpSession(proxy=proxy_url)
            bot = Bot(
                token=get_bot_token(),
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
                session=bot_session,
            )
        except RuntimeError as e:
            log.warning(
                "startup: proxy init failed, fallback to direct connection: %s", e
            )
            bot = Bot(
                token=get_bot_token(),
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
    else:
        bot = Bot(
            token=get_bot_token(),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    install_tg_error_logging(bot=bot, chat_id=830091750)

    dp = Dispatcher(storage=MemoryStorage())

    setup_middlewares(dp)
    setup_routers(dp)

    await init_db()
    async with session_factory() as session:
        await seed_subscriptions(session)
        await ensure_model_pricing_settings(session)
        await ensure_root_admin(session)

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
    admin_log_cleanup_task = asyncio.create_task(run_admin_log_cleanup())
    platega_callback_task = asyncio.create_task(
        run_platega_callback_server(
            bot=bot,
            sessionmaker=session_factory,
        )
    )

    try:
        log.info("Bot started. Polling...")
        await dp.start_polling(bot)
    finally:
        poller_task.cancel()
        expirer_task.cancel()
        admin_log_cleanup_task.cancel()
        platega_callback_task.cancel()
        try:
            await poller_task
            await expirer_task
            await admin_log_cleanup_task
            await platega_callback_task
        except asyncio.CancelledError:
            pass

        await engine.dispose()
        log.info("Shutdown OK: DB engine disposed.")


if __name__ == "__main__":
    asyncio.run(main())
