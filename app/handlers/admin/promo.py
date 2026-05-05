from __future__ import annotations

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.admin import AdminCallbacks, admin_menu_kb, admin_promo_kb
from app.keyboards.confirm import ConfirmCallbacks, yes_no_kb
from app.repository.promo import PromoError, create_promo_code, get_last_promo_codes
from app.states.admin import AdminPromoFSM
from app.utils.support_text import with_support
from app.utils.tg_edit import edit_text_safe

from .common import ensure_admin, router


@router.callback_query(F.data == AdminCallbacks.PROMO)
async def admin_promo_menu(call: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_admin(call, session, "admin_panel.promo_menu"):
        return
    await edit_text_safe(call, "🎟 Промокоды", reply_markup=admin_promo_kb())
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.CREATE_PROMO)
async def admin_promo_start(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not await ensure_admin(call, session, "admin_panel.create_promo"):
        return
    await state.clear()
    await state.set_state(AdminPromoFSM.code)
    await edit_text_safe(call, "Введи промокод ✍️")
    await call.answer()


@router.callback_query(F.data == AdminCallbacks.LIST_PROMO)
async def admin_promo_list(call: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_admin(call, session, "admin_panel.promo_list"):
        return
    promos = await get_last_promo_codes(session, limit=10)
    if not promos:
        text = "🎟 <b>Промокоды</b>\n\nПока пусто 💤"
    else:
        lines: list[str] = []
        for promo in promos:
            lines.append(
                f"• <code>{promo.code}</code> "
                f"кредиты={int(getattr(promo, 'bonus_credits', 0) or 0)} "
                f"фото={promo.bonus_photo} видео={promo.bonus_video} "
                f"использовано {promo.used_count}/{promo.max_uses}"
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
    await message.answer("Сколько кредитов выдаёт промокод? 💠")


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
    await message.answer("Сколько пользователей может активировать промокод? 👥")


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
        "Всё верно? ✅",
        reply_markup=yes_no_kb(
            yes_text="✅ Создать",
            no_text="❌ Отменить",
            no_style="danger",
        ),
    )


@router.callback_query(AdminPromoFSM.confirm, F.data == ConfirmCallbacks.NO)
async def admin_promo_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_text_safe(
        call,
        "Создание промокода отменено.",
        reply_markup=admin_menu_kb(),
    )
    await call.answer()


@router.callback_query(AdminPromoFSM.confirm, F.data == ConfirmCallbacks.YES)
async def admin_promo_confirm(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
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
            call,
            with_support(f"Ошибка: {e}"),
            reply_markup=admin_menu_kb(),
        )
        await state.clear()
        await call.answer()
        return

    await state.clear()
    await edit_text_safe(call, "✅ Промокод создан.", reply_markup=admin_menu_kb())
    await call.answer()
