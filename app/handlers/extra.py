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
    extra_custom_buy_kb,
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
from app.repository.generations import ensure_default_subscription
from app.repository.payments import (
    apply_credit_amount_to_user,
    create_pending_payment,
    get_payment_by_id,
    mark_payment_status,
    apply_plan_to_user,
    make_custom_plan_name,
    parse_custom_plan_credits,
)
from app.utils.tg_edit import edit_text_safe
from app.utils.tg_callback import safe_answer
from app.utils.support_text import with_support
from app.services.platega import normalize_payment_status, check_platega_health

router = Router()
logger = logging.getLogger(__name__)

# Показываем только доступные к покупке пакеты (Launch выдаётся один раз)
STAR_USD_RATE = 23.99 / 1000
USD_TO_RUB = 79
RUB_PER_STAR = STAR_USD_RATE * USD_TO_RUB


class FreePromoFlow(StatesGroup):
    code = State()


class CustomCreditsFlow(StatesGroup):
    amount = State()


def _format_promo_bonus(promo) -> str:
    bonus_credits = int(getattr(promo, "bonus_credits", 0) or 0)
    if bonus_credits > 0:
        return f"{bonus_credits} кредитов"

    bonus_photo = int(getattr(promo, "bonus_photo", 0) or 0)
    bonus_video = int(getattr(promo, "bonus_video", 0) or 0)
    parts: list[str] = []
    if bonus_photo > 0:
        parts.append(f"🖼️ {bonus_photo} фото")
    if bonus_video > 0:
        parts.append(f"🎬 {bonus_video} видео")
    return " • ".join(parts) if parts else "0 кредитов"


def _payment_tg_id(payment) -> int | None:
    # ✅ FIX: в проекте встречаются разные имена атрибута
    return (
        getattr(payment, "tg_user_id", None)
        or getattr(payment, "user_tg_id", None)
        or getattr(payment, "user_tg", None)
    )


def _custom_pitch(credits: int) -> str:
    stars = _stars_for_credits(credits)
    return (
        "💠 <b>Своя сумма</b>\n\n"
        f"Вы выбрали пополнение на <b>{credits}</b> кредитов.\n"
        f"К оплате: <b>{credits} ₽</b> / <b>{stars} ⭐</b>\n\n"
        "Выберите удобный способ оплаты 👇"
    )


