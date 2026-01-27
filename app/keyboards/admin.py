from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class AdminCallbacks:
    STATS = "admin:stats"
    USERS = "admin:users"
    ACCESS = "admin:access"

    ADD_ADMIN = "admin:add_admin"
    REMOVE_ADMIN = "admin:remove_admin"
    GIVE_SUB = "admin:give_sub"

    BACK = "admin:back"


def admin_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="📊 Статистика", callback_data=AdminCallbacks.STATS)
    kb.button(text="👥 Пользователи", callback_data=AdminCallbacks.USERS)
    kb.button(text="🔐 Доступы", callback_data=AdminCallbacks.ACCESS)
    kb.button(text="⬅️ Назад", callback_data=AdminCallbacks.BACK)

    kb.adjust(1)
    return kb.as_markup()


def admin_access_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="➕ Добавить админа", callback_data=AdminCallbacks.ADD_ADMIN)
    kb.button(
        text="➖ Удалить админа", callback_data=AdminCallbacks.REMOVE_ADMIN
    )
    kb.button(text="🎁 Выдать подписку", callback_data=AdminCallbacks.GIVE_SUB)
    kb.button(text="⬅️ Назад", callback_data=AdminCallbacks.BACK)

    kb.adjust(1)
    return kb.as_markup()
