from __future__ import annotations

from typing import Optional, Union

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


async def edit_text_safe(
    target: Union[CallbackQuery, Message],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = None,
) -> None:
    """
    Telegram часто кидает исключения:
    - message is not modified
    - can't edit message
    Поэтому редактируем "по возможности", иначе отправляем новое сообщение.
    """
    msg: Message | None = (
        target.message if isinstance(target, CallbackQuery) else target
    )
    if msg is None:
        return

    try:
        if msg.photo or msg.document or msg.video or msg.animation:
            await msg.edit_caption(
                caption=text, reply_markup=reply_markup, parse_mode=parse_mode
            )
        else:
            await msg.edit_text(
                text, reply_markup=reply_markup, parse_mode=parse_mode
            )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        await msg.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
