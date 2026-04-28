from __future__ import annotations

from aiogram import F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.extra import ExtraCallbacks, extra_menu_kb
from app.keyboards.menu import main_menu_kb
from app.keyboards.utils import add_button
from app.repository.extra import get_all_plans
from app.repository.promo import PromoError, redeem_promo_code
from app.services.free_channel_bonus import (
    CHANNEL_URL,
    bonus_already_used,
    free_channel_kb,
    is_user_in_channel,
    schedule_bonus_grant,
    start_bonus_pending,
)
from app.utils.tg_callback import safe_answer
from app.utils.tg_edit import edit_text_safe

from .common import FreePromoFlow, format_promo_bonus, logger, purchasable_plans, router


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
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    code = (message.text or "").strip()
    if not code:
        await message.answer("Промокод пустой. Попробуйте ещё раз ✍️")
        return
    await state.clear()

    try:
        promo = await redeem_promo_code(
            session=session,
            tg_id=message.from_user.id,
            code=code,
        )
    except PromoError as e:
        if "исчерпан" in str(e):
            await message.answer("⛔️ Промокод исчерпан — все активации уже использованы.")
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
        f"Бонус: {format_promo_bonus(promo)}"
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
        markup = extra_menu_kb(purchasable_plans(plans), current_plan_name=None)
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


@router.callback_query(F.data == ExtraCallbacks.TO_MENU)
async def extra_to_menu(call: CallbackQuery) -> None:
    if call.message:
        await edit_text_safe(call, "Главное меню 👇", reply_markup=main_menu_kb())
    await call.answer()
