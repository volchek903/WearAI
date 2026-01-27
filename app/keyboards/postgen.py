from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class PostGenCallbacks:
    PREFIX = "postgen"

    @staticmethod
    def report(ctx: str) -> str:
        return f"{PostGenCallbacks.PREFIX}:{ctx}:report"

    @staticmethod
    def ok(ctx: str) -> str:
        return f"{PostGenCallbacks.PREFIX}:{ctx}:ok"

    @staticmethod
    def menu(ctx: str) -> str:
        return f"{PostGenCallbacks.PREFIX}:{ctx}:menu"

    @staticmethod
    def animate(ctx: str) -> str:
        return f"{PostGenCallbacks.PREFIX}:{ctx}:animate"


def postgen_feedback_kb(ctx: str = "model") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛠 Сообщить об ошибке", callback_data=PostGenCallbacks.report(ctx))
    kb.button(text="✅ Всё отлично", callback_data=PostGenCallbacks.ok(ctx))
    kb.adjust(1)
    return kb.as_markup()


def postgen_offer_video_kb(ctx: str = "model") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В меню", callback_data=PostGenCallbacks.menu(ctx))
    kb.button(text="🎬 Оживить фото", callback_data=PostGenCallbacks.animate(ctx))
    kb.adjust(1)
    return kb.as_markup()
