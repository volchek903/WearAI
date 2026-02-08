# app/handlers/start.py
from __future__ import annotations

import os
import logging

import httpx
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.menu import main_menu_kb, MenuCallbacks
from app.keyboards.help import help_choose_kb
from app.repository.users import get_or_create_user
from app.repository.referrals import parse_referrer_tg_id, process_referral_for_new_user
from app.repository.photo_settings import ensure_photo_settings
from app.repository.generations import ensure_default_subscription
from app.services.free_channel_bonus import schedule_free_bonus_reminder
from app.repository.extra import get_plan
from app.repository.payments import (
    get_latest_pending_payment,
    mark_payment_status,
    apply_plan_to_user,
)
from app.models.payment import PaymentStatus
from app.utils.tg_edit import edit_text_safe

router = Router()
logger = logging.getLogger(__name__)


async def _hard_reset_user_runtime_caches(*, chat_id: int) -> None:
    try:
        from app.handlers import scenario_model

        album = getattr(scenario_model, "_album", None)
        if album and hasattr(album, "clear_chat"):
            await album.clear_chat(chat_id)
    except Exception:
        pass


async def _platega_get_status(tx_id: str) -> str | None:
    base_url = os.getenv("PLATEGA_BASE_URL") or "https://app.platega.io"
    merchant_id = os.getenv("PLATEGA_MERCHANT_ID") or ""
    secret = os.getenv("PLATEGA_SECRET") or ""

    if not merchant_id or not secret:
        logger.error(
            "start._platega_get_status: missing PLATEGA_MERCHANT_ID/PLATEGA_SECRET"
        )
        return None

    url = f"{base_url.rstrip('/')}/transaction/{tx_id}"
    headers = {"X-MerchantId": merchant_id, "X-Secret": secret}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers=headers)
    except Exception:
        logger.exception("start._platega_get_status: request failed tx_id=%s", tx_id)
        return None

    if r.status_code != 200:
        logger.warning(
            "start._platega_get_status: non-200 status_code=%s tx_id=%s body=%s",
            r.status_code,
            tx_id,
            (r.text or "")[:500],
        )
        return None

    try:
        data = r.json()
    except Exception:
        logger.exception(
            "start._platega_get_status: invalid json tx_id=%s body=%s",
            tx_id,
            (r.text or "")[:500],
        )
        return None

    status = data.get("status")
    logger.info("start._platega_get_status: tx_id=%s status=%s", tx_id, status)
    return status


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await _hard_reset_user_runtime_caches(chat_id=message.chat.id)

    # /start payload (например: /start pay_ok)
    parts = (message.text or "").split(maxsplit=1)
    start_payload = parts[1] if len(parts) > 1 else ""

    logger.info(
        "start.cmd_start: tg_id=%s username=%s payload=%s",
        message.from_user.id if message.from_user else None,
        message.from_user.username if message.from_user else None,
        start_payload,
    )

    # --- апсертим юзера и дефолтные настройки ---
    user, created = await get_or_create_user(
        session=session,
        tg_id=message.from_user.id,
        username=message.from_user.username,
    )

    await ensure_photo_settings(session=session, user_id=user.id)
    await ensure_default_subscription(session=session, tg_id=message.from_user.id)

    ref_tg_id = parse_referrer_tg_id(start_payload)
    if created and ref_tg_id:
        await process_referral_for_new_user(
            session, new_user=user, referrer_tg_id=ref_tg_id
        )
    if created:
        await schedule_free_bonus_reminder(message.bot, message.from_user.id, delay_s=600)

    # --- если вернулись из оплаты: проверяем PENDING и пытаемся подтвердить ---
    if start_payload in {"pay_ok", "pay_fail"}:
        pending = await get_latest_pending_payment(session, message.from_user.id)

        if not pending:
            logger.warning(
                "start.cmd_start: no pending payment tg_id=%s", message.from_user.id
            )
            await message.answer(
                "Не нашёл ожидающих оплат. Если оплата прошла — открой «Доп. возможности» ещё раз 🙌",
                reply_markup=main_menu_kb(),
            )
            return

        logger.info(
            "start.cmd_start: pending payment_id=%s tx_id=%s plan=%s status=%s",
            pending.id,
            pending.platega_transaction_id,
            pending.plan_name,
            pending.status,
        )

        status = await _platega_get_status(pending.platega_transaction_id)

        if status == "CONFIRMED":
            plan = await get_plan(session, pending.plan_name)
            if not plan:
                logger.error(
                    "start.cmd_start: plan not found in DB plan_name=%s payment_id=%s",
                    pending.plan_name,
                    pending.id,
                )
            else:
                # apply_plan_to_user уже с логированием и реальным начислением
                await apply_plan_to_user(session, message.from_user.id, plan)

            await mark_payment_status(session, pending, PaymentStatus.CONFIRMED)

            await message.answer(
                "✅ Оплата подтверждена! Пакет активирован 🎉",
                reply_markup=main_menu_kb(),
            )
            return

        if status in {"CANCELED", "CHARGEBACK"}:
            await mark_payment_status(session, pending, PaymentStatus(status))
            await message.answer(
                "Платёж не завершён (отменён/возврат). Если нужна помощь — напиши в поддержку 💬",
                reply_markup=main_menu_kb(),
            )
            return

        # PENDING / None / неизвестно
        await message.answer(
            "Платёж ещё обрабатывается. Попробуй снова через минуту ⏳",
            reply_markup=main_menu_kb(),
        )
        return

    # --- обычный старт ---
    await message.answer(
        "Привет! Я WEARAI 👋\n\n"
        "Вот что я умею:\n"
        "🖼 <b>Работа с фото</b>\n"
        "— <b>Модель с товаром</b>: опиши модель, загрузи до 5 фото товара 📸 и укажи, как его подать.\n"
        "— <b>Примерить одежду</b>: пришли своё фото 🤳, выбери часть тела 🎯, пришли фото вещи 📦 и подтверди.\n\n"
        "🎬 <b>Работа с видео</b>\n"
        "— <b>Оживить видео</b>: загрузи фото и напиши, что должно происходить в видео.\n\n"
        "🪄 <b>Помочь с описанием</b> — подскажу, как лучше написать промпт.\n"
        "✨ <b>Доп. возможности</b> — пакеты генераций и оплата.\n"
        "❓ <b>FAQ</b> — ответы, инструкции и реферальная система.\n"
        "⚙️ <b>Настройки</b> — параметры генерации фото.\n\n"
        "Выбирай режим ниже 👇✨",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == MenuCallbacks.HELP)
async def menu_help(call: CallbackQuery) -> None:
    await edit_text_safe(
        call,
        "Конечно! 😊\n\nЧто будем генерировать? 👇",
        reply_markup=help_choose_kb(),
    )
    await call.answer()
