from __future__ import annotations

from decimal import Decimal, InvalidOperation

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import (
    AdminCallbacks,
    admin_menu_kb,
    admin_package_actions_kb,
    admin_package_delete_confirm_kb,
    admin_package_fields_kb,
    admin_packages_kb,
)
from app.keyboards.confirm import ConfirmCallbacks, yes_no_kb
from app.models.subscription import Subscription
from app.repository.extra import get_all_plans
from app.states.admin import AdminPackageCreateFSM, AdminPackagesFSM
from app.utils.tg_edit import edit_text_safe

from .common import ensure_admin, new_plan_preview, plan_info, router


@router.callback_query(F.data == AdminCallbacks.PACKAGES)
async def admin_packages(call: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_admin(call, session, "admin_panel.packages"):
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
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not await ensure_admin(call, session, "admin_panel.package_create"):
        return
    await state.clear()
    await state.set_state(AdminPackageCreateFSM.name)
    await edit_text_safe(call, "Введите название пакета ✍️", reply_markup=None)
    await call.answer()


@router.message(AdminPackageCreateFSM.name)
async def admin_package_create_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Название слишком короткое. Введи ещё раз ✍️")
        return
    await state.update_data(name=name)
    await state.set_state(AdminPackageCreateFSM.photo_generations)
    await message.answer("Сколько кредитов начисляет пакет? ✍️")


@router.message(AdminPackageCreateFSM.photo_generations)
async def admin_package_create_credits(message: Message, state: FSMContext) -> None:
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
async def admin_package_create_price(message: Message, state: FSMContext) -> None:
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
async def admin_package_create_stars(message: Message, state: FSMContext) -> None:
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
    await message.answer(
        new_plan_preview(await state.get_data()),
        reply_markup=yes_no_kb(
            yes_text="✅ Создать",
            no_text="❌ Отменить",
            no_style="danger",
        ),
    )


@router.callback_query(
    AdminPackageCreateFSM.confirm,
    F.data.in_({ConfirmCallbacks.YES, ConfirmCallbacks.NO}),
)
async def admin_package_create_confirm(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
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

    exists = await session.scalar(select(Subscription.id).where(Subscription.name == name))
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
        plan_info(plan),
        reply_markup=admin_package_actions_kb(plan.id),
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{AdminCallbacks.PACKAGE_PICK}:"))
async def admin_package_pick(call: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_admin(call, session, "admin_panel.package_pick"):
        return
    plan_id = (call.data or "").split(":", 3)[-1]
    if not plan_id.isdigit():
        await call.answer("Некорректный пакет 😕", show_alert=True)
        return
    plan = await session.get(Subscription, int(plan_id))
    if not plan:
        await call.answer("Пакет не найден 😕", show_alert=True)
        return
    await edit_text_safe(
        call,
        plan_info(plan),
        reply_markup=admin_package_actions_kb(plan.id),
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{AdminCallbacks.PACKAGE_EDIT}:"))
async def admin_package_edit(call: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_admin(call, session, "admin_panel.package_edit"):
        return
    plan_id = (call.data or "").split(":", 3)[-1]
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


@router.callback_query(F.data.startswith(f"{AdminCallbacks.PACKAGE_DELETE}:"))
async def admin_package_delete_start(call: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_admin(call, session, "admin_panel.package_delete_start"):
        return
    plan_id = (call.data or "").split(":", 3)[-1]
    if not plan_id.isdigit():
        await call.answer("Некорректный пакет 😕", show_alert=True)
        return
    plan = await session.get(Subscription, int(plan_id))
    if not plan:
        await call.answer("Пакет не найден 😕", show_alert=True)
        return
    if plan.name == "Base":
        await call.answer("Системный пакет Base удалять нельзя", show_alert=True)
        return
    await edit_text_safe(
        call,
        "⚠️ Вы уверены, что хотите удалить пакет?\n\n"
        f"Пакет: <b>{plan.name}</b>\n"
        "Действие необратимо.",
        reply_markup=admin_package_delete_confirm_kb(plan.id),
    )
    await call.answer()


@router.callback_query(
    F.data.startswith(f"{AdminCallbacks.PACKAGE_DELETE_CONFIRM}:")
)
async def admin_package_delete_confirm(
    call: CallbackQuery,
    session: AsyncSession,
) -> None:
    if not await ensure_admin(call, session, "admin_panel.package_delete_confirm"):
        return
    parts = (call.data or "").split(":")
    if len(parts) < 5:
        await call.answer("Некорректная команда 😕", show_alert=True)
        return
    plan_id_str = parts[-2]
    decision = parts[-1]
    if not plan_id_str.isdigit():
        await call.answer("Некорректный пакет 😕", show_alert=True)
        return
    if decision != "yes":
        await call.answer()
        return

    plan = await session.get(Subscription, int(plan_id_str))
    if not plan:
        await call.answer("Пакет уже удалён", show_alert=True)
        plans = await get_all_plans(session)
        await edit_text_safe(
            call,
            "📦 <b>Пакеты</b>\n\nВыбери пакет для просмотра/редактирования 👇",
            reply_markup=admin_packages_kb(plans),
        )
        return
    if plan.name == "Base":
        await call.answer("Системный пакет Base удалять нельзя", show_alert=True)
        return

    try:
        await session.delete(plan)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        await edit_text_safe(
            call,
            "❌ Пакет нельзя удалить: есть связанные данные "
            "(активные/исторические подписки или логи генераций).",
            reply_markup=admin_package_actions_kb(int(plan_id_str)),
        )
        await call.answer()
        return

    plans = await get_all_plans(session)
    await edit_text_safe(
        call,
        "✅ Пакет удалён.\n\n📦 <b>Пакеты</b>\n\nВыбери пакет для просмотра/редактирования 👇",
        reply_markup=admin_packages_kb(plans),
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{AdminCallbacks.PACKAGE_FIELD}:"))
async def admin_package_field(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not await ensure_admin(call, session, "admin_panel.package_field"):
        return
    parts = (call.data or "").split(":")
    if len(parts) < 5:
        await call.answer("Некорректный параметр 😕", show_alert=True)
        return
    plan_id_str = parts[-2]
    field = parts[-1]
    if not plan_id_str.isdigit():
        await call.answer("Некорректный пакет 😕", show_alert=True)
        return
    if field not in {"name", "credit_amount", "price", "stars_price"}:
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
    else:
        prompt = "Введите новую цену в звёздах (целое число) ✍️"

    if call.message:
        await call.message.answer(prompt)
    await call.answer()


@router.message(AdminPackagesFSM.waiting_value)
async def admin_package_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
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
            yes_text="✅ Сохранить",
            no_text="❌ Отменить",
            no_style="danger",
        ),
    )


@router.callback_query(
    AdminPackagesFSM.confirm,
    F.data.in_({ConfirmCallbacks.YES, ConfirmCallbacks.NO}),
)
async def admin_package_confirm(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
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
                Subscription.name == name,
                Subscription.id != plan.id,
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
        plan_info(plan),
        reply_markup=admin_package_actions_kb(plan.id),
    )
    await call.answer()
