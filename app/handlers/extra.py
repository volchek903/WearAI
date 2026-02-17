# app/handlers/extra.py
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass

import httpx
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, LabeledPrice, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.menu import MenuCallbacks, main_menu_kb
from app.keyboards.extra import (
    ExtraCallbacks,
    extra_menu_kb,
    extra_buy_kb,
    extra_pay_poll_kb,
)
from app.keyboards.utils import add_button
from app.services.free_channel_bonus import (
    CHANNEL_URL,
    free_channel_kb,
    is_user_in_channel,
    bonus_already_used,
    start_bonus_pending,
    schedule_bonus_grant,
)
from app.repository.promo import redeem_promo_code, PromoError
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
from app.utils.tg_edit import edit_text_safe
from app.services.platega import normalize_payment_status, check_platega_health

router = Router()
logger = logging.getLogger(__name__)

# Показываем только доступные к покупке пакеты (Launch выдаётся один раз)


class FreePromoFlow(StatesGroup):
    code = State()


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

        async def _do() -> httpx.Response:
            async with httpx.AsyncClient(timeout=20) as client:
                return await client.post(url, headers=headers, json=body)

        r = await _with_retries(_do)

        r.raise_for_status()
        return r.json()

    async def get_transaction_status(self, tx_id: str) -> str | None:
        url = f"{self.cfg.base_url.rstrip('/')}/transaction/{tx_id}"
        headers = {"X-MerchantId": self.cfg.merchant_id, "X-Secret": self.cfg.secret}

        async def _do() -> httpx.Response:
            async with httpx.AsyncClient(timeout=20) as client:
                return await client.get(url, headers=headers)

        try:
            r = await _with_retries(_do)
        except httpx.HTTPError:
            return None

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

        status = data.get("status")
        if not status and isinstance(data.get("transaction"), dict):
            status = data["transaction"].get("status")
        if not status and isinstance(data.get("data"), dict):
            data_obj = data["data"]
            status = data_obj.get("status")
            if not status and isinstance(data_obj.get("transaction"), dict):
                status = data_obj["transaction"].get("status")

        return str(status) if status else None


