from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.utils import add_button


class ReferralCallbacks:
    SHARE = "referral:share"
    BACK = "referral:back"


def referral_kb(share_text: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📨 Поделиться", switch_inline_query=share_text))
    add_button(
        kb, text="⬅️ В меню", callback_data=ReferralCallbacks.BACK, style="danger"
    )
    kb.adjust(1)
    return kb.as_markup()
