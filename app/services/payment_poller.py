# app/services/payment_poller.py
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.payment import PaymentStatus
from app.repository.payments import (
    PaymentAlreadyProcessedError,
    PaymentPlanNotFoundError,
    PaymentUserNotFoundError,
    confirm_payment_and_apply_credits,
    get_pending_payments_batch,
    mark_payment_status,
)
import httpx
from app.services.platega import build_platega_client, normalize_payment_status

logger = logging.getLogger(__name__)


def _payment_tg_id(p) -> int | None:
    """
    В проекте было расхождение имён:
    - в БД колонка: user_tg_id
    - в питоне модель может иметь атрибут: tg_user_id (рекомендовано) или user_tg_id (старое)

    Поэтому берём безопасно через getattr, чтобы не падать в проде.
    """
    return (
        getattr(p, "tg_user_id", None)
        or getattr(p, "user_tg_id", None)
        or getattr(p, "user_tg", None)
    )


async def run_payment_poller(
    *,
    bot: Bot,
    sessionmaker: async_sessionmaker[AsyncSession],
    interval_sec: int = 20,
    batch_size: int = 50,
) -> None:
    """
    Polling подтверждений платежей (без вебхуков):
    - каждые interval_sec секунд берём batch_size платежей со статусом PENDING
    - проверяем в Platega статус транзакции
    - при CONFIRMED: начисляем пакет, помечаем CONFIRMED, уведомляем пользователя
    - при CANCELED/CHARGEBACK: помечаем соответствующий статус
    """
    client = None
    logger.info(
        "payment_poller: started interval_sec=%s batch_size=%s",
        interval_sec,
        batch_size,
    )

    while True:
        try:
            if client is None:
                try:
                    client = build_platega_client()
                except Exception:
                    logger.exception(
                        "payment_poller: platega client init failed (missing env?)"
                    )
                    await asyncio.sleep(interval_sec)
                    continue

            async with sessionmaker() as session:
                pending = await get_pending_payments_batch(session, limit=batch_size)

                if pending:
                    logger.info("payment_poller: pending_count=%s", len(pending))

                for p in pending:
                    try:
                        tg_id = _payment_tg_id(p)
                        if not tg_id:
                            logger.error(
                                "payment_poller: payment has no tg_id field payment_id=%s tx_id=%s attrs=%s",
                                getattr(p, "id", None),
                                getattr(p, "platega_transaction_id", None),
                                sorted(list(getattr(p, "__dict__", {}).keys())),
                            )
                            continue

                        raw_status = await client.get_transaction_status(
                            p.platega_transaction_id
                        )
                        status = normalize_payment_status(raw_status)

                        logger.info(
                            "payment_poller: check payment_id=%s tx_id=%s tg_id=%s raw_status=%s normalized=%s",
                            p.id,
                            p.platega_transaction_id,
                            tg_id,
                            raw_status,
                            status,
                        )

                        if status == "CONFIRMED":
                            try:
                                credited_amount = await confirm_payment_and_apply_credits(
                                    session, p
                                )
                            except PaymentAlreadyProcessedError:
                                logger.info(
                                    "payment_poller: payment already processed payment_id=%s tx_id=%s",
                                    p.id,
                                    p.platega_transaction_id,
                                )
                                continue
                            except (
                                PaymentPlanNotFoundError,
                                PaymentUserNotFoundError,
                            ):
                                logger.exception(
                                    "payment_poller: payment confirmation blocked payment_id=%s tx_id=%s",
                                    p.id,
                                    p.platega_transaction_id,
                                )
                                continue

                            try:
                                await bot.send_message(
                                    tg_id,
                                    f"✅ Оплата подтверждена! Начислено {credited_amount} кредитов 🎉",
                                )
                            except Exception:
                                logger.exception(
                                    "payment_poller: failed to notify tg_user_id=%s payment_id=%s",
                                    tg_id,
                                    p.id,
                                )

                        elif status in {"CANCELED", "CHARGEBACK"}:
                            await mark_payment_status(session, p, PaymentStatus(status))

                        else:
                            # PENDING / None / неизвестно — ничего не делаем
                            pass

                    except (httpx.TimeoutException, httpx.ConnectError):
                        logger.warning(
                            "payment_poller: timeout while processing payment_id=%s tx_id=%s",
                            getattr(p, "id", None),
                            getattr(p, "platega_transaction_id", None),
                        )
                    except Exception:
                        logger.exception(
                            "payment_poller: error while processing payment_id=%s tx_id=%s",
                            getattr(p, "id", None),
                            getattr(p, "platega_transaction_id", None),
                        )

        except Exception:
            logger.exception("payment_poller: loop error (session/batch)")

        await asyncio.sleep(interval_sec)
