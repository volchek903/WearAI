from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class AdminCallbacks:
    STATS = "admin:stats"
    USERS = "admin:users"
    USERS_PAGE = "admin:users:page"
    ACCESS = "admin:access"
    BROADCAST = "admin:broadcast"

    ADD_ADMIN = "admin:add_admin"
    REMOVE_ADMIN = "admin:remove_admin"
    GIVE_SUB = "admin:give_sub"
    PROMO = "admin:promo"
    CREATE_PROMO = "admin:promo:create"
    LIST_PROMO = "admin:promo:list"
    PROMO_TYPE = "admin:promo:type"

    BACK = "admin:back"

    @staticmethod
    def users_page(page: int) -> str:
        return f"{AdminCallbacks.USERS_PAGE}:{page}"

    @staticmethod
    def promo_type(kind: str) -> str:
        return f"{AdminCallbacks.PROMO_TYPE}:{kind}"


class AdminBroadcastCallbacks:
    PHOTO = "admin:broadcast:photo"
    PHOTO_TEXT = "admin:broadcast:photo_text"
    VIDEO = "admin:broadcast:video"
    VIDEO_TEXT = "admin:broadcast:video_text"
    VOICE = "admin:broadcast:voice"
    TEXT = "admin:broadcast:text"
    BACK = "admin:broadcast:back"


def admin_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="📊 Статистика", callback_data=AdminCallbacks.STATS)
    kb.button(text="👥 Пользователи", callback_data=AdminCallbacks.USERS)
    kb.button(text="🎟 Промокоды", callback_data=AdminCallbacks.PROMO)
    kb.button(text="📣 Рассылка", callback_data=AdminCallbacks.BROADCAST)
    kb.button(text="🔐 Доступы", callback_data=AdminCallbacks.ACCESS)
    kb.button(text="⬅️ Назад", callback_data=AdminCallbacks.BACK)

    kb.adjust(1)
    return kb.as_markup()


def admin_promo_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Создать промокод", callback_data=AdminCallbacks.CREATE_PROMO)
    kb.button(text="📋 Просмотреть промокоды", callback_data=AdminCallbacks.LIST_PROMO)
    kb.button(text="⬅️ Назад", callback_data=AdminCallbacks.BACK)
    kb.adjust(1)
    return kb.as_markup()


def admin_broadcast_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🖼️ Только фото", callback_data=AdminBroadcastCallbacks.PHOTO)
    kb.button(text="🖼️ Фото с текстом", callback_data=AdminBroadcastCallbacks.PHOTO_TEXT)
    kb.button(text="🎬 Только видео", callback_data=AdminBroadcastCallbacks.VIDEO)
    kb.button(text="🎬 Видео с текстом", callback_data=AdminBroadcastCallbacks.VIDEO_TEXT)
    kb.button(text="🎙️ Голосовое", callback_data=AdminBroadcastCallbacks.VOICE)
    kb.button(text="✉️ Только текст", callback_data=AdminBroadcastCallbacks.TEXT)
    kb.button(text="⬅️ Назад", callback_data=AdminBroadcastCallbacks.BACK)
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


def admin_users_nav_kb(
    *, page: int, has_prev: bool, has_next: bool
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_prev:
        kb.button(text="⬅️ Назад", callback_data=AdminCallbacks.users_page(page - 1))
    if has_next:
        kb.button(text="➡️ Вперёд", callback_data=AdminCallbacks.users_page(page + 1))
    kb.button(text="⬅️ В админку", callback_data=AdminCallbacks.BACK)
    if has_prev and has_next:
        kb.adjust(2, 1)
    else:
        kb.adjust(1)
    return kb.as_markup()
