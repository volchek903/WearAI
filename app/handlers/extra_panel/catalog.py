from __future__ import annotations

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.extra import (
    ExtraCallbacks,
    extra_buy_kb,
    extra_custom_buy_kb,
    extra_menu_kb,
)
from app.keyboards.menu import MenuCallbacks
from app.models.subscription import Subscription
from app.repository.extra import (
    get_active_plan_name,
    get_active_remaining,
    get_all_plans,
    get_user,
)
from app.repository.generations import ensure_default_subscription
from app.services.platega import check_platega_health
from app.utils.tg_callback import safe_answer
from app.utils.tg_edit import edit_text_safe

from .common import (
    CustomCreditsFlow,
    custom_pitch,
    extra_text,
    logger,
    package_pitch,
    purchasable_plans,
    router,
    table_html,
)


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
                session,
                user.id,
            )

        plans = await get_all_plans(session)
        table = table_html(plans)
        menu_plans = purchasable_plans(plans)

        if call.message:
            await edit_text_safe(
                call,
                extra_text(
                    current_name,
                    paid_credit_balance,
                    free_credit_balance,
                    table,
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
    plan = await session.get(Subscription, int(raw))
    if not plan:
        await call.answer("Пакет не найден в базе 😕", show_alert=True)
        return

    platega_ok = await check_platega_health()
    text = package_pitch(plan.name, plan)
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
async def extra_custom_amount_value(message: Message, state: FSMContext) -> None:
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
    platega_ok = await check_platega_health()
    text = custom_pitch(credits)
    if not platega_ok:
        text += "\n\n⚠️ Оплата картой/СБП/крипто временно недоступна. Доступна оплата Stars."
    await message.answer(
        text,
        reply_markup=extra_custom_buy_kb(credits, platega_available=platega_ok),
        parse_mode="HTML",
    )
