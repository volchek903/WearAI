from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import suppress

from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.payment import PaymentStatus
from app.repository.extra import get_plan
from app.repository.payments import (
    apply_credit_amount_to_user,
    apply_plan_to_user,
    get_payment_by_tx_id,
    mark_payment_status,
    parse_custom_plan_credits,
)

logger = logging.getLogger(__name__)


def _extract_tg_id_from_payload(payload_raw: str | None) -> int | None:
    if not payload_raw:
        return None
    try:
        payload = json.loads(payload_raw)
    except Exception:
        return None
    tg_id = payload.get("tgUserId")
    try:
        return int(tg_id) if tg_id is not None else None
    except Exception:
        return None


async def _handle_platega_callback(
    request: web.Request,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    bot,
) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid json"}, status=400)

    tx_id = str(data.get("id") or "").strip()
    status = str(data.get("status") or "").strip().upper()
    payload_raw = data.get("payload")
    payment_method = data.get("paymentMethod")

    if not tx_id or status not in {"CONFIRMED", "CANCELED"}:
        return web.json_response({"ok": False, "error": "invalid body"}, status=400)

    logger.info(
        "platega_callback: tx_id=%s status=%s method=%s payload=%s",
        tx_id,
        status,
        payment_method,
        payload_raw,
    )

    async with sessionmaker() as session:
        payment = await get_payment_by_tx_id(session, tx_id)
        if not payment:
            logger.warning("platega_callback: payment not found tx_id=%s", tx_id)
            return web.json_response({"ok": True, "ignored": "payment_not_found"})

        if status == "CANCELED":
            if payment.status != PaymentStatus.CANCELED:
                await mark_payment_status(session, payment, PaymentStatus.CANCELED)
            return web.json_response({"ok": True})

        # CONFIRMED
        if payment.status == PaymentStatus.CONFIRMED:
            return web.json_response({"ok": True, "already": True})

        tg_id = int(payment.tg_user_id)
        custom_credits = parse_custom_plan_credits(payment.plan_name)
        credited_amount = 0
        if custom_credits:
            await apply_credit_amount_to_user(session, tg_id, custom_credits)
            credited_amount = custom_credits
        else:
            plan = await get_plan(session, payment.plan_name)
            if not plan:
                logger.error(
                    "platega_callback: plan not found plan_name=%s payment_id=%s tx_id=%s",
                    payment.plan_name,
                    payment.id,
                    tx_id,
                )
                return web.json_response({"ok": False, "error": "plan not found"}, status=500)
            await apply_plan_to_user(session, tg_id, plan)
            credited_amount = int(getattr(plan, "credit_amount", 0) or 0)
        await mark_payment_status(session, payment, PaymentStatus.CONFIRMED)

    # notify user outside db transaction
    with suppress(Exception):
        await bot.send_message(
            tg_id,
            f"✅ Оплата подтверждена! Начислено {credited_amount} кредитов 🎉",
        )

    return web.json_response({"ok": True})


async def run_platega_callback_server(
    *,
    bot,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    enabled = (os.getenv("PLATEGA_CALLBACK_ENABLED") or "1").strip()
    if enabled not in {"1", "true", "TRUE", "yes", "YES"}:
        logger.info("platega_callback: disabled by env")
        await asyncio.Event().wait()
        return

    host = (os.getenv("PLATEGA_CALLBACK_HOST") or "0.0.0.0").strip()
    port = int((os.getenv("PLATEGA_CALLBACK_PORT") or "8081").strip())
    path = (os.getenv("PLATEGA_CALLBACK_PATH") or "/platega/callback").strip()

    app = web.Application()
    app.router.add_post(
        path,
        lambda request: _handle_platega_callback(
            request, sessionmaker=sessionmaker, bot=bot
        ),
    )

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    logger.info("platega_callback: listening on %s:%s%s", host, port, path)

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
