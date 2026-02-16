from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.menu import main_menu_kb
from app.keyboards.faq import FAQ_REFERRAL_CB
from app.keyboards.referrals import ReferralCallbacks, referral_kb
from app.repository.referrals import get_referrals_count
from app.repository.users import get_or_create_user
from app.utils.tg_edit import edit_text_safe

router = Router()
logger = logging.getLogger(__name__)

INVITE_BAIT_TEXT = (
    "🔥 Хочешь делать крутые генерации фото с ИИ?\n"
    "Заходи и попробуй — есть бесплатные генерации!\n\n"
    "Присоединяйся по моей ссылке 👇"
)


async def _get_ref_link(bot, tg_id: int) -> str:
    try:
        me = await bot.get_me()
        if me.username:
            return f"https://t.me/{me.username}?start=ref_{tg_id}"
    except Exception:
        logger.exception("referrals: failed to get bot username")
    return f"/start ref_{tg_id}"


def _referral_text(ref_link: str, count: int) -> str:
    return (
        "🤝 <b>Реферальная система</b>\n\n"
        "Приглашай друзей по своей ссылке — получай подписки:\n"
        "• <b>10</b> приглашённых → <b>подписка Orbit</b>\n"
        "• <b>50</b> приглашённых → <b>подписка Nova</b>\n"
        "Если текущая подписка хуже/такая же/дешевле — заменяем на новую.\n\n"
        f"У тебя приглашено: <b>{count}</b>\n"
        f"Твоя ссылка:\n<code>{ref_link}</code>\n\n"
        "Нажми «Поделиться», чтобы получить готовый текст."
    )


@router.callback_query(F.data == FAQ_REFERRAL_CB)
async def referral_open_from_faq(
    call: CallbackQuery, session: AsyncSession
) -> None:
    user, _ = await get_or_create_user(
        session, call.from_user.id, call.from_user.username
    )
    count = await get_referrals_count(session, user.id)
    ref_link = await _get_ref_link(call.bot, user.tg_id)

    await edit_text_safe(
        call,
        _referral_text(ref_link, count),
        reply_markup=referral_kb(f"{INVITE_BAIT_TEXT}\n{ref_link}"),
    )
    await call.answer()

@router.callback_query(F.data == ReferralCallbacks.BACK)
async def referral_back(call: CallbackQuery) -> None:
    await edit_text_safe(call, "Главное меню 👇", reply_markup=main_menu_kb())
    await call.answer()