def _stars_for_credits(credits: int) -> int:
    if credits <= 0:
        return 0
    raw = max(1, round(int(credits) / RUB_PER_STAR))
    return ((raw + 9) // 10) * 10


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


def _price_key(p: Subscription) -> tuple:
    rub_price = int(float(p.price)) if float(p.price) > 0 else 0
    stars_price = int(getattr(p, "stars_price", 0) or 0)
    effective = rub_price if rub_price > 0 else stars_price
    return (effective, rub_price, stars_price, p.name.lower())


def _purchasable_plans(plans: list[Subscription]) -> list[Subscription]:
    return [
        p
        for p in sorted(plans, key=_price_key)
        if p.name not in {"Base", "Launch"}
    ]


def _table(plans: list[Subscription]) -> str:
    lines = ["<b>Кредитные пакеты</b>"]

    for p in _purchasable_plans(plans):

        rub_price = int(float(p.price)) if float(p.price) > 0 else 0
        stars_price = int(getattr(p, "stars_price", 0) or 0)

        if rub_price <= 0 and stars_price <= 0:
            rub_part = "Бесплатно"
            stars_part = "Бесплатно"
        else:
            rub_part = f"{rub_price} ₽" if rub_price > 0 else "—"
            stars_part = f"{stars_price} ⭐" if stars_price > 0 else "—"
        lines.append(
            "\n".join(
                [
                    f"<b>{_escape(p.name)}</b>",
                    f"Кредиты: <b>{int(getattr(p, 'credit_amount', 0) or 0)}</b>",
                    f"Скидка: <b>{_package_discount_text(p.name)}</b>",
                    f"Цена: {rub_part} / {stars_part}",
                ]
            )
        )
        lines.append("────────────")

    if lines and lines[-1] == "────────────":
        lines.pop()

    joined = "\n".join(lines)
    return joined


def _package_discount_text(plan_name: str) -> str:
    if plan_name == "Pulse":
        return "10%"
    if plan_name == "Orbit":
        return "10%"
    if plan_name == "Nova":
        return "15%"
    if plan_name == "Cosmic":
        return "25%"
    return "0%"


def _extra_text(
    current_name: str,
    paid_credit_balance: int,
    free_credit_balance: int,
    table_html: str,
) -> str:
    return (
        "✨ <b>Дополнительные возможности</b>\n\n"
        f"Режим оплаты: <b>{_escape(current_name)}</b>\n"
        f"Основные кредиты: <b>{int(paid_credit_balance)}</b>\n"
        f"Бесплатные кредиты: <b>{int(free_credit_balance)}</b>\n"
        f"Всего доступно: <b>{int(paid_credit_balance) + int(free_credit_balance)}</b>\n"
        "\n"
        f"{table_html}\n\n"
        "Выбирай пакет ниже, чтобы пополнить баланс 👇"
    )


def _pitch(plan_name: str, plan: Subscription) -> str:
    if plan_name == "Pulse":
        intro = "Лёгкий старт с <b>Pulse</b> ⚡"
        vibe = "Подойдет, если хочешь быстро протестировать механику без большого пополнения."
    elif plan_name == "Orbit":
        intro = "Ооо, <b>Orbit</b> — быстрый старт 🚀"
        vibe = "Подойдет, если хочешь аккуратно тестировать гипотезы и не держать большой остаток."
    elif plan_name == "Nova":
        intro = "Йо! <b>Nova</b> — рабочий объём 😮‍💨✨"
        vibe = "Хватает для регулярной генерации фото и видео без постоянных пополнений."
    else:
        intro = "Воу… <b>Cosmic</b> — запас с комфортом 🤯🌌"
        vibe = "Большой баланс для постоянной работы и агрессивного продакшна."

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
    return (
        f"{intro}\n\n"
        "Вот что ты получаешь:\n"
        f"• 💠 Кредиты: <b>{int(getattr(plan, 'credit_amount', 0) or 0)}</b>\n"
        f"• 🏷 Скидка: <b>{_package_discount_text(plan.name)}</b>\n"
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
        await safe_answer(call)
        return

    if await bonus_already_used(session, call.from_user.id):
        await edit_text_safe(
            call,
            "Ты уже получал(а) бесплатную генерацию за подписку ✅",
            reply_markup=main_menu_kb(),
        )
        await safe_answer(call)
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
        "2) Нажми кнопку ниже — мы проверим подписку и начислим кредиты на <b>1 фото‑генерацию</b> в течение минуты.\n\n"
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
        "✅ Промокод активирован!\n"
        f"Бонус: {_format_promo_bonus(promo)}"
    )

@router.callback_query(F.data == ExtraCallbacks.FREE_CHECK)
async def extra_free_check(call: CallbackQuery, session: AsyncSession) -> None:
    if call.message is None:
        await call.answer()
        return

    tg_id = call.from_user.id
    if await bonus_already_used(session, tg_id):
        text = "Ты уже получал(а) бесплатную генерацию за подписку ✅"
        plans = await get_all_plans(session)
        markup = extra_menu_kb(_purchasable_plans(plans), current_plan_name=None)
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
            current_name = "Кредитный баланс"
            paid_credit_balance = 0
            free_credit_balance = 0
        else:
            await ensure_default_subscription(session, call.from_user.id)
            current_name = await get_active_plan_name(session, user.id)
            paid_credit_balance, free_credit_balance = await get_active_remaining(
                session, user.id
            )

        plans = await get_all_plans(session)
        table_html = _table(plans)
        menu_plans = _purchasable_plans(plans)

        if call.message:
            await edit_text_safe(
                call,
                _extra_text(
                    current_name,
                    paid_credit_balance,
                    free_credit_balance,
                    table_html,
                ),
                reply_markup=extra_menu_kb(menu_plans, current_name),
                parse_mode="HTML",
            )
        await safe_answer(call)
    except Exception:
        logger.exception("extra_open failed")
        raise


@router.callback_query(F.data.startswith(ExtraCallbacks.WANT_PREFIX))
async def extra_want(call: CallbackQuery, session: AsyncSession) -> None:
    raw = (call.data or "").replace(ExtraCallbacks.WANT_PREFIX, "", 1)
    if not raw.isdigit():
        await call.answer("Некорректный пакет 😕", show_alert=True)
        return
    plan_id = int(raw)
    plan = await session.get(Subscription, plan_id)
    if not plan:
        await call.answer("Пакет не найден в базе 😕", show_alert=True)
        return

    platega_ok = await check_platega_health()
    text = _pitch(plan.name, plan)
    if not platega_ok:
        text += "\n\n⚠️ Оплата картой/СБП/крипто временно недоступна. Доступна оплата Stars."
    if call.message:
        await edit_text_safe(
            call,
            text,
            reply_markup=extra_buy_kb(plan, platega_available=platega_ok),
            parse_mode="HTML",
        )
    await call.answer()


@router.callback_query(F.data == ExtraCallbacks.BACK)
async def extra_back(call: CallbackQuery, session: AsyncSession) -> None:
    await extra_open(call, session)


@router.callback_query(F.data == ExtraCallbacks.CUSTOM_AMOUNT)
async def extra_custom_amount_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CustomCreditsFlow.amount)
    if call.message:
        await edit_text_safe(
            call,
            "Введите сумму пополнения в кредитах от <b>200</b> до <b>100000</b> ✍️",
            reply_markup=None,
            parse_mode="HTML",
        )
    await call.answer()


