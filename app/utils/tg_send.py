from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, Message

logger = logging.getLogger(__name__)

TG_MAX_PHOTO_BYTES = 10_485_760  # 10 MB


async def send_image_smart(
    message: Message, *, img_bytes: bytes, filename: str, caption: str | None = None
) -> Message:
    """
    Если <= 10MB — photo, иначе document.
    Всегда возвращает Message (что реально отправили).
    """
    size = len(img_bytes)

    if size <= TG_MAX_PHOTO_BYTES:
        try:
            return await message.answer_photo(
                BufferedInputFile(img_bytes, filename=filename),
                caption=caption,
            )
        except TelegramBadRequest as e:
            logger.warning(
                "sendPhoto failed, fallback to document. file=%s size=%d err=%s",
                filename,
                size,
                e,
            )

    return await message.answer_document(
        BufferedInputFile(img_bytes, filename=filename),
        caption=caption,
    )
