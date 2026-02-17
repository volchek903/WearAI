from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.utils import add_button


class AdminCallbacks:
    STATS = "admin:stats"
    USERS = "admin:users"
    USERS_PAGE = "admin:users:page"
    ACCESS = "admin:access"
    BROADCAST = "admin:broadcast"
    TOP_REFERRALS = "admin:top_referrals"
    PACKAGES = "admin:packages"
    PACKAGE_PICK = "admin:packages:pick"
    PACKAGE_EDIT = "admin:packages:edit"
    PACKAGE_FIELD = "admin:packages:field"
    PACKAGE_CREATE = "admin:packages:create"

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

    @staticmethod
    def package_pick(plan_id: int) -> str:
        return f"{AdminCallbacks.PACKAGE_PICK}:{plan_id}"

    @staticmethod
    def package_edit(plan_id: int) -> str:
        return f"{AdminCallbacks.PACKAGE_EDIT}:{plan_id}"

    @staticmethod
    def package_field(plan_id: int, field: str) -> str:
        return f"{AdminCallbacks.PACKAGE_FIELD}:{plan_id}:{field}"


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

    add_button(kb, text="📊 Статистика", callback_data=AdminCallbacks.STATS)
    add_button(kb, text="👥 Пользователи", callback_data=AdminCallbacks.USERS)
    add_button(kb, text="🏆 Топ рефералов", callback_data=AdminCallbacks.TOP_REFERRALS)
    add_button(kb, text="📦 Пакеты", callback_data=AdminCallbacks.PACKAGES)
    add_button(kb, text="🎟 Промокоды", callback_data=AdminCallbacks.PROMO)
    add_button(kb, text="📣 Рассылка", callback_data=AdminCallbacks.BROADCAST)
    add_button(kb, text="🔐 Доступы", callback_data=AdminCallbacks.ACCESS)
    add_button(kb, text="⬅️ Назад", callback_data=AdminCallbacks.BACK, style="danger")

    kb.adjust(1)
    return kb.as_markup()


def admin_promo_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(
        kb, text="➕ Создать промокод", callback_data=AdminCallbacks.CREATE_PROMO
    )
    add_button(
        kb,
        text="📋 Просмотреть промокоды",
        callback_data=AdminCallbacks.LIST_PROMO,
    )
    add_button(kb, text="⬅️ Назад", callback_data=AdminCallbacks.BACK, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def admin_broadcast_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="🖼️ Только фото", callback_data=AdminBroadcastCallbacks.PHOTO)
    add_button(
        kb,
        text="🖼️ Фото с текстом",
        callback_data=AdminBroadcastCallbacks.PHOTO_TEXT,
    )
    add_button(kb, text="🎬 Только видео", callback_data=AdminBroadcastCallbacks.VIDEO)
    add_button(
        kb,
        text="🎬 Видео с текстом",
        callback_data=AdminBroadcastCallbacks.VIDEO_TEXT,
    )
    add_button(kb, text="🎙️ Голосовое", callback_data=AdminBroadcastCallbacks.VOICE)
    add_button(kb, text="✉️ Только текст", callback_data=AdminBroadcastCallbacks.TEXT)
    add_button(
        kb,
        text="⬅️ Назад",
        callback_data=AdminBroadcastCallbacks.BACK,
        style="danger",
    )
    kb.adjust(1)
    return kb.as_markup()


def admin_access_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    add_button(kb, text="➕ Добавить админа", callback_data=AdminCallbacks.ADD_ADMIN)
    add_button(
        kb, text="➖ Удалить админа", callback_data=AdminCallbacks.REMOVE_ADMIN
    )
    add_button(kb, text="🎁 Выдать подписку", callback_data=AdminCallbacks.GIVE_SUB)
    add_button(kb, text="📦 Пакеты", callback_data=AdminCallbacks.PACKAGES)
    add_button(kb, text="⬅️ Назад", callback_data=AdminCallbacks.BACK, style="danger")

    kb.adjust(1)
    return kb.as_markup()


def admin_users_nav_kb(
    *, page: int, has_prev: bool, has_next: bool
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_prev:
        add_button(
            kb,
            text="⬅️ Назад",
            callback_data=AdminCallbacks.users_page(page - 1),
            style="danger",
        )
    if has_next:
        add_button(
            kb, text="➡️ Вперёд", callback_data=AdminCallbacks.users_page(page + 1)
        )
    add_button(kb, text="⬅️ В админку", callback_data=AdminCallbacks.BACK, style="danger")
    if has_prev and has_next:
        kb.adjust(2, 1)
    else:
        kb.adjust(1)
    return kb.as_markup()


def admin_packages_kb(plans) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in plans:
        add_button(kb, text=f"📦 {p.name}", callback_data=AdminCallbacks.package_pick(p.id))
    add_button(kb, text="➕ Добавить пакет", callback_data=AdminCallbacks.PACKAGE_CREATE)
    add_button(kb, text="⬅️ Назад", callback_data=AdminCallbacks.BACK, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def admin_package_actions_kb(plan_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(
        kb,
        text="✏️ Изменить пакет",
        callback_data=AdminCallbacks.package_edit(plan_id),
    )
    add_button(kb, text="⬅️ Назад", callback_data=AdminCallbacks.PACKAGES, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def admin_package_fields_kb(plan_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(
        kb, text="Название", callback_data=AdminCallbacks.package_field(plan_id, "name")
    )
    add_button(
        kb,
        text="Количество видео",
        callback_data=AdminCallbacks.package_field(plan_id, "video_generations"),
    )
    add_button(
        kb,
        text="Количество фото",
        callback_data=AdminCallbacks.package_field(plan_id, "photo_generations"),
    )
    add_button(
        kb,
        text="Кол-во дней действия",
        callback_data=AdminCallbacks.package_field(plan_id, "duration_days"),
    )
    add_button(
        kb,
        text="Цена в ₽",
        callback_data=AdminCallbacks.package_field(plan_id, "price"),
    )
    add_button(
        kb,
        text="Цена в ⭐",
        callback_data=AdminCallbacks.package_field(plan_id, "stars_price"),
    )
    add_button(kb, text="⬅️ Назад", callback_data=AdminCallbacks.package_pick(plan_id), style="danger")
    kb.adjust(1)
    return kb.as_markup()
