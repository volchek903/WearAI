from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import (
    AdminCallbacks,
    admin_access_kb,
    admin_menu_kb,
)
from app.keyboards.confirm import ConfirmCallbacks, yes_no_kb
from app.repository.access import (
    get_user_by_tg_id,
    is_user_admin,
    add_admin,
    remove_admin,
    give_subscription,
    give_subscription_days,
)
from app.states.admin_access import AdminAccessFSM
from app.utils.tg_edit import edit_text_safe

router = Router()


@router.callback_query(F.data == AdminCallbacks.ACCESS)
async def access_menu(call: CallbackQuery) -> None:
    await edit_text_safe(
        call, "🔐 <b>Права доступа</b>", reply_markup=admin_access_kb()
    )
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.ADD_ADMIN)
async def add_admin_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminAccessFSM.waiting_user_id)
    await state.update_data(action="add_admin")

    await edit_text_safe(
        call,
        "➕ Добавить администратора\n\n"
        "Перешли сообщение пользователя или отправь его tgID",
        reply_markup=admin_access_kb(),
    )
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.REMOVE_ADMIN)
async def remove_admin_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminAccessFSM.waiting_user_id)
    await state.update_data(action="remove_admin")

    await edit_text_safe(
        call,
        "➖ Удалить администратора\n\n"
        "Перешли сообщение пользователя или отправь его tgID",
        reply_markup=admin_access_kb(),
    )
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.GIVE_SUB)
async def give_sub_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminAccessFSM.waiting_user_id)
    await state.update_data(action="give_sub")

    await edit_text_safe(
        call,
        "🎁 Выдать подписку\n\n" "Перешли сообщение пользователя или отправь его tgID",
        reply_markup=admin_access_kb(),
    )
    await call.answer()


@router.message(AdminAccessFSM.waiting_user_id)
async def process_user_id(message: Message, state: FSMContext) -> None:
    tg_id: int | None = None

    if message.forward_from:
        tg_id = message.forward_from.id
    elif message.text:
        try:
            tg_id = int(message.text)
        except ValueError:
            pass

    if not tg_id:
        await message.answer("❌ Отправь tgID пользователя или перешли его сообщение")
        return

    data = await state.get_data()
    action = data.get("action")

    await state.update_data(tg_id=tg_id)

    if action == "give_sub":
        await state.set_state(AdminAccessFSM.waiting_sub_days)
        await message.answer("Введи количество дней подписки")
        return

    await message.answer(
        f"Подтвердить действие для пользователя <code>{tg_id}</code>?",
        reply_markup=yes_no_kb(),
    )


@router.message(AdminAccessFSM.waiting_sub_days)
async def process_sub_days(message: Message, state: FSMContext) -> None:
    try:
        days = int(message.text)
        if days <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи положительное число дней")
        return

    await state.update_data(days=days)

    await message.answer(
        f"Выдать подписку на <b>{days}</b> дней?",
        reply_markup=yes_no_kb(),
    )


@router.callback_query(
    F.data == ConfirmCallbacks.YES,
    StateFilter(
        AdminAccessFSM.waiting_user_id,
        AdminAccessFSM.waiting_sub_days,
    ),
)
async def confirm_yes(
    call: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    action = data.get("action")
    tg_id = data.get("tg_id")

    user = await get_user_by_tg_id(session, tg_id)
    if not user:
        await state.clear()
        await edit_text_safe(
            call, "❌ Пользователь не найден", reply_markup=admin_menu_kb()
        )
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
        days = data.get("days")
        if days:
            await give_subscription_days(session, user, days)
            text = f"🎉 Подписка выдана на {days} дней"
        else:
            await give_subscription(session, user)
            text = "🎉 Подписка выдана"

    else:
        text = "❌ Неизвестное действие"

    await state.clear()
    await edit_text_safe(call, text, reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(
    F.data == ConfirmCallbacks.NO,
    StateFilter(
        AdminAccessFSM.waiting_user_id,
        AdminAccessFSM.waiting_sub_days,
    ),
)
async def confirm_no(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_text_safe(call, "❌ Отменено", reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.BACK)
async def access_back(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_text_safe(call, "⚙️ Админка", reply_markup=admin_menu_kb())
    await call.answer()
