from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.utils import add_button


class ConfirmCallbacks:
    YES = "confirm:yes"
    NO = "confirm:no"

    EDIT_MODEL = "edit:model"
    EDIT_PHOTOS = "edit:photos"
    EDIT_PRESENTATION = "edit:presentation"


def yes_no_kb(
    yes_text: str = "✅ Подтвердить выбор",
    no_text: str = "✏️ Изменить",
    yes_style: str | None = None,
    no_style: str | None = None,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(
        kb,
        text=yes_text,
        callback_data=ConfirmCallbacks.YES,
        style=yes_style,
    )
    add_button(
        kb,
        text=no_text,
        callback_data=ConfirmCallbacks.NO,
        style=no_style,
    )
    kb.adjust(2)
    return kb.as_markup()


def review_edit_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="✅ Всё верно", callback_data=ConfirmCallbacks.YES)
    add_button(kb, text="✏️ Описание модели", callback_data=ConfirmCallbacks.EDIT_MODEL)
    add_button(kb, text="🖼️ Фото товара", callback_data=ConfirmCallbacks.EDIT_PHOTOS)
    add_button(kb, text="📝 Подача товара", callback_data=ConfirmCallbacks.EDIT_PRESENTATION)
    kb.adjust(1, 2, 1)
    return kb.as_markup()


def yes_no_tryon_kb() -> InlineKeyboardMarkup:
    return yes_no_kb(
        yes_text="✅ Да, подтверждаю",
        no_text="🔁 Выбрать другую",
        no_style="danger",
    )


def yes_no_tryon_kb_with_help() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    add_button(kb, text="✅ Да, подтверждаю", callback_data=ConfirmCallbacks.YES)
    add_button(
        kb, text="🔁 Выбрать другую", callback_data=ConfirmCallbacks.NO, style="danger"
    )
    kb.adjust(2)
    return kb.as_markup()
