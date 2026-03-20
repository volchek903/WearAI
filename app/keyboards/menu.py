from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models.user_photo_settings import UserPhotoSettings
from app.keyboards.utils import add_button


class MenuCallbacks:
    MODEL = "menu:model"
    TRYON = "menu:tryon"
    ANIMATE = "menu:animate"
    MOTION_CONTROL = "menu:motion_control"
    PHOTO = "menu:photo"
    PHOTO_CARS = "menu:photo:cars"
    PHOTO_TWO = "menu:photo:two"
    DISNEY_STYLE = "menu:disney_style"
    DISNEY_FAMILY_HEART = "menu:disney_family_heart"
    DISNEY_FAMILY_WALL = "menu:disney_family_wall"
    PHOTO_ONE = "menu:photo:one"
    PHOTO_OTHER = "menu:photo:other"
    PHOTO_ARCHIVE = "menu:photo:archive"
    VIDEO = "menu:video"
    LOVE_IS = "menu:love_is"
    FEB23 = "menu:feb23"
    MAIN_DEFENDER = "menu:main_defender"
    MARCH8 = "menu:march8"
    CINEMA_BW = "menu:cinema_bw"
    RADAR = "menu:radar"
    SECOND_LIFE = "menu:second_life"
    NANO_BANANA = "menu:nano_banana"
    DRIFT_HEART = "menu:drift_heart"
    CAR_IN_HAND = "menu:car_in_hand"
    REAR_VIEW_MIRROR = "menu:rear_view_mirror"
    GTA_STYLE = "menu:gta_style"
    LEGO_STYLE = "menu:lego_style"
    GLAM_COLLAGE = "menu:glam_collage"
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

    add_button(kb, text="🖼 Работа с фото", callback_data=MenuCallbacks.PHOTO)
    add_button(kb, text="🎬 Работа с видео", callback_data=MenuCallbacks.VIDEO)
    add_button(kb, text="✨ Доп. возможности", callback_data=MenuCallbacks.EXTRA)
    add_button(kb, text="❓ Вопросы (FAQ)", callback_data=MenuCallbacks.FAQ)

    kb.adjust(1)
    return kb.as_markup()


def photo_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="🍌 Nano Banana 2", callback_data=MenuCallbacks.NANO_BANANA)
    add_button(kb, text="🚗 Шаблоны с машинами", callback_data=MenuCallbacks.PHOTO_CARS)
    add_button(
        kb,
        text="👫 Шаблоны для двоих и семейные",
        callback_data=MenuCallbacks.PHOTO_TWO,
    )
    add_button(kb, text="🧍‍♂️ Шаблоны для одного", callback_data=MenuCallbacks.PHOTO_ONE)
    add_button(kb, text="🧩 Другое", callback_data=MenuCallbacks.PHOTO_OTHER)
    add_button(kb, text="🗂 Архив", callback_data=MenuCallbacks.PHOTO_ARCHIVE)
    add_button(kb, text="⬅️ В меню", callback_data=MenuCallbacks.BACK, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def photo_cars_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="💘 Дрифт сердце", callback_data=MenuCallbacks.DRIFT_HEART)
    add_button(kb, text="✋ Ваша машина в руке", callback_data=MenuCallbacks.CAR_IN_HAND)
    add_button(
        kb,
        text="🪞 Зеркало заднего вида",
        callback_data=MenuCallbacks.REAR_VIEW_MIRROR,
    )
    add_button(kb, text="🛰 ИИ Радар", callback_data=MenuCallbacks.RADAR)
    add_button(kb, text="⬅️ Назад", callback_data=MenuCallbacks.PHOTO, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def photo_two_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="🏰 Дисней стиль", callback_data=MenuCallbacks.DISNEY_STYLE)
    add_button(kb, text="❤️ ИИ Love is", callback_data=MenuCallbacks.LOVE_IS)
    add_button(kb, text="🛡 Мой главный защитник", callback_data=MenuCallbacks.MAIN_DEFENDER)
    add_button(kb, text="🎞 Одни в кинозале ЧБ", callback_data=MenuCallbacks.CINEMA_BW)
    add_button(kb, text="🛰 ИИ Радар", callback_data=MenuCallbacks.RADAR)
    add_button(kb, text="⬅️ Назад", callback_data=MenuCallbacks.PHOTO, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def disney_style_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(
        kb,
        text="💖 Семья в сердечке",
        callback_data=MenuCallbacks.DISNEY_FAMILY_HEART,
    )
    add_button(
        kb,
        text="🧱 Семья выглядывает из-за стены",
        callback_data=MenuCallbacks.DISNEY_FAMILY_WALL,
    )
    add_button(kb, text="⬅️ Назад", callback_data=MenuCallbacks.PHOTO_TWO, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def photo_other_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="🖼 Вторая жизнь для фото", callback_data=MenuCallbacks.SECOND_LIFE)
    add_button(kb, text="🌸 Поздравление с 8 Марта", callback_data=MenuCallbacks.MARCH8)
    add_button(kb, text="⬅️ Назад", callback_data=MenuCallbacks.PHOTO, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def photo_archive_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="🎖 23 февраля", callback_data=MenuCallbacks.FEB23)
    add_button(kb, text="⬅️ Назад", callback_data=MenuCallbacks.PHOTO, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def photo_one_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="🛍️ Модель с товаром", callback_data=MenuCallbacks.MODEL)
    add_button(kb, text="🧥 Примерить одежду", callback_data=MenuCallbacks.TRYON)
    add_button(kb, text="🕶 GTA STYLE", callback_data=MenuCallbacks.GTA_STYLE)
    add_button(kb, text="🧱 LEGO Style", callback_data=MenuCallbacks.LEGO_STYLE)
    add_button(kb, text="✨ Шикарный коллаж", callback_data=MenuCallbacks.GLAM_COLLAGE)
    add_button(kb, text="⬅️ Назад", callback_data=MenuCallbacks.PHOTO, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def video_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="🎬 Оживить видео", callback_data=MenuCallbacks.ANIMATE)
    add_button(
        kb,
        text="🎞 Оживить фото по видео",
        callback_data=MenuCallbacks.MOTION_CONTROL,
    )
    add_button(kb, text="⬅️ В меню", callback_data=MenuCallbacks.BACK, style="danger")
    kb.adjust(1)
    return kb.as_markup()


def photo_settings_kb(s: UserPhotoSettings) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    add_button(
        kb,
        text=f"📐 Соотношение: {s.aspect_ratio}",
        callback_data=SettingsCallbacks.ASPECT,
    )
    add_button(
        kb,
        text=f"🖼 Разрешение: {s.resolution}",
        callback_data=SettingsCallbacks.RESOLUTION,
    )
    add_button(
        kb,
        text=f"🗂 Формат: {s.output_format}",
        callback_data=SettingsCallbacks.FORMAT,
    )
    add_button(kb, text="🔄 Сбросить по умолчанию", callback_data=SettingsCallbacks.RESET)
    add_button(kb, text="⬅️ Назад", callback_data=SettingsCallbacks.BACK, style="danger")

    kb.adjust(1)
    return kb.as_markup()
