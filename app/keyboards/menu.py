from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models.user_photo_settings import UserPhotoSettings


class MenuCallbacks:
    MODEL = "menu:model"
    TRYON = "menu:tryon"
    ANIMATE = "menu:animate"
    HELP = "menu:help"
    FAQ = "menu:faq"
    SETTINGS = "menu:settings"

    # NEW
    EXTRA = "menu:extra"


class SettingsCallbacks:
    ASPECT = "settings:aspect"
    RESOLUTION = "settings:resolution"
    FORMAT = "settings:format"
    RESET = "settings:reset"
    BACK = "settings:back"


class ExtraCallbacks:
    # открыть меню "Дополнительные возможности"
    OPEN = "extra:open"

    # выбор пакета
    WANT_ORBIT = "extra:want:orbit"
    WANT_NOVA = "extra:want:nova"
    WANT_COSMIC = "extra:want:cosmic"

    # покупка
    BUY_ORBIT = "extra:buy:orbit"
    BUY_NOVA = "extra:buy:nova"
    BUY_COSMIC = "extra:buy:cosmic"

    # навигация назад
    BACK = "extra:back"


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="🛍️ Модель с товаром", callback_data=MenuCallbacks.MODEL)
    kb.button(text="🧥 Примерить одежду", callback_data=MenuCallbacks.TRYON)
    kb.button(text="🎬 Оживить фото", callback_data=MenuCallbacks.ANIMATE)
    kb.button(text="🪄 Помочь с описанием", callback_data=MenuCallbacks.HELP)

    # NEW
    kb.button(text="✨ Доп. возможности", callback_data=MenuCallbacks.EXTRA)

    kb.button(text="❓ FAQ", callback_data=MenuCallbacks.FAQ)
    kb.button(text="⚙️ Настройки", callback_data=MenuCallbacks.SETTINGS)

    kb.adjust(1)
    return kb.as_markup()


def photo_settings_kb(s: UserPhotoSettings) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text=f"Соотношение: {s.aspect_ratio}", callback_data=SettingsCallbacks.ASPECT
    )
    kb.button(
        text=f"Разрешение: {s.resolution}", callback_data=SettingsCallbacks.RESOLUTION
    )
    kb.button(text=f"Формат: {s.output_format}", callback_data=SettingsCallbacks.FORMAT)
    kb.button(text="Сбросить по умолчанию", callback_data=SettingsCallbacks.RESET)
    kb.button(text="⬅️ Назад", callback_data=SettingsCallbacks.BACK)
    kb.adjust(1)
    return kb.as_markup()