@router.message(CustomCreditsFlow.amount)
async def extra_custom_amount_value(
    message: Message, state: FSMContext
) -> None:
    raw = (message.text or "").strip()
    try:
        credits = int(raw)
    except Exception:
        await message.answer("Нужно целое число от 200 до 100000 ✍️")
        return

    if credits < 200 or credits > 100000:
        await message.answer("Сумма должна быть от 200 до 100000 кредитов ✍️")
        return

    await state.clear()
    from app.services.platega import check_platega_health

    platega_ok = await check_platega_health()
    text = _custom_pitch(credits)
    if not platega_ok:
        text += "\n\n⚠️ Оплата картой/СБП/крипто временно недоступна. Доступна оплата Stars."
    await message.answer(
        text,
        reply_markup=extra_custom_buy_kb(credits, platega_available=platega_ok),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith(ExtraCallbacks.BUY_PREFIX))
async def extra_buy(call: CallbackQuery, session: AsyncSession) -> None:
    await call.answer()
    raw = (call.data or "").replace(ExtraCallbacks.BUY_PREFIX, "", 1)
    parts = raw.split(":")
    if len(parts) != 2 or not parts[0].isdigit():
        await call.answer("Некорректный платёж 😕", show_alert=True)
        return
    plan_id = int(parts[0])
    method = parts[1]

    plan = await session.get(Subscription, plan_id)
    if not plan:
        await call.answer("Пакет не найден в базе 😕", show_alert=True)
        return

    if method == "stars":
        await extra_buy_stars(call, session, plan)
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
                reply_markup=extra_buy_kb(plan, platega_available=False),
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

    if method == "crypto":
        pay_method = 13
    elif method == "card":
        pay_method = 11
    else:
        pay_method = 2

    if call.message:
        await edit_text_safe(call, "🔥 Супер! Сейчас подготовлю оплату…", parse_mode="HTML")

    try:
        data = await client.create_payment_link(
            amount=amount,
            currency=currency,
            description=f"Credit pack {plan.name}",
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
                reply_markup=extra_buy_kb(plan, platega_available=platega_ok),
                parse_mode="HTML",
            )
        await call.answer(
            with_support("Ошибка платежного сервиса"), show_alert=True
        )
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
                reply_markup=extra_buy_kb(plan, platega_available=platega_ok),
                parse_mode="HTML",
            )
        await call.answer(with_support("Ошибка ответа Platega"), show_alert=True)
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
            "Кредиты начислятся сразу после подтверждения ✅",
            reply_markup=extra_pay_poll_kb(redirect, payment.id),
            parse_mode="HTML",
        )

    return


