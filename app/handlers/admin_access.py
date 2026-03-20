from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import AdminCallbacks, admin_access_kb, admin_menu_kb
from app.keyboards.confirm import ConfirmCallbacks, yes_no_kb
from app.keyboards.utils import add_button
from app.repository.access import (
    get_user_by_tg_id,
    is_user_admin,
    add_admin,
    remove_admin,
    give_subscription_plan,  # ✅ NEW
)
from app.repository.admin import is_admin
from app.repository.admin_actions import log_admin_action
from app.repository.extra import get_all_plans  # ✅ NEW: планы из таблицы subscription
from app.states.admin_access import AdminAccessFSM
from app.utils.tg_edit import edit_text_safe

router = Router()
logger = logging.getLogger(__name__)

# callback_data для выбора плана
SUB_PICK_PREFIX = "admin_access:pick_sub:"


def _plans_kb(plans) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in plans:
        # можно сделать красивее: f"{p.name} · {p.duration_days}д · {p.video_generations}/{p.photo_generations}"
        add_button(kb, text=f"📦 {p.name}", callback_data=f"{SUB_PICK_PREFIX}{p.id}")
    add_button(kb, text="⬅️ Назад", callback_data=AdminCallbacks.BACK, style="danger")
    kb.adjust(1)
    return kb.as_markup()


async def _ensure_admin(call_or_message, session: AsyncSession, action: str) -> bool:
    tg_id = getattr(call_or_message.from_user, "id", None)
    if tg_id is None:
        return False
    if await is_admin(session, tg_id):
        data = getattr(call_or_message, "data", None) or getattr(call_or_message, "text", None) or ""
        await log_admin_action(session, tg_id=tg_id, action=action, data=str(data))
        return True
    logger.warning(
        "ADMIN_DENY action=%s tg_id=%s data=%s",
        action,
        tg_id,
        getattr(call_or_message, "data", None),
    )
    if isinstance(call_or_message, CallbackQuery):
        await call_or_message.answer("Недостаточно прав", show_alert=True)
    elif isinstance(call_or_message, Message):
        await call_or_message.answer("Недостаточно прав")
    return False


@router.callback_query(F.data == AdminCallbacks.ACCESS)
async def access_menu(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _ensure_admin(call, session, "admin_access.menu"):
        return
    await edit_text_safe(
        call, "🔐 <b>Права доступа</b>", reply_markup=admin_access_kb()
    )
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.ADD_ADMIN)
async def add_admin_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_access.add_admin"):
        return
    await state.clear()
    await state.set_state(AdminAccessFSM.waiting_user_id)
    await state.update_data(action="add_admin")

    await edit_text_safe(
        call,
        "➕ Добавить администратора\n\nПерешли сообщение пользователя или отправь его tgID",
        reply_markup=admin_access_kb(),
    )
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.REMOVE_ADMIN)
async def remove_admin_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_access.remove_admin"):
        return
    await state.clear()
    await state.set_state(AdminAccessFSM.waiting_user_id)
    await state.update_data(action="remove_admin")

    await edit_text_safe(
        call,
        "➖ Удалить администратора\n\nПерешли сообщение пользователя или отправь его tgID",
        reply_markup=admin_access_kb(),
    )
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.GIVE_SUB)
async def give_sub_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_access.give_sub"):
        return
    await state.clear()
    await state.set_state(AdminAccessFSM.waiting_user_id)
    await state.update_data(action="give_sub")

    await edit_text_safe(
        call,
        "🎁 Выдать подписку\n\nПерешли сообщение пользователя или отправь его tgID",
        reply_markup=admin_access_kb(),
    )
    await call.answer()


