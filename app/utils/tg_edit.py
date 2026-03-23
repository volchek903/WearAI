from __future__ import annotations

import asyncio
import logging
from typing import Optional, Union

from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)


async def _send_fallback_message(
    msg: Message, text: str, **kwargs: object
) -> None:
    try:
        await msg.answer(text, **kwargs)
    except TelegramNetworkError as e:
        logger.warning("Telegram network error while sending fallback message: %s", e)


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

    kwargs = {"reply_markup": reply_markup}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode

    try:
        if msg.photo or msg.document or msg.video or msg.animation:
            await msg.edit_caption(caption=text, **kwargs)
        else:
            await msg.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        await _send_fallback_message(msg, text, **kwargs)
    except TelegramNetworkError as e:
        logger.warning("Telegram network error while editing message: %s", e)
        await asyncio.sleep(0.5)
        try:
            if msg.photo or msg.document or msg.video or msg.animation:
                await msg.edit_caption(caption=text, **kwargs)
            else:
                await msg.edit_text(text, **kwargs)
        except TelegramBadRequest as retry_error:
            if "message is not modified" in str(retry_error):
                return
            await _send_fallback_message(msg, text, **kwargs)
        except TelegramNetworkError as retry_error:
            logger.warning(
                "Telegram network error while retrying message edit: %s",
                retry_error,
            )
            await _send_fallback_message(msg, text, **kwargs)
