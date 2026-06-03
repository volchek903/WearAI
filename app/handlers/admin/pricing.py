from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import AdminCallbacks, admin_menu_kb, admin_model_pricing_kb
from app.repository.admin import is_admin
from app.repository.app_settings import (
    MODEL_TITLES,
    get_agent_daily_free_limit,
    get_launch_daily_limit,
    get_pricing_markup_multiplier_pct,
    get_usd_to_rub_rate,
    list_model_pricing,
    set_agent_daily_free_limit,
    set_launch_daily_limit,
    set_model_price_credits,
)
from app.states.admin import (
    AdminAgentDailyLimitFSM,
    AdminLaunchLimitFSM,
    AdminModelPricingFSM,
)
from app.utils.tg_edit import edit_text_safe
from app.utils.support_text import with_support

from .common import ensure_admin, router


async def render_model_pricing(call: CallbackQuery, session: AsyncSession) -> None:
    pricing = await list_model_pricing(session)
    markup_pct = await get_pricing_markup_multiplier_pct(session)
    usd_to_rub = await get_usd_to_rub_rate(session)
    lines = [
        "💸 <b>Настройка цен моделей</b>",
        "",
        f"Курс USD->RUB для базового расчёта: <b>{usd_to_rub}</b>",
        f"Целевая наценка: <b>x{markup_pct / 100:.1f}</b>",
        "",
    ]
    for item in pricing:
        cost_rub = (item.provider_cost_usd * Decimal(usd_to_rub)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        margin_rub = (Decimal(item.user_price_credits) - cost_rub).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        unit = "кр./сек" if "per_second" in item.model_key else "кр."
        lines.append(
            f"• <b>{item.title}</b>: {item.user_price_credits} {unit} "
            f"(себестоимость {item.provider_cost_usd}$ / {cost_rub} ₽, +{margin_rub} ₽)"
        )
    await edit_text_safe(
        call,
        "\n".join(lines),
        reply_markup=admin_model_pricing_kb(pricing),
    )


@router.callback_query(F.data == AdminCallbacks.MODEL_PRICING)
async def admin_model_pricing(call: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_admin(call, session, "admin_panel.model_pricing"):
        return
    await render_model_pricing(call, session)
    await call.answer()


@router.callback_query(F.data.startswith(f"{AdminCallbacks.MODEL_PRICE_EDIT}:"))
async def admin_model_price_edit(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not await ensure_admin(call, session, "admin_panel.model_price_edit"):
        return
    model_key = (call.data or "").split(":", 3)[-1]
    if model_key not in MODEL_TITLES:
        await call.answer("Неизвестная модель", show_alert=True)
        return
    await state.set_state(AdminModelPricingFSM.waiting_value)
    await state.update_data(model_key=model_key)
    unit_hint = (
        " в кредитах за 1 секунду" if "per_second" in model_key else " в кредитах"
    )
    if call.message:
        await call.message.answer(
            f"Введите новую цену{unit_hint} для «{MODEL_TITLES[model_key]}» ✍️"
        )
    await call.answer()


@router.message(AdminModelPricingFSM.waiting_value)
async def admin_model_price_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    data = await state.get_data()
    model_key = data.get("model_key")
    if model_key not in MODEL_TITLES:
        await state.clear()
        await message.answer("Сессия редактирования потеряна.")
        return
    try:
        value = int((message.text or "").strip())
    except Exception:
        await message.answer("Нужно целое число. Введи ещё раз ✍️")
        return
    if value <= 0:
        await message.answer("Значение должно быть > 0")
        return
    await set_model_price_credits(session, model_key, value)
    await state.clear()
    unit_hint = " кр./сек." if "per_second" in model_key else " кр."
    await message.answer(
        f"Сохранено: {MODEL_TITLES[model_key]} = {value}{unit_hint}",
        reply_markup=admin_menu_kb(),
    )


@router.callback_query(F.data == AdminCallbacks.LAUNCH_DAILY_LIMIT)
async def admin_launch_daily_limit_start(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not await ensure_admin(call, session, "admin_panel.launch_daily_limit"):
        return
    current = await get_launch_daily_limit(session)
    await state.clear()
    await state.set_state(AdminLaunchLimitFSM.waiting_value)
    await edit_text_safe(
        call,
        f"Текущий лимит бесплатных генераций в день (Launch): {current}\n\n"
        "Введи новое число:",
        reply_markup=admin_menu_kb(),
    )
    await call.answer()


@router.message(AdminLaunchLimitFSM.waiting_value)
async def admin_launch_daily_limit_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not await is_admin(session, message.from_user.id):
        await message.answer("Недостаточно прав")
        return
    txt = (message.text or "").strip()
    if not txt.isdigit():
        await message.answer(
            "Нужно целое число. Попробуй ещё раз.",
            reply_markup=admin_menu_kb(),
        )
        return
    value = int(txt)
    if value < 0:
        await message.answer("Число не может быть отрицательным.")
        return
    await set_launch_daily_limit(session, value)
    await state.clear()
    await message.answer(
        f"✅ Лимит обновлён: {value}",
        reply_markup=admin_menu_kb(),
    )


@router.callback_query(F.data == AdminCallbacks.AGENT_DAILY_LIMIT)
async def admin_agent_daily_limit_start(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not await ensure_admin(call, session, "admin_panel.agent_daily_limit"):
        return
    current = await get_agent_daily_free_limit(session)
    await state.clear()
    await state.set_state(AdminAgentDailyLimitFSM.waiting_value)
    await edit_text_safe(
        call,
        f"Текущий лимит бесплатных запросов к агенту в день: {current}\n\n"
        "Введи новое число:",
        reply_markup=admin_menu_kb(),
    )
    await call.answer()


@router.message(AdminAgentDailyLimitFSM.waiting_value)
async def admin_agent_daily_limit_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not await is_admin(session, message.from_user.id):
        await message.answer("Недостаточно прав")
        return
    txt = (message.text or "").strip()
    if not txt.isdigit():
        await message.answer(
            "Нужно целое число. Попробуй ещё раз.",
            reply_markup=admin_menu_kb(),
        )
        return
    value = int(txt)
    if value < 0:
        await message.answer("Число не может быть отрицательным.")
        return
    await set_agent_daily_free_limit(session, value)
    await state.clear()
    await message.answer(
        f"✅ Лимит бесплатных запросов к агенту обновлён: {value}",
        reply_markup=admin_menu_kb(),
    )
