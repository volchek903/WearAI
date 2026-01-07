from __future__ import annotations

from typing import Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup


async def edit_text_safe(
    call: CallbackQuery,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """
    Telegram часто кидает исключения:
    - message is not modified
    - can't edit message
    Поэтому редактируем "по возможности", иначе отправляем новое сообщение.
    """
    if call.message is None:
        return

    try:
        await call.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        await call.message.answer(text, reply_markup=reply_markup)
