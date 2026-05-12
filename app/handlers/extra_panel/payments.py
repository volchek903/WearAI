from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from aiogram import F
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.extra import (
    ExtraCallbacks,
    extra_buy_kb,
    extra_custom_buy_kb,
    extra_pay_poll_kb,
)
from app.keyboards.menu import main_menu_kb
from app.models.payment import PaymentStatus
from app.models.subscription import Subscription
from app.repository.extra import get_plan
from app.repository.payments import (
    PaymentAlreadyProcessedError,
    PaymentPlanNotFoundError,
    PaymentUserNotFoundError,
    apply_credit_amount_to_user,
    apply_plan_to_user,
    confirm_payment_and_apply_credits,
    create_pending_payment,
    get_payment_by_id,
    make_custom_plan_name,
    mark_payment_status,
)
from app.services.platega import (
    build_platega_client,
    check_platega_health,
    normalize_payment_status,
)
from app.utils.support_text import with_support
from app.utils.tg_edit import edit_text_safe

from .common import logger, payment_tg_id, router, stars_for_credits


def _price_to_rub_int(value: object) -> int:
    price = Decimal(str(value or "0"))
    return max(0, int(price.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


@router.callback_query(F.data.startswith(ExtraCallbacks.BUY_PREFIX))
async def extra_buy(call: CallbackQuery, session: AsyncSession) -> None:
    await call.answer()
    raw = (call.data or "").replace(ExtraCallbacks.BUY_PREFIX, "", 1)
    parts = raw.split(":")
    if len(parts) != 2 or not parts[0].isdigit():
        await call.answer("Некорректный платёж 😕", show_alert=True)
        return
    plan = await session.get(Subscription, int(parts[0]))
    method = parts[1]

    if not plan:
        await call.answer("Пакет не найден в базе 😕", show_alert=True)
        return
    if method == "stars":
        await extra_buy_stars(call, session, plan)
        return

    amount = _price_to_rub_int(plan.price)
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
            currency="RUB",
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
        await call.answer(with_support("Ошибка платежного сервиса"), show_alert=True)
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
        currency="RUB",
        tx_id=tx_id,
        credit_amount_snapshot=int(getattr(plan, "credit_amount", 0) or 0),
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

    if method == "stars":
        await extra_buy_custom_stars(call, session, credits)
        return

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
            amount=credits,
            currency="RUB",
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
        plan_name=make_custom_plan_name(credits),
        amount=credits,
        currency="RUB",
        tx_id=tx_id,
        credit_amount_snapshot=credits,
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
    call: CallbackQuery,
    session: AsyncSession,
    credits: int,
) -> None:
    del session
    stars_amount = stars_for_credits(credits)
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
    call: CallbackQuery,
    session: AsyncSession,
    plan: Subscription,
) -> None:
    del session
    stars_price = int(getattr(plan, "stars_price", 0) or 0)
    if stars_price <= 0:
        await call.answer("Оплата Stars недоступна для этого пакета", show_alert=True)
        return

    payload = (
        f"stars:{plan.name}:{int(getattr(plan, 'credit_amount', 0) or 0)}:{call.from_user.id}"
    )
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
    payment = message.successful_payment
    if not payment or (payment.currency or "").upper() != "XTR":
        return

    payload = payment.invoice_payload or ""
    if not (payload.startswith("stars:") or payload.startswith("stars_custom:")):
        return

    parts = payload.split(":")
    if len(parts) < 3:
        return

    mode = parts[0]
    plan_name = parts[1]
    tg_id = message.from_user.id

    payload_tg_id = parts[2]
    snapshot_credits = 0
    if mode == "stars" and len(parts) >= 4:
        snapshot_raw = parts[2]
        payload_tg_id = parts[3]
        if snapshot_raw.isdigit():
            snapshot_credits = int(snapshot_raw)

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

    if snapshot_credits > 0:
        await apply_credit_amount_to_user(session, tg_id, snapshot_credits)
        await message.answer(
            f"✅ Оплата Stars подтверждена! Начислено {snapshot_credits} кредитов 🎉",
            reply_markup=main_menu_kb(),
        )
        return

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
    payment_id_str = (call.data or "").replace(ExtraCallbacks.CHECK_PREFIX, "", 1)
    if not payment_id_str.isdigit():
        await call.answer("Некорректный идентификатор платежа 😕", show_alert=True)
        return

    payment = await get_payment_by_id(session, int(payment_id_str))
    if not payment:
        await call.answer("Платёж не найден 😕", show_alert=True)
        return

    owner_tg_id = payment_tg_id(payment)
    if not owner_tg_id:
        await call.answer("Не удалось определить пользователя платежа 😕", show_alert=True)
        return
    if owner_tg_id != call.from_user.id:
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
        owner_tg_id,
        raw_status,
        status,
    )

    if status == "CONFIRMED":
        try:
            credited_amount = await confirm_payment_and_apply_credits(session, payment)
        except PaymentAlreadyProcessedError:
            await call.answer("✅ Уже подтверждено — пакет активирован", show_alert=True)
            return
        except PaymentPlanNotFoundError:
            logger.exception(
                "extra_check_payment: plan not found plan_name=%s payment_id=%s",
                payment.plan_name,
                payment.id,
            )
            await call.answer(
                "Платёж найден, но пакет настроен некорректно. Напиши в поддержку 💬",
                show_alert=True,
            )
            return
        except PaymentUserNotFoundError:
            logger.exception(
                "extra_check_payment: user not found payment_id=%s tg_id=%s",
                payment.id,
                call.from_user.id,
            )
            await call.answer(
                "Платёж найден, но не удалось активировать пакет. Напиши в поддержку 💬",
                show_alert=True,
            )
            return

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
