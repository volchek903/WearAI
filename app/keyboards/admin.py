from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class AdminCallbacks:
    STATS = "admin:stats"
    USERS = "admin:users"
    BACK = "admin:back"


def admin_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data=AdminCallbacks.STATS)
    kb.button(text="👥 Пользователи", callback_data=AdminCallbacks.USERS)
    kb.button(text="⬅️ Назад", callback_data=AdminCallbacks.BACK)
    kb.adjust(1)
    return kb.as_markup()
