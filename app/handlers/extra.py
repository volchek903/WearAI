# app/handlers/extra.py
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

import httpx
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.menu import MenuCallbacks, main_menu_kb
from app.keyboards.extra import (
    ExtraCallbacks,
    extra_menu_kb,
    extra_buy_kb,
    extra_pay_poll_kb,
)
from app.models.payment import PaymentStatus
from app.models.subscription import Subscription
from app.repository.extra import (
    get_user,
    get_active_plan_name,
    get_active_remaining,
    get_plan,
    get_all_plans,
)
from app.repository.payments import (
    create_pending_payment,
    get_payment_by_id,
    mark_payment_status,
    apply_plan_to_user,
)

router = Router()
logger = logging.getLogger(__name__)

ORDER = ["Launch", "Orbit", "Nova", "Cosmic"]


def _payment_tg_id(payment) -> int | None:
    # ✅ FIX: в проекте встречаются разные имена атрибута
    return (
        getattr(payment, "tg_user_id", None)
        or getattr(payment, "user_tg_id", None)
        or getattr(payment, "user_tg", None)
    )


@dataclass
class PlategaConfig:
    base_url: str
    merchant_id: str
    secret: str
    return_url: str
    failed_url: str


class PlategaClient:
    def __init__(self, cfg: PlategaConfig) -> None:
        self.cfg = cfg

    async def create_payment_link(
        self,
        *,
        amount: int,
        currency: str,
        description: str,
        payload: dict,
        payment_method: int = 2,
    ) -> dict:
        url = f"{self.cfg.base_url.rstrip('/')}/transaction/process"
        headers = {
            "Content-Type": "application/json",
            "X-MerchantId": self.cfg.merchant_id,
            "X-Secret": self.cfg.secret,
        }
        body = {
            "paymentMethod": payment_method,
            "paymentDetails": {"amount": amount, "currency": currency},
            "description": description,
            "return": self.cfg.return_url,
            "failedUrl": self.cfg.failed_url,
            "payload": json.dumps(payload, ensure_ascii=False),
        }

        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, headers=headers, json=body)

        r.raise_for_status()
        return r.json()

    async def get_transaction_status(self, tx_id: str) -> str | None:
        url = f"{self.cfg.base_url.rstrip('/')}/transaction/{tx_id}"
        headers = {"X-MerchantId": self.cfg.merchant_id, "X-Secret": self.cfg.secret}

        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers=headers)

        if r.status_code != 200:
            logger.warning(
                "platega.get_transaction_status: non-200 status_code=%s tx_id=%s body=%s",
                r.status_code,
                tx_id,
                (r.text or "")[:500],
            )
            return None

        try:
            data = r.json()
        except Exception:
            logger.exception(
                "platega.get_transaction_status: invalid json tx_id=%s body=%s",
                tx_id,
                (r.text or "")[:500],
            )
            return None

        return data.get("status")


def build_platega_client() -> PlategaClient:
    cfg = PlategaConfig(
        base_url=os.getenv("PLATEGA_BASE_URL") or "https://app.platega.io",
        merchant_id=os.getenv("PLATEGA_MERCHANT_ID") or "",
        secret=os.getenv("PLATEGA_SECRET") or "",
        return_url=os.getenv("PLATEGA_RETURN_URL") or "",
        failed_url=os.getenv("PLATEGA_FAILED_URL") or "",
    )

    if not cfg.merchant_id or not cfg.secret:
        raise RuntimeError("Platega env is not configured (MERCHANT_ID/SECRET).")

    return PlategaClient(cfg)


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _table(plans: list[Subscription]) -> str:
    by_name = {p.name: p for p in plans}

    lines = [
        "Пакет      Цена     Дней   Видео   Фото",
        "----------------------------------------",
    ]

    for name in ORDER:
        p = by_name.get(name)
        if not p:
            continue

        price = "Free" if float(p.price) == 0 else f"${float(p.price):.0f}"
        days = "-" if p.duration_days == 0 else str(p.duration_days)

        lines.append(
            f"{p.name:<10} {price:<7} {days:<5} {p.video_generations:<6} {p.photo_generations:<6}"
        )

    joined = "\n".join(lines)
    return f"<pre>{_escape(joined)}</pre>"


