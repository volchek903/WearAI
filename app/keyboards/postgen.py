from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


# Контекст "model" = раздел "Модель с товаром"
# Потом для второго раздела добавишь "tryon" аналогично.
def postgen_feedback_kb(ctx: str = "model") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛠 Сообщить об ошибке", callback_data=f"postgen:{ctx}:report")
    kb.button(text="✅ Всё хорошо", callback_data=f"postgen:{ctx}:ok")
    kb.adjust(1)
    return kb.as_markup()


def postgen_offer_video_kb(ctx: str = "model") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Вернуться в меню", callback_data=f"postgen:{ctx}:menu")
    kb.button(text="🎬 Оживить фото", callback_data=f"postgen:{ctx}:animate")
    kb.adjust(1)
    return kb.as_markup()
