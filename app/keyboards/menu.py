from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models.user_photo_settings import UserPhotoSettings


class MenuCallbacks:
    MODEL = "menu:model"
    TRYON = "menu:tryon"
    ANIMATE = "menu:animate"
    PHOTO = "menu:photo"
    VIDEO = "menu:video"
    LOVE_IS = "menu:love_is"
    RADAR = "menu:radar"
    NANO_BANANA = "menu:nano_banana"
    HELP = "menu:help"
    FAQ = "menu:faq"
    SETTINGS = "menu:settings"
    EXTRA = "menu:extra"
    BACK = "menu:back"


class SettingsCallbacks:
    ASPECT = "settings:aspect"
    RESOLUTION = "settings:resolution"
    FORMAT = "settings:format"
    NANO_BANANA = "settings:nano_banana"
    RESET = "settings:reset"
    BACK = "settings:back"


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="🖼 Работа с фото", callback_data=MenuCallbacks.PHOTO)
    kb.button(text="🎬 Работа с видео", callback_data=MenuCallbacks.VIDEO)
    kb.button(text="🪄 Помощь в генерации", callback_data=MenuCallbacks.HELP)
    kb.button(text="✨ Доп. возможности", callback_data=MenuCallbacks.EXTRA)
    kb.button(text="❓ Вопросы (FAQ)", callback_data=MenuCallbacks.FAQ)
    kb.button(text="⚙️ Настройки", callback_data=MenuCallbacks.SETTINGS)

    kb.adjust(1)
    return kb.as_markup()


def photo_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🍌 nano-banano", callback_data=MenuCallbacks.NANO_BANANA)
    kb.button(text="🛍️ Модель с товаром", callback_data=MenuCallbacks.MODEL)
    kb.button(text="🧥 Примерить одежду", callback_data=MenuCallbacks.TRYON)
    kb.button(text="❤️ ИИ Love is", callback_data=MenuCallbacks.LOVE_IS)
    kb.button(text="🛰 ИИ Радар", callback_data=MenuCallbacks.RADAR)
    kb.button(text="⬅️ В меню", callback_data=MenuCallbacks.BACK)
    kb.adjust(1)
    return kb.as_markup()


def video_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎬 Оживить видео", callback_data=MenuCallbacks.ANIMATE)
    kb.button(text="⬅️ В меню", callback_data=MenuCallbacks.BACK)
    kb.adjust(1)
    return kb.as_markup()


def photo_settings_kb(s: UserPhotoSettings) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(
        text=f"📐 Соотношение: {s.aspect_ratio}",
        callback_data=SettingsCallbacks.ASPECT,
    )
    kb.button(
        text=f"🖼 Разрешение: {s.resolution}",
        callback_data=SettingsCallbacks.RESOLUTION,
    )
    kb.button(
        text=f"🗂 Формат: {s.output_format}",
        callback_data=SettingsCallbacks.FORMAT,
    )
    kb.button(text="🍌 nano-banano", callback_data=SettingsCallbacks.NANO_BANANA)
    kb.button(text="🔄 Сбросить по умолчанию", callback_data=SettingsCallbacks.RESET)
    kb.button(text="⬅️ Назад", callback_data=SettingsCallbacks.BACK)

    kb.adjust(1)
    return kb.as_markup()