def _extra_text(
    current_name: str, remaining_video: int, remaining_photo: int, table_html: str
) -> str:
    return (
        "✨ <b>Дополнительные возможности</b>\n\n"
        f"Твоя текущая подписка: <b>{_escape(current_name)}</b>\n"
        f"Осталось генераций: 🎬 <b>{remaining_video}</b> видео • 🖼️ <b>{remaining_photo}</b> фото\n\n"
        "За пожертвование ты получаешь доступ к пакетам генераций — "
        "это помогает развитию сервиса и даёт больше контента под твои товары.\n\n"
        f"{table_html}\n"
        "Выбирай пакет ниже — и я расскажу, что там самого кайфового 👇"
    )


def _pitch(plan_name: str, plan: Subscription) -> str:
    if plan_name == "Orbit":
        intro = "Ооо, <b>Orbit</b> — отличный выбор 🚀"
        vibe = "Это уверенный режим: тестишь идеи, делаешь карточки товара и вариации спокойно."
    elif plan_name == "Nova":
        intro = "Йо! <b>Nova</b> — это уже мощно 😮‍💨✨"
        vibe = "Здесь можно разогнаться по ассортименту и делать контент пачками."
    else:
        intro = "Воу… <b>Cosmic</b> — уровень «я пришёл забирать рынок» 🤯🌌"
        vibe = "Максимальная свобода: много генераций, можно закрывать линейки товаров без стресса."

    price = "Free" if float(plan.price) == 0 else f"<b>${float(plan.price):.0f}</b>"
    days = (
        "без срока"
        if plan.duration_days == 0
        else f"на <b>{plan.duration_days}</b> дней"
    )

    return (
        f"{intro}\n\n"
        f"Вот что ты получаешь {days}:\n"
        f"• 🎬 Видео: <b>{plan.video_generations}</b>\n"
        f"• 🖼️ Фото: <b>{plan.photo_generations}</b>\n"
        f"• 💰 Стоимость: {price}\n\n"
        f"{vibe}\n\n"
        "Если готов — жми <b>Купить</b> 😉"
    )


@router.callback_query(F.data == ExtraCallbacks.TO_MENU)
async def extra_to_menu(call: CallbackQuery) -> None:
    if call.message:
        await call.message.edit_text("Главное меню 👇", reply_markup=main_menu_kb())
    await call.answer()