@router.message(AdminAccessFSM.waiting_user_id)
async def process_user_id(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(message, session, "admin_access.process_user_id"):
        return
    tg_id: int | None = None

    if message.forward_from:
        tg_id = message.forward_from.id
    elif message.text:
        try:
            tg_id = int(message.text.strip())
        except ValueError:
            tg_id = None

    if not tg_id:
        await message.answer("❌ Отправь tgID пользователя или перешли его сообщение 🙏")
        return

    data = await state.get_data()
    action = data.get("action")

    await state.update_data(tg_id=tg_id)

    # Сразу проверим, что юзер есть
    user = await get_user_by_tg_id(session, tg_id)
    if not user:
        await message.answer("❌ Пользователь не найден в базе (пусть нажмёт /start)")
        return

    if action == "give_sub":
        plans = await get_all_plans(session)
        if not plans:
            await message.answer("❌ В базе нет планов подписки")
            return

        await state.set_state(AdminAccessFSM.waiting_sub_plan)
        await message.answer(
            "Выбери подписку для пользователя 👇",
            reply_markup=_plans_kb(plans),
        )
        return

    # для add_admin / remove_admin — обычное подтверждение
    await message.answer(
        f"Подтвердить действие для пользователя <code>{tg_id}</code>? ✅",
        reply_markup=yes_no_kb(),
    )


@router.callback_query(
    StateFilter(AdminAccessFSM.waiting_sub_plan), F.data.startswith(SUB_PICK_PREFIX)
)
async def pick_subscription_plan(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_access.pick_plan"):
        return
    plan_id_str = (call.data or "").replace(SUB_PICK_PREFIX, "", 1)
    if not plan_id_str.isdigit():
        await call.answer("Некорректный план 😕", show_alert=True)
        return

    plan_id = int(plan_id_str)
    await state.update_data(plan_id=plan_id)

    # дальше спрашиваем подтверждение
    await edit_text_safe(
        call,
        f"Вы уверены, что хотите выдать подписку (plan_id=<code>{plan_id}</code>) этому пользователю? ✅",
        reply_markup=yes_no_kb(),
    )
    await call.answer()


@router.callback_query(
    F.data == ConfirmCallbacks.YES,
    StateFilter(AdminAccessFSM.waiting_user_id, AdminAccessFSM.waiting_sub_plan),
)
async def confirm_yes(
    call: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    if not await _ensure_admin(call, session, "admin_access.confirm_yes"):
        return
    data = await state.get_data()
    action = data.get("action")

    tg_id_raw = data.get("tg_id")
    try:
        tg_id = int(tg_id_raw)
    except Exception:
        await state.clear()
        await edit_text_safe(call, "❌ Некорректный tgID 😕", reply_markup=admin_menu_kb())
        await call.answer()
        return

    user = await get_user_by_tg_id(session, tg_id)
    if not user:
        await state.clear()
        await edit_text_safe(
            call, "❌ Пользователь не найден 😕", reply_markup=admin_menu_kb()
        )
        await call.answer()
        return

    if action == "add_admin":
        if not await is_user_admin(session, user):
            await add_admin(session, user)
            text = "✅ Администратор добавлен"
        else:
            text = "⚠️ Уже администратор"

    elif action == "remove_admin":
        if await is_user_admin(session, user):
            await remove_admin(session, user)
            text = "✅ Администратор удалён"
        else:
            text = "⚠️ Не администратор"

    elif action == "give_sub":
        plan_id = data.get("plan_id")
        if not plan_id:
            text = "❌ Не выбран план подписки"
        else:
            # ✅ FIX: деактивируем текущую активную + создаём новую выбранную
            await give_subscription_plan(session, user, int(plan_id))
            text = "🎉 Подписка выдана (старая отключена, новая активирована)"

    else:
        text = "❌ Неизвестное действие"

    await state.clear()
    await edit_text_safe(call, text, reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(
    F.data == ConfirmCallbacks.NO,
    StateFilter(AdminAccessFSM.waiting_user_id, AdminAccessFSM.waiting_sub_plan),
)
async def confirm_no(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_access.confirm_no"):
        return
    await state.clear()
    await edit_text_safe(call, "❌ Отменено", reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.BACK)
async def access_back(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not await _ensure_admin(call, session, "admin_access.back"):
        return
    await state.clear()
    await edit_text_safe(call, "⚙️ Админка", reply_markup=admin_menu_kb())
    await call.answer()
