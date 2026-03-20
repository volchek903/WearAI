from __future__ import annotations

import asyncio
import logging
import os
import sys

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import (
    AdminCallbacks,
    admin_menu_kb,
    admin_model_pricing_kb,
    admin_users_nav_kb,
    admin_promo_kb,
    admin_packages_kb,
    admin_package_actions_kb,
    admin_package_fields_kb,
)
from app.keyboards.confirm import yes_no_kb, ConfirmCallbacks
from app.keyboards.utils import add_button
from app.repository.admin import is_admin, get_users_page, get_users_stats
from app.repository.admin_actions import log_admin_action
from app.repository.analytics import (
    get_revenue_stats,
    get_section_breakdown,
    get_top_sections,
    get_user_entry_stats,
)
from app.repository.app_settings import (
    MODEL_TITLES,
    get_launch_daily_limit,
    get_pricing_markup_multiplier_pct,
    get_usd_to_rub_rate,
    list_model_pricing,
    set_launch_daily_limit,
    set_model_price_credits,
)
from app.models.subscription import Subscription
from app.repository.extra import get_all_plans
from app.repository.promo import create_promo_code, get_last_promo_codes, PromoError
from app.repository.referrals import get_top_referrers_last_week
from app.states.admin import (
    AdminPromoFSM,
    AdminModelPricingFSM,
    AdminPackagesFSM,
    AdminPackageCreateFSM,
    AdminLaunchLimitFSM,
)
from app.utils.tg_edit import edit_text_safe
from app.utils.support_text import with_support

router = Router()
logger = logging.getLogger(__name__)


async def _ensure_admin(call: CallbackQuery, session: AsyncSession, action: str) -> bool:
    tg_id = call.from_user.id
    if await is_admin(session, tg_id):
        await log_admin_action(
            session, tg_id=tg_id, action=action, data=str(call.data or "")
        )
        return True
    logger.warning("ADMIN_DENY action=%s tg_id=%s data=%s", action, tg_id, call.data)
    await call.answer("Недостаточно прав", show_alert=True)
    return False


async def _restart_process(message: Message) -> None:
    # Give the bot time to send the confirmation message before restarting.
    await message.answer("🔄 Перезапускаю бота…")
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)


@router.message(Command("admin"))
async def admin_entry(message: Message, session: AsyncSession) -> None:
    if not await is_admin(session, message.from_user.id):
        return
    await message.answer("⚙️ Админка", reply_markup=admin_menu_kb())


@router.message(Command("restart"))
async def admin_restart(message: Message, session: AsyncSession) -> None:
    if message.from_user.id != 830091750:
        return
    await _restart_process(message)


@router.callback_query(F.data == AdminCallbacks.STATS)
async def admin_stats(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.stats"):
        return
    total_users, active_subs, total_photos, total_videos = await get_users_stats(
        session
    )
    payments_count, revenue_rub = await get_revenue_stats(session)
    entries = await get_user_entry_stats(session)

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"💰 Заработано: <code>{revenue_rub} ₽</code>\n"
        f"🧾 Оплат подтверждено: <code>{payments_count}</code>\n\n"
        f"👥 Пользователей за всё время: <code>{entries['all_time']}</code>\n"
        f"🗓 За 30 дней: <code>{entries['month']}</code>\n"
        f"📅 За 7 дней: <code>{entries['week']}</code>\n"
        f"⏱ За 24 часа: <code>{entries['day']}</code>\n\n"
        f"👥 Всего пользователей в БД: <code>{total_users}</code>\n"
        f"✅ Активных подписок: <code>{active_subs}</code>\n"
        f"🖼️ Сгенерировано фото: <code>{total_photos}</code>\n"
        f"🎬 Сгенерировано видео: <code>{total_videos}</code>"
    )

    await edit_text_safe(call, text, reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.ANALYTICS)
