from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.utils import add_button


class ReferralCallbacks:
    SHARE = "referral:share"
    BACK = "referral:back"


def referral_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(
        kb,
        text="📨 Поделиться",
        callback_data=ReferralCallbacks.SHARE,
        style="success",
    )
    add_button(
        kb, text="⬅️ В меню", callback_data=ReferralCallbacks.BACK, style="danger"
    )
    kb.adjust(1)
    return kb.as_markup()