@router.callback_query(F.data.startswith(ExtraCallbacks.CUSTOM_BUY_PREFIX))
async def extra_custom_buy(call: CallbackQuery, session: AsyncSession) -> None:
    await call.answer()
    raw = (call.data or "").replace(ExtraCallbacks.CUSTOM_BUY_PREFIX, "", 1)
    parts = raw.split(":")
    if len(parts) != 2 or not parts[0].isdigit():
        await call.answer("Некорректный платёж 😕", show_alert=True)
        return

    credits = int(parts[0])
    method = parts[1]
    if credits < 200 or credits > 100000:
        await call.answer("Сумма должна быть от 200 до 100000", show_alert=True)
        return

    plan_name = make_custom_plan_name(credits)

    if method == "stars":
        await extra_buy_custom_stars(call, session, credits)
        return

    amount = credits
    currency = "RUB"
    platega_ok = await check_platega_health()
    if not platega_ok:
        if call.message:
            await edit_text_safe(
                call,
                "⚠️ Оплата картой/СБП/крипто временно недоступна.\n"
                "Попробуй позже или выбери оплату Stars.",
                reply_markup=extra_custom_buy_kb(credits, platega_available=False),
                parse_mode="HTML",
            )
        return

    try:
        client = build_platega_client()
    except Exception:
        logger.exception("extra_custom_buy: platega client init failed")
        await call.answer("Платёжный сервис не настроен", show_alert=True)
        return

    payload = {"tgUserId": call.from_user.id, "customCredits": credits}

    if method == "crypto":
        pay_method = 13
    elif method == "card":
        pay_method = 11
    else:
        pay_method = 2

    if call.message:
        await edit_text_safe(call, "🔥 Супер! Сейчас подготовлю оплату…", parse_mode="HTML")

    try:
        data = await client.create_payment_link(
            amount=amount,
            currency=currency,
            description=f"Custom credit top-up {credits}",
            payload=payload,
            payment_method=pay_method,
        )
    except Exception:
        logger.exception(
            "extra_custom_buy: failed to create payment credits=%s tg_id=%s",
            credits,
            call.from_user.id,
        )
        if call.message:
            await edit_text_safe(
                call,
                "Не удалось создать оплату 😕\n\nПопробуй ещё раз чуть позже.",
                reply_markup=extra_custom_buy_kb(credits, platega_available=platega_ok),
                parse_mode="HTML",
            )
        await call.answer(with_support("Ошибка платежного сервиса"), show_alert=True)
        return

    redirect = data.get("redirect")
    tx_id = data.get("transactionId")
    if not redirect or not tx_id:
        logger.error(
            "extra_custom_buy: invalid platega response tg_id=%s data=%s",
            call.from_user.id,
            data,
        )
        if call.message:
            await edit_text_safe(
                call,
                "Платёжный сервис вернул некорректный ответ 😕",
                reply_markup=extra_custom_buy_kb(credits, platega_available=platega_ok),
                parse_mode="HTML",
            )
        await call.answer(with_support("Ошибка ответа Platega"), show_alert=True)
        return

    payment = await create_pending_payment(
        session,
        tg_user_id=call.from_user.id,
        plan_name=plan_name,
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
            "Кредиты начислятся сразу после подтверждения ✅",
            reply_markup=extra_pay_poll_kb(redirect, payment.id),
            parse_mode="HTML",
        )


async def extra_buy_custom_stars(
    call: CallbackQuery, session: AsyncSession, credits: int
) -> None:
    del session
    stars_amount = _stars_for_credits(credits)
    payload = f"stars_custom:{credits}:{call.from_user.id}"
    title = f"Пополнение на {credits} кредитов"
    description = f"{credits} кредитов за {stars_amount} ⭐"

    if call.message:
        await call.message.answer_invoice(
            title=title,
            description=description,
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"{credits} кредитов", amount=stars_amount)],
        )
    await call.answer()


async def extra_buy_stars(
    call: CallbackQuery, session: AsyncSession, plan: Subscription
) -> None:

    stars_price = int(getattr(plan, "stars_price", 0) or 0)
    if stars_price <= 0:
        await call.answer("Оплата Stars недоступна для этого пакета", show_alert=True)
        return

    payload = f"stars:{plan.name}:{call.from_user.id}"
    title = f"Кредиты {plan.name}"
    description = f"{int(getattr(plan, 'credit_amount', 0) or 0)} кредитов"

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
    if not (payload.startswith("stars:") or payload.startswith("stars_custom:")):
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
    if not (payload.startswith("stars:") or payload.startswith("stars_custom:")):
        return

    parts = payload.split(":")
    if len(parts) < 3:
        return

    mode = parts[0]
    plan_name = parts[1]
    payload_tg_id = parts[2]
    tg_id = message.from_user.id

    if payload_tg_id.isdigit() and int(payload_tg_id) != tg_id:
        return

    if mode == "stars_custom":
        if not plan_name.isdigit():
            await message.answer("Некорректная сумма пополнения 😕")
            return
        credits = int(plan_name)
        await apply_credit_amount_to_user(session, tg_id, credits)
        await message.answer(
            f"✅ Оплата Stars подтверждена! Начислено {credits} кредитов 🎉",
            reply_markup=main_menu_kb(),
        )
        return
    else:
        plan = await get_plan(session, plan_name)
        if not plan:
            await message.answer("Пакет не найден 😕")
            return

        await apply_plan_to_user(session, tg_id, plan)
        await message.answer(
            f"✅ Оплата Stars подтверждена! Начислено {int(getattr(plan, 'credit_amount', 0) or 0)} кредитов 🎉",
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
        custom_credits = parse_custom_plan_credits(payment.plan_name)
        plan = None
        credited_amount = 0
        if custom_credits:
            await apply_credit_amount_to_user(session, call.from_user.id, custom_credits)
            credited_amount = custom_credits
        else:
            plan = await get_plan(session, payment.plan_name)
            if plan:
                await apply_plan_to_user(session, call.from_user.id, plan)
                credited_amount = int(getattr(plan, "credit_amount", 0) or 0)
        await mark_payment_status(session, payment, PaymentStatus.CONFIRMED)

        if call.message:
            await edit_text_safe(
                call,
                f"✅ Оплата подтверждена! Начислено {credited_amount} кредитов 🎉",
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