async def admin_analytics(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.analytics"):
        return

    top_sections = await get_top_sections(session, limit=5)
    breakdown = await get_section_breakdown(session)

    lines = ["📈 <b>Аналитика шаблонов</b>", ""]
    lines.append("🏆 Топ 5 шаблонов / разделов:")
    if not top_sections:
        lines.append("Пока нет данных.")
    else:
        for idx, (section, cnt) in enumerate(top_sections, start=1):
            lines.append(f"{idx}. <b>{section}</b> — {cnt}")

    lines.append("")
    lines.append("🧩 По разделам:")
    if not breakdown:
        lines.append("Пока нет данных.")
    else:
        for section, photo_cnt, video_cnt, total_cnt in breakdown:
            lines.append(
                f"• <b>{section}</b> — всего {total_cnt}, фото {photo_cnt}, видео {video_cnt}"
            )

    await edit_text_safe(call, "\n".join(lines), reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.TOP_REFERRALS)
async def admin_top_referrals(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.top_referrals"):
        return

    rows = await get_top_referrers_last_week(session, limit=10)
    if not rows:
        text = "🏆 <b>Топ рефералов</b>\n\nЗа последние 7 дней нет рефералов."
        await edit_text_safe(call, text, reply_markup=admin_menu_kb())
        await call.answer()
        return

    lines = []
    for i, r in enumerate(rows, start=1):
        username = r.get("username")
        tg_id = r.get("tg_id")
        count = r.get("count", 0)
        who = f"@{username}" if username else f"tg_id {tg_id}"
        lines.append(f"{i}. {who} — {count}")

    text = "🏆 <b>Топ рефералов за 7 дней</b>\n\n" + "\n".join(lines)
    await edit_text_safe(call, text, reply_markup=admin_menu_kb())
    await call.answer()


def _plan_info(plan: Subscription) -> str:
    price = "Бесплатно" if float(plan.price) == 0 else f"{int(float(plan.price))} ₽"
    stars_price = int(getattr(plan, "stars_price", 0) or 0)
    stars = "Бесплатно" if stars_price == 0 else f"{stars_price} ⭐"
    return (
        "📦 <b>Пакет</b>\n\n"
        f"Название: <b>{plan.name}</b>\n"
        f"Кредиты: <b>{int(getattr(plan, 'credit_amount', 0) or 0)}</b>\n"
        f"Цена: <b>{price}</b>\n"
        f"Цена в ⭐: <b>{stars}</b>"
    )


def _new_plan_preview(data: dict) -> str:
    name = str(data.get("name", "")).strip()
    credits = int(data.get("credit_amount") or 0)
    price = data.get("price")
    stars_price = int(data.get("stars_price") or 0)
    if price is None or Decimal(price) == 0:
        price_text = "Бесплатно"
    else:
        price_text = f"{int(price)} ₽"
    stars_text = "Бесплатно" if stars_price == 0 else f"{stars_price} ⭐"
    return (
        "📦 <b>Новый пакет</b>\n\n"
        f"Название: <b>{name}</b>\n"
        f"Кредиты: <b>{credits}</b>\n"
        f"Цена: <b>{price_text}</b>\n"
        f"Цена в ⭐: <b>{stars_text}</b>\n\n"
        "Все верно?"
    )


async def _render_model_pricing(call: CallbackQuery, session: AsyncSession) -> None:
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
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        margin_rub = (Decimal(item.user_price_credits) - cost_rub).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        lines.append(
            f"• <b>{item.title}</b>: {item.user_price_credits} кр. "
            f"(себестоимость {item.provider_cost_usd}$ / {cost_rub} ₽, +{margin_rub} ₽)"
        )
    await edit_text_safe(
        call,
        "\n".join(lines),
        reply_markup=admin_model_pricing_kb(pricing),
    )


@router.callback_query(F.data == AdminCallbacks.MODEL_PRICING)
async def admin_model_pricing(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.model_pricing"):
        return
    await _render_model_pricing(call, session)
    await call.answer()


@router.callback_query(F.data.startswith(f"{AdminCallbacks.MODEL_PRICE_EDIT}:"))
async def admin_model_price_edit(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_panel.model_price_edit"):
        return
    model_key = (call.data or "").split(":", 3)[-1]
    if model_key not in MODEL_TITLES:
        await call.answer("Неизвестная модель", show_alert=True)
        return
    await state.set_state(AdminModelPricingFSM.waiting_value)
    await state.update_data(model_key=model_key)
    if call.message:
        await call.message.answer(
            f"Введите новую цену в кредитах для «{MODEL_TITLES[model_key]}» ✍️"
        )
    await call.answer()


@router.message(AdminModelPricingFSM.waiting_value)
async def admin_model_price_value(
    message: Message, state: FSMContext, session: AsyncSession
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
    await message.answer(
        f"Сохранено: {MODEL_TITLES[model_key]} = {value} кр.",
        reply_markup=admin_menu_kb(),
    )


@router.callback_query(F.data == AdminCallbacks.PACKAGES)
async def admin_packages(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.packages"):
        return
    plans = await get_all_plans(session)
    await edit_text_safe(
        call,
        "📦 <b>Пакеты</b>\n\nВыбери пакет для просмотра/редактирования 👇",
        reply_markup=admin_packages_kb(plans),
    )
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.PACKAGE_CREATE)
async def admin_package_create_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_panel.package_create"):
        return
    await state.clear()
    await state.set_state(AdminPackageCreateFSM.name)
    await edit_text_safe(call, "Введите название пакета ✍️", reply_markup=None)
    await call.answer()


@router.message(AdminPackageCreateFSM.name)
async def admin_package_create_name(
    message: Message, state: FSMContext
) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Название слишком короткое. Введи ещё раз ✍️")
        return
    await state.update_data(name=name)
    await state.set_state(AdminPackageCreateFSM.photo_generations)
    await message.answer("Сколько кредитов начисляет пакет? ✍️")


@router.message(AdminPackageCreateFSM.photo_generations)
async def admin_package_create_credits(
    message: Message, state: FSMContext
) -> None:
    try:
        credits = int((message.text or "").strip())
    except Exception:
        await message.answer("Нужно целое число. Введи ещё раз ✍️")
        return
    if credits < 0:
        await message.answer("Число должно быть >= 0")
        return
    await state.update_data(credit_amount=credits)
    await state.set_state(AdminPackageCreateFSM.price)
    await message.answer("Введите цену в рублях (например 750) ✍️")


@router.message(AdminPackageCreateFSM.price)
async def admin_package_create_price(
    message: Message, state: FSMContext
) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Нужно число. Введи ещё раз ✍️")
        return
    cleaned = raw.replace(",", ".")
    try:
        price = Decimal(cleaned)
    except InvalidOperation:
        await message.answer("Нужно число. Введи ещё раз ✍️")
        return
    if price < 0:
        await message.answer("Цена должна быть >= 0")
        return
    await state.update_data(price=price)
    await state.set_state(AdminPackageCreateFSM.stars_price)
    await message.answer("Введите цену в звёздах (целое число) ✍️")


@router.message(AdminPackageCreateFSM.stars_price)
async def admin_package_create_stars(
    message: Message, state: FSMContext
) -> None:
    try:
        stars_price = int((message.text or "").strip())
    except Exception:
        await message.answer("Нужно целое число. Введи ещё раз ✍️")
        return
    if stars_price < 0:
        await message.answer("Число должно быть >= 0")
        return
    await state.update_data(stars_price=stars_price)
    await state.set_state(AdminPackageCreateFSM.confirm)
    data = await state.get_data()
    await message.answer(
        _new_plan_preview(data),
        reply_markup=yes_no_kb(
            yes_text="✅ Создать", no_text="❌ Отменить", no_style="danger"
        ),
    )


@router.callback_query(
    AdminPackageCreateFSM.confirm, F.data.in_({ConfirmCallbacks.YES, ConfirmCallbacks.NO})
)
async def admin_package_create_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if call.data == ConfirmCallbacks.NO:
        await state.clear()
        await edit_text_safe(call, "⚙️ Админка", reply_markup=admin_menu_kb())
        await call.answer()
        return

    data = await state.get_data()
    name = str(data.get("name", "")).strip()
    if not name:
        await state.clear()
        await call.answer("Сессия создания потеряна", show_alert=True)
        return

    exists = await session.scalar(
        select(Subscription.id).where(Subscription.name == name)
    )
    if exists:
        await call.answer("Пакет с таким названием уже существует", show_alert=True)
        return

    plan = Subscription(
        name=name,
        duration_days=0,
        photo_generations=0,
        video_generations=0,
        credit_amount=int(data.get("credit_amount") or 0),
        price=Decimal(data.get("price") or 0),
        stars_price=int(data.get("stars_price") or 0),
    )
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    await state.clear()

    await edit_text_safe(
        call,
        _plan_info(plan),
        reply_markup=admin_package_actions_kb(plan.id),
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{AdminCallbacks.PACKAGE_PICK}:"))
async def admin_package_pick(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.package_pick"):
        return
    raw = call.data or ""
    plan_id = raw.split(":", 3)[-1]
    if not plan_id.isdigit():
        await call.answer("Некорректный пакет 😕", show_alert=True)
        return
    plan = await session.get(Subscription, int(plan_id))
    if not plan:
        await call.answer("Пакет не найден 😕", show_alert=True)
        return
    await edit_text_safe(
        call,
        _plan_info(plan),
        reply_markup=admin_package_actions_kb(plan.id),
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{AdminCallbacks.PACKAGE_EDIT}:"))
async def admin_package_edit(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.package_edit"):
        return
    raw = call.data or ""
    plan_id = raw.split(":", 3)[-1]
    if not plan_id.isdigit():
        await call.answer("Некорректный пакет 😕", show_alert=True)
        return
    plan = await session.get(Subscription, int(plan_id))
    if not plan:
        await call.answer("Пакет не найден 😕", show_alert=True)
        return
    await edit_text_safe(
        call,
        "Что хотите менять? 👇",
        reply_markup=admin_package_fields_kb(plan.id),
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{AdminCallbacks.PACKAGE_FIELD}:"))
async def admin_package_field(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_panel.package_field"):
        return
    raw = call.data or ""
    parts = raw.split(":")
    if len(parts) < 5:
        await call.answer("Некорректный параметр 😕", show_alert=True)
        return
    plan_id_str = parts[-2]
    field = parts[-1]
    if not plan_id_str.isdigit():
        await call.answer("Некорректный пакет 😕", show_alert=True)
        return
    if field not in {
        "name",
        "credit_amount",
        "price",
        "stars_price",
    }:
        await call.answer("Некорректное поле 😕", show_alert=True)
        return

    await state.set_state(AdminPackagesFSM.waiting_value)
    await state.update_data(plan_id=int(plan_id_str), field=field)

    if field == "name":
        prompt = "Введите новое название пакета ✍️"
    elif field == "credit_amount":
        prompt = "Введите новое количество кредитов (целое число) ✍️"
    elif field == "price":
        prompt = "Введите новую цену в рублях (например 750) ✍️"
    elif field == "stars_price":
        prompt = "Введите новую цену в звёздах (целое число) ✍️"
    else:
        prompt = "Введите новое значение ✍️"

    if call.message:
        await call.message.answer(prompt)
    await call.answer()


@router.message(AdminPackagesFSM.waiting_value)
async def admin_package_value(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    plan_id = data.get("plan_id")
    field = data.get("field")
    if not plan_id or not field:
        await state.clear()
        await message.answer("Сессия редактирования потеряна. Начни заново.")
        return

    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Нужно значение. Введи ещё раз ✍️")
        return

    if field == "name":
        new_value = raw
        if len(new_value) < 2:
            await message.answer("Название слишком короткое. Введи ещё раз.")
            return
    elif field == "price":
        cleaned = raw.replace(",", ".")
        try:
            new_value = Decimal(cleaned)
        except InvalidOperation:
            await message.answer("Нужно число. Введи ещё раз ✍️")
            return
        if new_value < 0:
            await message.answer("Цена должна быть >= 0")
            return
    else:
        try:
            new_value = int(raw)
        except Exception:
            await message.answer("Нужно целое число. Введи ещё раз ✍️")
            return
        if new_value < 0:
            await message.answer("Число должно быть >= 0")
            return

    await state.set_state(AdminPackagesFSM.confirm)
    await state.update_data(new_value=new_value)
    await message.answer(
        "Сохранить изменения? ✅",
        reply_markup=yes_no_kb(
            yes_text="✅ Сохранить", no_text="❌ Отменить", no_style="danger"
        ),
    )


@router.callback_query(
    AdminPackagesFSM.confirm, F.data.in_({ConfirmCallbacks.YES, ConfirmCallbacks.NO})
)
async def admin_package_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    plan_id = data.get("plan_id")
    field = data.get("field")
    new_value = data.get("new_value")

    if call.data == ConfirmCallbacks.NO:
        await state.clear()
        if plan_id:
            await edit_text_safe(
                call,
                "Что хотите менять? 👇",
                reply_markup=admin_package_fields_kb(int(plan_id)),
            )
        await call.answer()
        return

    if not plan_id or not field:
        await state.clear()
        await call.answer("Сессия редактирования потеряна", show_alert=True)
        return

    plan = await session.get(Subscription, int(plan_id))
    if not plan:
        await state.clear()
        await call.answer("Пакет не найден 😕", show_alert=True)
        return

    if field == "name":
        name = str(new_value).strip()
        exists = await session.scalar(
            select(Subscription.id).where(
                Subscription.name == name, Subscription.id != plan.id
            )
        )
        if exists:
            await call.answer("Пакет с таким названием уже существует", show_alert=True)
            return
        plan.name = name
    elif field == "credit_amount":
        plan.credit_amount = int(new_value)
    elif field == "price":
        plan.price = Decimal(new_value)
    elif field == "stars_price":
        plan.stars_price = int(new_value)

    await session.commit()
    await session.refresh(plan)
    await state.clear()

    await edit_text_safe(
        call,
        _plan_info(plan),
        reply_markup=admin_package_actions_kb(plan.id),
    )
    await call.answer()


def _parse_users_page(data: str) -> int:
    try:
        _, page = data.rsplit(":", 1)
        return max(1, int(page))
    except Exception:
        return 1


async def _render_users_page(
    call: CallbackQuery, session: AsyncSession, page: int
) -> None:
    limit = 10
    offset = (page - 1) * limit
    rows, total_users = await get_users_page(session, limit=limit, offset=offset)

    if not rows:
        text = "👥 <b>Пользователи</b>\n\nПока пусто 💤"
        reply_markup = admin_menu_kb()
    else:
        lines: list[str] = []
        for uid, tg_id, username, created_at, credits, free_credits, photos, videos in rows:
            uname = username or "-"
            lines.append(
                f"• id={uid} tg={tg_id} @{uname} ({created_at:%Y-%m-%d}) "
                f"осн={int(credits or 0)} free={int(free_credits or 0)} "
                f"фото={int(photos or 0)} видео={int(videos or 0)}"
            )
        total_pages = max(1, (total_users + limit - 1) // limit)
        text = (
            f"👥 <b>Пользователи</b> (стр. {page}/{total_pages})\n\n"
            + "\n".join(lines)
        )
        reply_markup = admin_users_nav_kb(
            page=page,
            has_prev=page > 1,
            has_next=offset + limit < total_users,
        )

    await edit_text_safe(call, text, reply_markup=reply_markup)
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.USERS)
async def admin_users(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.users"):
        return
    await _render_users_page(call, session, page=1)


@router.callback_query(F.data.startswith(f"{AdminCallbacks.USERS_PAGE}:"))
async def admin_users_page(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.users_page"):
        return
    page = _parse_users_page(call.data or "")
    await _render_users_page(call, session, page=page)


@router.callback_query(F.data == AdminCallbacks.BACK)
async def admin_back(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.back"):
        return
    await edit_text_safe(call, "⚙️ Админка", reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.PROMO)
async def admin_promo_menu(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.promo_menu"):
        return
    await edit_text_safe(call, "🎟 Промокоды", reply_markup=admin_promo_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.LAUNCH_DAILY_LIMIT)
async def admin_launch_daily_limit_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_panel.launch_daily_limit"):
        return
    cur = await get_launch_daily_limit(session)
    await state.clear()
    await state.set_state(AdminLaunchLimitFSM.waiting_value)
    await edit_text_safe(
        call,
        f"Текущий лимит бесплатных генераций в день (Launch): {cur}\n\n"
        "Введи новое число:",
        reply_markup=admin_menu_kb(),
    )
    await call.answer()


@router.message(AdminLaunchLimitFSM.waiting_value)
async def admin_launch_daily_limit_value(
    message: Message, state: FSMContext, session: AsyncSession
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


@router.callback_query(F.data == AdminCallbacks.CREATE_PROMO)
async def admin_promo_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_panel.create_promo"):
        return
    await state.clear()
    await state.set_state(AdminPromoFSM.code)
    await edit_text_safe(call, "Введи промокод ✍️")
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.LIST_PROMO)
async def admin_promo_list(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_panel.promo_list"):
        return
    promos = await get_last_promo_codes(session, limit=10)
    if not promos:
        text = "🎟 <b>Промокоды</b>\n\nПока пусто 💤"
    else:
        lines: list[str] = []
        for p in promos:
            lines.append(
                f"• <code>{p.code}</code> "
                f"кредиты={int(getattr(p, 'bonus_credits', 0) or 0)} "
                f"фото={p.bonus_photo} видео={p.bonus_video} "
                f"использовано {p.used_count}/{p.max_uses}"
            )
        text = "🎟 <b>Последние 10 промокодов</b>\n\n" + "\n".join(lines)
    await edit_text_safe(call, text, reply_markup=admin_promo_kb())
    await call.answer()


@router.message(AdminPromoFSM.code)
async def admin_promo_code_in(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip()
    if not code:
        await message.answer("Промокод пустой. Введи ещё раз ✍️")
        return
    await state.update_data(code=code)
    await state.set_state(AdminPromoFSM.credit_amount)
    await message.answer("Сколько кредитов выдаёт промокод?")


@router.message(AdminPromoFSM.credit_amount)
async def admin_promo_credit_amount(message: Message, state: FSMContext) -> None:
    try:
        count = int((message.text or "").strip())
    except Exception:
        await message.answer("Нужно число. Введи ещё раз ✍️")
        return
    if count <= 0:
        await message.answer("Число должно быть > 0")
        return
    await state.update_data(credit_amount=count)
    await state.set_state(AdminPromoFSM.max_uses)
    await message.answer("Сколько пользователей может активировать промокод?")


@router.message(AdminPromoFSM.max_uses)
async def admin_promo_max_uses(message: Message, state: FSMContext) -> None:
    try:
        count = int((message.text or "").strip())
    except Exception:
        await message.answer("Нужно число. Введи ещё раз ✍️")
        return
    if count <= 0:
        await message.answer("Число должно быть > 0")
        return

    data = await state.get_data()
    code = data.get("code")
    credit_amount = int(data.get("credit_amount") or 0)

    await state.update_data(max_uses=count)
    await state.set_state(AdminPromoFSM.confirm)

    await message.answer(
        "Проверь данные промокода:\n\n"
        f"Код: <b>{code}</b>\n"
        f"Кредитов: <b>{credit_amount}</b>\n"
        f"Лимит активаций: <b>{count}</b>\n\n"
        "Всё верно?",
        reply_markup=yes_no_kb(
            yes_text="✅ Создать", no_text="❌ Отменить", no_style="danger"
        ),
    )


@router.callback_query(AdminPromoFSM.confirm, F.data == ConfirmCallbacks.NO)
async def admin_promo_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_text_safe(call, "Создание промокода отменено.", reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(AdminPromoFSM.confirm, F.data == ConfirmCallbacks.YES)
async def admin_promo_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    code = data.get("code") or ""
    credit_amount = int(data.get("credit_amount") or 0)
    max_uses = int(data.get("max_uses") or 0)

    try:
        await create_promo_code(
            session,
            code=code,
            bonus_credits=credit_amount,
            max_uses=max_uses,
        )
    except PromoError as e:
        await edit_text_safe(
            call, with_support(f"Ошибка: {e}"), reply_markup=admin_menu_kb()
        )
        await state.clear()
        await call.answer()
        return

    await state.clear()
    await edit_text_safe(call, "✅ Промокод создан.", reply_markup=admin_menu_kb())
    await call.answer()
