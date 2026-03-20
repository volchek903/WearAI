from __future__ import annotations

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

STYLE_SUCCESS = "success"
STYLE_DANGER = "danger"

_DANGER_EMOJI = ("❌", "⛔", "🚫", "🛑", "🗑", "🔴", "➖")
_SUCCESS_EMOJI = ("✅", "✔️", "🟢", "💚", "💳", "🎁", "💞", "❤️")

_DANGER_WORDS = ("отмен", "удал", "сброс")
_SUCCESS_WORDS = (
    "подтверд",
    "готово",
    "купить",
    "оплат",
    "создать",
    "использовать",
    "подпис",
    "всё отлично",
)


def add_button(kb: InlineKeyboardBuilder, *, text: str, **kwargs) -> None:
    kb.button(text=text, **kwargs)


def make_button(*, text: str, **kwargs) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, **kwargs)