@router.callback_query(F.data == MenuCallbacks.EXTRA)
async def extra_open(call: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user(session, call.from_user.id)

    if not user:
        current_name = "Launch"
        remaining_video, remaining_photo = 2, 3
    else:
        current_name = await get_active_plan_name(session, user.id)
        remaining_video, remaining_photo = await get_active_remaining(session, user.id)

    plans = await get_all_plans(session)
    table_html = _table(plans)

    if call.message:
        await call.message.edit_text(
            _extra_text(current_name, remaining_video, remaining_photo, table_html),
            reply_markup=extra_menu_kb(current_name),
            parse_mode="HTML",
        )
    await call.answer()


@router.callback_query(
    F.data.in_(
        {
            ExtraCallbacks.WANT_ORBIT,
            ExtraCallbacks.WANT_NOVA,
            ExtraCallbacks.WANT_COSMIC,
        }
    )
)
async def extra_want(call: CallbackQuery, session: AsyncSession) -> None:
    plan_name = (
        "Orbit"
        if call.data == ExtraCallbacks.WANT_ORBIT
        else "Nova" if call.data == ExtraCallbacks.WANT_NOVA else "Cosmic"
    )

    plan = await get_plan(session, plan_name)
    if not plan:
        await call.answer("Пакет не найден в базе 😕", show_alert=True)
        return

    if call.message:
        await call.message.edit_text(
            _pitch(plan_name, plan),
            reply_markup=extra_buy_kb(plan_name),
            parse_mode="HTML",
        )
    await call.answer()


@router.callback_query(F.data == ExtraCallbacks.BACK)
async def extra_back(call: CallbackQuery, session: AsyncSession) -> None:
    await extra_open(call, session)


@router.callback_query(
    F.data.in_(
        {ExtraCallbacks.BUY_ORBIT, ExtraCallbacks.BUY_NOVA, ExtraCallbacks.BUY_COSMIC}
    )
)
async def extra_buy(call: CallbackQuery, session: AsyncSession) -> None:
    plan_name = (
        "Orbit"
        if call.data == ExtraCallbacks.BUY_ORBIT
        else "Nova" if call.data == ExtraCallbacks.BUY_NOVA else "Cosmic"
    )

    plan = await get_plan(session, plan_name)
    if not plan:
        await call.answer("Пакет не найден в базе 😕", show_alert=True)
        return

    amount = int(float(plan.price))
    currency = "RUB"

    client = build_platega_client()
    payload = {"tgUserId": call.from_user.id, "planName": plan.name}

    if call.message:
        await call.message.edit_text(
            "🔥 Супер! Сейчас подготовлю оплату…", parse_mode="HTML"
        )

    try:
        data = await client.create_payment_link(
            amount=amount,
            currency=currency,
            description=f"Donation plan {plan.name}",
            payload=payload,
            payment_method=2,
        )
    except Exception:
        logger.exception(
            "extra_buy: failed to create payment plan=%s tg_id=%s",
            plan.name,
            call.from_user.id,
        )
        if call.message:
            await call.message.edit_text(
                "Не удалось создать оплату 😕\n\nПопробуй ещё раз чуть позже.",
                reply_markup=extra_buy_kb(plan_name),
                parse_mode="HTML",
            )
        await call.answer("Ошибка платежного сервиса", show_alert=True)
        return

    redirect = data.get("redirect")
    tx_id = data.get("transactionId")

    if not redirect or not tx_id:
        logger.error(
            "extra_buy: invalid platega response tg_id=%s data=%s",
            call.from_user.id,
            data,
        )
        if call.message:
            await call.message.edit_text(
                "Платёжный сервис вернул некорректный ответ 😕",
                reply_markup=extra_buy_kb(plan_name),
                parse_mode="HTML",
            )
        await call.answer("Ошибка ответа Platega", show_alert=True)
        return

    payment = await create_pending_payment(
        session,
        tg_user_id=call.from_user.id,
        plan_name=plan.name,
        amount=amount,
        currency=currency,
        tx_id=tx_id,
    )

    if call.message:
        await call.message.edit_text(
            "✅ Готово!\n\n"
            "1) Нажми <b>Оплатить</b>\n"
            "2) Потом жми <b>Проверить оплату</b> (если не активировалось сразу)\n\n"
            "Пакет активируется сразу после подтверждения ✅",
            reply_markup=extra_pay_poll_kb(redirect, payment.id),
            parse_mode="HTML",
        )

    await call.answer()


@router.callback_query(F.data.startswith(ExtraCallbacks.CHECK_PREFIX))
async def extra_check_payment(call: CallbackQuery, session: AsyncSession) -> None:
    raw = call.data or ""
    payment_id_str = raw.replace(ExtraCallbacks.CHECK_PREFIX, "", 1)

    if not payment_id_str.isdigit():
        await call.answer("Некорректный идентификатор платежа", show_alert=True)
        return

    payment_id = int(payment_id_str)
    payment = await get_payment_by_id(session, payment_id)

    if not payment:
        await call.answer("Платёж не найден", show_alert=True)
        return

    payment_tg_id = _payment_tg_id(payment)
    if not payment_tg_id:
        await call.answer("Не удалось определить пользователя платежа", show_alert=True)
        return

    if payment_tg_id != call.from_user.id:
        await call.answer("Это не ваш платёж", show_alert=True)
        return

    if payment.status == PaymentStatus.CONFIRMED:
        await call.answer("✅ Уже подтверждено, пакет активирован", show_alert=True)
        return

    client = build_platega_client()
    status = await client.get_transaction_status(payment.platega_transaction_id)

    logger.info(
        "extra_check_payment: payment_id=%s tx_id=%s tg_id=%s status=%s",
        payment.id,
        payment.platega_transaction_id,
        payment_tg_id,
        status,
    )

    if status == "CONFIRMED":
        plan = await get_plan(session, payment.plan_name)
        if plan:
            await apply_plan_to_user(session, call.from_user.id, plan)
        await mark_payment_status(session, payment, PaymentStatus.CONFIRMED)

        if call.message:
            await call.message.edit_text(
                "✅ Оплата подтверждена! Пакет активирован 🎉",
                reply_markup=main_menu_kb(),
                parse_mode="HTML",
            )
        await call.answer()
        return

    if status in {"CANCELED", "CHARGEBACK"}:
        await mark_payment_status(session, payment, PaymentStatus(status))
        await call.answer("Платёж не завершён (отменён/возврат).", show_alert=True)
        return

    await call.answer(
        "Платёж ещё обрабатывается. Попробуй снова через минуту 🙂", show_alert=True
    )
