# app/handlers/extra.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.menu import MenuCallbacks, main_menu_kb
from app.keyboards.extra import ExtraCallbacks, extra_menu_kb, extra_buy_kb
from app.models.subscription import Subscription
from app.repository.extra import (
    get_user,
    get_active_plan_name,
    get_active_remaining,
    get_plan,
    get_all_plans,
)

router = Router()

ORDER = ["Launch", "Orbit", "Nova", "Cosmic"]


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _table(plans: list[Subscription]) -> str:
    by_name = {p.name: p for p in plans}

    lines = [
        "Пакет      Цена     Дней   Видео   Фото",
        "----------------------------------------",
    ]

    for name in ORDER:
        p = by_name.get(name)
        if not p:
            continue

        price = "Free" if float(p.price) == 0 else f"${float(p.price):.0f}"
        days = "-" if p.duration_days == 0 else str(p.duration_days)

        lines.append(
            f"{p.name:<10} {price:<7} {days:<5} {p.video_generations:<6} {p.photo_generations:<6}"
        )

    joined = "\n".join(lines)
    return f"<pre>{_escape(joined)}</pre>"


def _extra_text(
    current_name: str,
    remaining_video: int,
    remaining_photo: int,
    table_html: str,
) -> str:
    return (
        "✨ <b>Дополнительные возможности</b>\n\n"
        f"Твоя текущая подписка: <b>{_escape(current_name)}</b>\n"
        f"Осталось генераций: 🎬 <b>{remaining_video}</b> видео • 🖼️ <b>{remaining_photo}</b> фото\n\n"
        "За пожертвование ты получаешь доступ к пакетам генераций — "
        "это помогает развитию сервиса и даёт больше контента под твои товары.\n\n"
        f"{table_html}\n"
        "Выбирай пакет ниже — и я расскажу, что там самого кайфового 👇"
    )


def _pitch(plan_name: str, plan: Subscription) -> str:
    if plan_name == "Orbit":
        intro = "Ооо, <b>Orbit</b> — отличный выбор 🚀"
        vibe = "Это уверенный режим: тестишь идеи, делаешь карточки товара и вариации спокойно."
    elif plan_name == "Nova":
        intro = "Йо! <b>Nova</b> — это уже мощно 😮‍💨✨"
        vibe = "Здесь можно разогнаться по ассортименту и делать контент пачками."
    else:  # Cosmic
        intro = "Воу… <b>Cosmic</b> — уровень «я пришёл забирать рынок» 🤯🌌"
        vibe = "Максимальная свобода: много генераций, можно закрывать линейки товаров без стресса."

    price = "Free" if float(plan.price) == 0 else f"<b>${float(plan.price):.0f}</b>"
    days = (
        "без срока"
        if plan.duration_days == 0
        else f"на <b>{plan.duration_days}</b> дней"
    )

    return (
        f"{intro}\n\n"
        f"Вот что ты получаешь {days}:\n"
        f"• 🎬 Видео: <b>{plan.video_generations}</b>\n"
        f"• 🖼️ Фото: <b>{plan.photo_generations}</b>\n"
        f"• 💰 Стоимость: {price}\n\n"
        f"{vibe}\n\n"
        "Если готов — жми <b>Купить</b> 😉"
    )


@router.callback_query(F.data == ExtraCallbacks.TO_MENU)
async def extra_to_menu(call: CallbackQuery) -> None:
    if call.message:
        await call.message.edit_text("Главное меню 👇", reply_markup=main_menu_kb())
    await call.answer()


@router.callback_query(F.data == MenuCallbacks.EXTRA)
async def extra_open(call: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user(session, call.from_user.id)

    if not user:
        current_name = "Launch"
        remaining_video, remaining_photo = 2, 3
    else:
        current_name = await get_active_plan_name(session, user.id)
        remaining_video, remaining_photo = await get_active_remaining(session, user.id)

    plans = await get_all_plans(session)
    table_html = _table(plans)

    if call.message:
        await call.message.edit_text(
            _extra_text(current_name, remaining_video, remaining_photo, table_html),
            reply_markup=extra_menu_kb(current_name),
            parse_mode="HTML",
        )
    await call.answer()


@router.callback_query(
    F.data.in_(
        {
            ExtraCallbacks.WANT_ORBIT,
            ExtraCallbacks.WANT_NOVA,
            ExtraCallbacks.WANT_COSMIC,
        }
    )
)
async def extra_want(call: CallbackQuery, session: AsyncSession) -> None:
    plan_name = (
        "Orbit"
        if call.data == ExtraCallbacks.WANT_ORBIT
        else "Nova" if call.data == ExtraCallbacks.WANT_NOVA else "Cosmic"
    )

    plan = await get_plan(session, plan_name)
    if not plan:
        await call.answer("Пакет не найден в базе 😕", show_alert=True)
        return

    if call.message:
        await call.message.edit_text(
            _pitch(plan_name, plan),
            reply_markup=extra_buy_kb(plan_name),
            parse_mode="HTML",
        )
    await call.answer()


@router.callback_query(F.data == ExtraCallbacks.BACK)
async def extra_back(call: CallbackQuery, session: AsyncSession) -> None:
    await extra_open(call, session)


@router.callback_query(
    F.data.in_(
        {
            ExtraCallbacks.BUY_ORBIT,
            ExtraCallbacks.BUY_NOVA,
            ExtraCallbacks.BUY_COSMIC,
        }
    )
)
async def extra_buy(call: CallbackQuery) -> None:
    if call.message:
        await call.message.edit_text(
            "🔥 Супер! Сейчас оформим покупку.\n\n"
            "Я подготовлю оплату и после подтверждения пакет активируется автоматически ✅",
            parse_mode="HTML",
        )
    await call.answer()
