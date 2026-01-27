from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class ReferralCallbacks:
    SHARE = "referral:share"
    BACK = "referral:back"


def referral_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📨 Поделиться", callback_data=ReferralCallbacks.SHARE)
    kb.button(text="⬅️ В меню", callback_data=ReferralCallbacks.BACK)
    kb.adjust(1)
    return kb.as_markup()
