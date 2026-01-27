from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.help import HelpCallbacks


class ConfirmCallbacks:
    YES = "confirm:yes"
    NO = "confirm:no"

    EDIT_MODEL = "edit:model"
    EDIT_PHOTOS = "edit:photos"
    EDIT_PRESENTATION = "edit:presentation"


def yes_no_kb(
    yes_text: str = "✅ Подтвердить выбор",
    no_text: str = "✏️ Изменить",
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=yes_text, callback_data=ConfirmCallbacks.YES)
    kb.button(text=no_text, callback_data=ConfirmCallbacks.NO)
    kb.adjust(2)
    return kb.as_markup()


def review_edit_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Всё верно", callback_data=ConfirmCallbacks.YES)
    kb.button(text="✏️ Описание модели", callback_data=ConfirmCallbacks.EDIT_MODEL)
    kb.button(text="🖼️ Фото товара", callback_data=ConfirmCallbacks.EDIT_PHOTOS)
    kb.button(text="📝 Подача товара", callback_data=ConfirmCallbacks.EDIT_PRESENTATION)
    kb.adjust(1, 2, 1)
    return kb.as_markup()


def yes_no_tryon_kb() -> InlineKeyboardMarkup:
    return yes_no_kb(
        yes_text="✅ Да, подтверждаю",
        no_text="🔁 Выбрать другую",
    )


def yes_no_tryon_kb_with_help() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, подтверждаю", callback_data=ConfirmCallbacks.YES)
    kb.button(text="🔁 Выбрать другую", callback_data=ConfirmCallbacks.NO)
    kb.button(
        text="🪄 Помочь со стилем", callback_data=f"{HelpCallbacks.START}:tryon_desc"
    )
    kb.adjust(2, 1)
    return kb.as_markup()