async def _with_retries(
    fn, retries: int = 2, backoff_s: float = 1.5
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await fn()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            last_exc = e
            if attempt >= retries:
                raise
            await asyncio.sleep(backoff_s * (attempt + 1))
        except httpx.HTTPError as e:
            last_exc = e
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("request failed")


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


def _strike(text: str) -> str:
    # Use Unicode combining long stroke for a strikethrough effect inside <pre>.
    return "".join(ch + "\u0336" for ch in text)


def _table(plans: list[Subscription]) -> str:
    lines = ["<b>Пакеты</b>"]

    def _price_key(p: Subscription) -> tuple:
        rub_price = int(float(p.price)) if float(p.price) > 0 else 0
        stars_price = int(getattr(p, "stars_price", 0) or 0)
        effective = rub_price if rub_price > 0 else stars_price
        return (effective, rub_price, stars_price, p.name.lower())

    sorted_plans = sorted(plans, key=_price_key)

    for p in sorted_plans:
        if p.name == "Launch":
            continue

        rub_price = int(float(p.price)) if float(p.price) > 0 else 0
        stars_price = int(getattr(p, "stars_price", 0) or 0)

        if rub_price <= 0 and stars_price <= 0:
            rub_part = "Бесплатно"
            stars_part = "Бесплатно"
        else:
            rub_part = f"{rub_price} ₽" if rub_price > 0 else "—"
            stars_part = f"{stars_price} ⭐" if stars_price > 0 else "—"
        days = "без срока" if p.duration_days == 0 else f"{p.duration_days} дн."
        lines.append(
            "\n".join(
                [
                    f"<b>{_escape(p.name)}</b>",
                    f"Фото: <b>{p.photo_generations}</b>",
                    f"Видео: <b>{p.video_generations}</b>",
                    f"Срок: <b>{days}</b>",
                    f"Цена: {rub_part} / {stars_part}",
                ]
            )
        )
        lines.append("────────────")

    if lines and lines[-1] == "────────────":
        lines.pop()

    joined = "\n".join(lines)
    return joined


def _extra_text(
    current_name: str, remaining_video: int, remaining_photo: int, table_html: str
) -> str:
    return (
        "✨ <b>Дополнительные возможности</b>\n\n"
        f"Твоя текущая подписка: <b>{_escape(current_name)}</b>\n"
        f"Осталось генераций: 🎬 <b>{remaining_video}</b> видео • 🖼️ <b>{remaining_photo}</b> фото\n"
        "\n"
        f"{table_html}\n\n"
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

    rub_price = int(float(plan.price)) if float(plan.price) > 0 else 0
    stars_price = int(getattr(plan, "stars_price", 0) or 0)
    if rub_price <= 0 and stars_price <= 0:
        price = "Бесплатно"
    else:
        rub_old = int(round(rub_price * 1.1)) if rub_price > 0 else 0
        stars_old = int(round(stars_price * 1.1)) if stars_price > 0 else 0

        rub_part = (
            f"<b>{rub_price} ₽</b> (скидка, было <s>{rub_old} ₽</s>)"
            if rub_price > 0
            else "—"
        )
        stars_part = (
            f"<b>{stars_price} ⭐</b> (скидка, было <s>{stars_old} ⭐</s>)"
            if stars_price > 0
            else "—"
        )
        price = f"{rub_part} / {stars_part}"
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
        await edit_text_safe(call, "Главное меню 👇", reply_markup=main_menu_kb())
    await call.answer()


@router.callback_query(F.data == ExtraCallbacks.FREE)
async def extra_free_generation(call: CallbackQuery, session: AsyncSession) -> None:
    if call.message is None:
        await call.answer()
        return

    if await bonus_already_used(session, call.from_user.id):
        await edit_text_safe(
            call,
            "Ты уже получал(а) бесплатную генерацию за подписку ✅",
            reply_markup=main_menu_kb(),
        )
        await call.answer()
        return

    await edit_text_safe(
        call,
        "Подпишись на канал и нажми кнопку «✅ Я подписался» ниже 👇",
        reply_markup=free_channel_kb(),
    )
    await call.answer()


@router.callback_query(F.data == ExtraCallbacks.FREE_INFO)
async def extra_free_info(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None:
        await call.answer()
        return

    kb = InlineKeyboardBuilder()
    add_button(kb, text="Бесплатная генерация", callback_data=ExtraCallbacks.FREE)
    add_button(kb, text="Ввести промокод", callback_data=ExtraCallbacks.FREE_PROMO)
    kb.adjust(1)

    await edit_text_safe(
        call,
        "🎁 <b>Бесплатная генерация</b>\n\n"
        "Получить бонус просто:\n"
        "1) Подпишись на наш канал.\n"
        "2) Нажми кнопку ниже — мы проверим подписку и начислим <b>+1 фото‑генерацию</b> в течение минуты.\n\n"
        "Промокоды мы публикуем в рассылке внутри бота и в нашем Telegram‑канале:\n"
        f"{CHANNEL_URL}\n\n"
        "Бонус за подписку можно получить только <b>1 раз</b> на пользователя.",
        reply_markup=kb.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data == ExtraCallbacks.FREE_PROMO)
async def extra_free_promo_start(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None:
        await call.answer()
        return
    await state.set_state(FreePromoFlow.code)
    await edit_text_safe(call, "Введите промокод ✍️")
    await call.answer()


@router.message(FreePromoFlow.code)
async def extra_free_promo_code(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    code = (message.text or "").strip()
    if not code:
        await message.answer("Промокод пустой. Попробуйте ещё раз ✍️")
        return
    await state.clear()

    try:
        promo = await redeem_promo_code(
            session=session, tg_id=message.from_user.id, code=code
        )
    except PromoError as e:
        if "исчерпан" in str(e):
            await message.answer(
                "⛔️ Промокод исчерпан — все активации уже использованы."
            )
        else:
            await message.answer(
                "❌ Промокод не найден или уже использован.",
                reply_markup=main_menu_kb(),
            )
        return
    except Exception:
        logger.exception("promo redeem failed")
        await message.answer("Не удалось активировать промокод 😕 Попробуй позже.")
        return

    await message.answer(
        f"✅ Промокод активирован!\n"
        f"Бонус: 🖼️ {promo.bonus_photo} фото • 🎬 {promo.bonus_video} видео"
    )

@router.callback_query(F.data == ExtraCallbacks.FREE_CHECK)
async def extra_free_check(call: CallbackQuery, session: AsyncSession) -> None:
    if call.message is None:
        await call.answer()
        return

    tg_id = call.from_user.id
    if await bonus_already_used(session, tg_id):
        text = "Ты уже получал(а) бесплатную генерацию за подписку ✅"
        markup = extra_menu_kb(current_plan_name=None)
        if call.message:
            try:
                if call.message.photo or call.message.document or call.message.video or call.message.animation:
                    await call.message.edit_caption(caption=text, reply_markup=markup)
                else:
                    await call.message.edit_text(text, reply_markup=markup)
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    await call.message.edit_reply_markup(reply_markup=markup)
                else:
                    await call.message.answer(text, reply_markup=markup)
        else:
            await edit_text_safe(call, text, reply_markup=markup)
        await call.answer()
        return

    in_channel = await is_user_in_channel(call.bot, tg_id)
    if not in_channel:
        await edit_text_safe(
            call,
            "Похоже, ты ещё не подписался(ась). "
            "Подпишись на канал и нажми «✅ Я подписался» ещё раз.",
            reply_markup=free_channel_kb(),
        )
        await call.answer()
        return

    started = await start_bonus_pending(session, tg_id)
    if not started:
        await edit_text_safe(call, "Проверка уже запущена или бонус уже выдан ✅")
        await call.answer()
        return

    await edit_text_safe(
        call,
        "Подписка подтверждена ✅\n"
        "В течение минуты придёт бесплатная генерация.",
        reply_markup=main_menu_kb(),
    )
    await call.answer()
    await schedule_bonus_grant(call.bot, tg_id, delay_s=60)


@router.callback_query(F.data == MenuCallbacks.EXTRA)
async def extra_open(call: CallbackQuery, session: AsyncSession) -> None:
    try:
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
            await edit_text_safe(
                call,
                _extra_text(current_name, remaining_video, remaining_photo, table_html),
                reply_markup=extra_menu_kb(current_name),
                parse_mode="HTML",
            )
        await call.answer()
    except Exception:
        logger.exception("extra_open failed")
        raise


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

    platega_ok = await check_platega_health()
    text = _pitch(plan_name, plan)
    if not platega_ok:
        text += "\n\n⚠️ Оплата картой/СБП/крипто временно недоступна. Доступна оплата Stars."
    if call.message:
        await edit_text_safe(
            call,
            text,
            reply_markup=extra_buy_kb(plan_name, platega_available=platega_ok),
            parse_mode="HTML",
        )
    await call.answer()


@router.callback_query(F.data == ExtraCallbacks.BACK)
async def extra_back(call: CallbackQuery, session: AsyncSession) -> None:
    await extra_open(call, session)


@router.callback_query(
    F.data.in_(
        {
            ExtraCallbacks.BUY_ORBIT,
            ExtraCallbacks.BUY_NOVA,
            ExtraCallbacks.BUY_COSMIC,
            ExtraCallbacks.BUY_ORBIT_CARD,
            ExtraCallbacks.BUY_NOVA_CARD,
            ExtraCallbacks.BUY_COSMIC_CARD,
            ExtraCallbacks.BUY_ORBIT_CRYPTO,
            ExtraCallbacks.BUY_NOVA_CRYPTO,
            ExtraCallbacks.BUY_COSMIC_CRYPTO,
            ExtraCallbacks.BUY_ORBIT_STARS,
            ExtraCallbacks.BUY_NOVA_STARS,
            ExtraCallbacks.BUY_COSMIC_STARS,
        }
    )
)
async def extra_buy(call: CallbackQuery, session: AsyncSession) -> None:
    await call.answer()
    if call.data in {
        ExtraCallbacks.BUY_ORBIT_STARS,
        ExtraCallbacks.BUY_NOVA_STARS,
        ExtraCallbacks.BUY_COSMIC_STARS,
    }:
        await extra_buy_stars(call, session)
        return

    if call.data in {
        ExtraCallbacks.BUY_ORBIT,
        ExtraCallbacks.BUY_ORBIT_CARD,
        ExtraCallbacks.BUY_ORBIT_CRYPTO,
    }:
        plan_name = "Orbit"
    elif call.data in {
        ExtraCallbacks.BUY_NOVA,
        ExtraCallbacks.BUY_NOVA_CARD,
        ExtraCallbacks.BUY_NOVA_CRYPTO,
    }:
        plan_name = "Nova"
    else:
        plan_name = "Cosmic"

    plan = await get_plan(session, plan_name)
    if not plan:
        await call.answer("Пакет не найден в базе 😕", show_alert=True)
        return

    amount = int(float(plan.price))
    currency = "RUB"

    platega_ok = await check_platega_health()
    if not platega_ok:
        if call.message:
            await edit_text_safe(
                call,
                "⚠️ Оплата картой/СБП/крипто временно недоступна.\n"
                "Попробуй позже или выбери оплату Stars.",
                reply_markup=extra_buy_kb(plan_name, platega_available=False),
                parse_mode="HTML",
            )
        return

    try:
        client = build_platega_client()
    except Exception:
        logger.exception("extra_buy: platega client init failed")
        await call.answer("Платёжный сервис не настроен", show_alert=True)
        return
    payload = {"tgUserId": call.from_user.id, "planName": plan.name}

    if call.data.endswith(":crypto"):
        pay_method = 13
    elif call.data.endswith(":card"):
        pay_method = 11
    else:
        pay_method = 2

    if call.message:
        await edit_text_safe(call, "🔥 Супер! Сейчас подготовлю оплату…", parse_mode="HTML")

    try:
        data = await client.create_payment_link(
            amount=amount,
            currency=currency,
            description=f"Donation plan {plan.name}",
            payload=payload,
            payment_method=pay_method,
        )
    except Exception:
        logger.exception(
            "extra_buy: failed to create payment plan=%s tg_id=%s",
            plan.name,
            call.from_user.id,
        )
        if call.message:
            await edit_text_safe(
                call,
                "Не удалось создать оплату 😕\n\nПопробуй ещё раз чуть позже.",
                reply_markup=extra_buy_kb(plan_name, platega_available=platega_ok),
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
            await edit_text_safe(
                call,
                "Платёжный сервис вернул некорректный ответ 😕",
                reply_markup=extra_buy_kb(plan_name, platega_available=platega_ok),
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
        await edit_text_safe(
            call,
            "✅ Готово!\n\n"
            "1) Нажми <b>Оплатить</b>\n"
            "2) Потом жми <b>Проверить оплату</b> (если не активировалось сразу)\n\n"
            "Пакет активируется сразу после подтверждения ✅",
            reply_markup=extra_pay_poll_kb(redirect, payment.id),
            parse_mode="HTML",
        )

    return


async def extra_buy_stars(call: CallbackQuery, session: AsyncSession) -> None:
    if call.data == ExtraCallbacks.BUY_ORBIT_STARS:
        plan_name = "Orbit"
    elif call.data == ExtraCallbacks.BUY_NOVA_STARS:
        plan_name = "Nova"
    else:
        plan_name = "Cosmic"

    plan = await get_plan(session, plan_name)
    if not plan:
        await call.answer("Пакет не найден в базе 😕", show_alert=True)
        return

    stars_price = int(getattr(plan, "stars_price", 0) or 0)
    if stars_price <= 0:
        await call.answer("Оплата Stars недоступна для этого пакета", show_alert=True)
        return

    payload = f"stars:{plan_name}:{call.from_user.id}"
    title = f"Пакет {plan.name}"
    description = (
        f"{plan.video_generations} видео • {plan.photo_generations} фото"
    )

    if call.message:
        await call.message.answer_invoice(
            title=title,
            description=description,
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=plan.name, amount=stars_price)],
        )
    await call.answer()


@router.pre_checkout_query()
async def stars_pre_checkout(pre_checkout: PreCheckoutQuery) -> None:
    payload = pre_checkout.invoice_payload or ""
    if not payload.startswith("stars:"):
        await pre_checkout.answer(ok=False, error_message="Неверные параметры оплаты.")
        return
    await pre_checkout.answer(ok=True)


@router.message(F.successful_payment)
async def stars_success(message: Message, session: AsyncSession) -> None:
    sp = message.successful_payment
    if not sp:
        return

    if (sp.currency or "").upper() != "XTR":
        return

    payload = sp.invoice_payload or ""
    if not payload.startswith("stars:"):
        return

    parts = payload.split(":")
    if len(parts) < 3:
        return

    plan_name = parts[1]
    payload_tg_id = parts[2]
    tg_id = message.from_user.id

    if payload_tg_id.isdigit() and int(payload_tg_id) != tg_id:
        return

    plan = await get_plan(session, plan_name)
    if not plan:
        await message.answer("Пакет не найден 😕")
        return

    await apply_plan_to_user(session, tg_id, plan)
    await message.answer(
        "✅ Оплата Stars подтверждена! Пакет активирован 🎉",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data.startswith(ExtraCallbacks.CHECK_PREFIX))
async def extra_check_payment(call: CallbackQuery, session: AsyncSession) -> None:
    raw = call.data or ""
    payment_id_str = raw.replace(ExtraCallbacks.CHECK_PREFIX, "", 1)

    if not payment_id_str.isdigit():
        await call.answer("Некорректный идентификатор платежа 😕", show_alert=True)
        return

    payment_id = int(payment_id_str)
    payment = await get_payment_by_id(session, payment_id)

    if not payment:
        await call.answer("Платёж не найден 😕", show_alert=True)
        return

    payment_tg_id = _payment_tg_id(payment)
    if not payment_tg_id:
        await call.answer("Не удалось определить пользователя платежа 😕", show_alert=True)
        return

    if payment_tg_id != call.from_user.id:
        await call.answer("Это не ваш платёж 🙅‍♂️", show_alert=True)
        return

    if payment.status == PaymentStatus.CONFIRMED:
        await call.answer("✅ Уже подтверждено — пакет активирован", show_alert=True)
        return

    try:
        client = build_platega_client()
    except Exception:
        logger.exception("extra_check_payment: platega client init failed")
        await call.answer("Платёжный сервис не настроен", show_alert=True)
        return
    raw_status = await client.get_transaction_status(payment.platega_transaction_id)
    status = normalize_payment_status(raw_status)

    logger.info(
        "extra_check_payment: payment_id=%s tx_id=%s tg_id=%s raw_status=%s normalized=%s",
        payment.id,
        payment.platega_transaction_id,
        payment_tg_id,
        raw_status,
        status,
    )

    if status == "CONFIRMED":
        plan = await get_plan(session, payment.plan_name)
        if plan:
            await apply_plan_to_user(session, call.from_user.id, plan)
        await mark_payment_status(session, payment, PaymentStatus.CONFIRMED)

        if call.message:
            await edit_text_safe(
                call,
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
        "Платёж ещё обрабатывается ⏳ Попробуй снова через минуту.",
        show_alert=True,
    )
