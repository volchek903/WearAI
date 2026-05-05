from __future__ import annotations

from pathlib import Path
import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardMarkup,
    Message,
    InputMediaPhoto,
)

logger = logging.getLogger(__name__)

TG_MAX_PHOTO_BYTES = 10_485_760  # 10 MB
TG_MAX_CAPTION_CHARS = 1024
TG_MAX_MESSAGE_CHARS = 4096


def _content_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "content"


def _caption_too_long(caption: str | None) -> bool:
    return bool(caption and len(caption) > TG_MAX_CAPTION_CHARS)


def _is_caption_too_long_error(error: Exception) -> bool:
    return "caption is too long" in str(error).lower()


def _message_kwargs(
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> dict:
    kwargs = {}
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    return kwargs


def _clip_message_text(text: str) -> str:
    if len(text) <= TG_MAX_MESSAGE_CHARS:
        return text
    return text[: TG_MAX_MESSAGE_CHARS - 3].rstrip() + "..."


async def _send_caption_as_text(
    message: Message,
    *,
    caption: str | None,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> None:
    if not caption:
        return

    text = _clip_message_text(caption)
    if len(text) != len(caption):
        logger.warning(
            "caption text is too long for Telegram message; truncated from %d to %d chars",
            len(caption),
            len(text),
        )

    try:
        await message.answer(
            text,
            **_message_kwargs(reply_markup=reply_markup, parse_mode=parse_mode),
        )
    except TelegramBadRequest as e:
        if parse_mode is None:
            raise
        logger.warning(
            "caption text send failed with parse_mode=%s, retrying as plain text: %s",
            parse_mode,
            e,
        )
        await message.answer(text, reply_markup=reply_markup)


def get_content_file(name: str) -> BufferedInputFile:
    path = _content_dir() / name
    data = path.read_bytes()
    return BufferedInputFile(data, filename=name)


async def send_content_photo(
    message: Message,
    *,
    filename: str,
    caption: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
    request_timeout: int = 15,
) -> bool:
    send_caption_separately = _caption_too_long(caption)
    media_caption = None if send_caption_separately else caption
    media_reply_markup = None if send_caption_separately else reply_markup
    media_kwargs = _message_kwargs(
        reply_markup=media_reply_markup,
        parse_mode=parse_mode if media_caption else None,
    )

    try:
        path = _content_dir() / filename
        data = path.read_bytes()
        if len(data) > TG_MAX_PHOTO_BYTES:
            await message.answer_document(
                BufferedInputFile(data, filename=filename),
                caption=media_caption,
                request_timeout=request_timeout,
                **media_kwargs,
            )
        else:
            await message.answer_photo(
                BufferedInputFile(data, filename=filename),
                caption=media_caption,
                request_timeout=request_timeout,
                **media_kwargs,
            )
        if send_caption_separately:
            await _send_caption_as_text(
                message,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        return True
    except TelegramBadRequest as e:
        if media_caption and _is_caption_too_long_error(e):
            logger.warning(
                "send_content_photo caption too long after Telegram validation; retrying without caption"
            )
            try:
                if len(data) > TG_MAX_PHOTO_BYTES:
                    await message.answer_document(
                        BufferedInputFile(data, filename=filename),
                        request_timeout=request_timeout,
                    )
                else:
                    await message.answer_photo(
                        BufferedInputFile(data, filename=filename),
                        request_timeout=request_timeout,
                    )
                await _send_caption_as_text(
                    message,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
                return True
            except Exception as retry_error:
                logger.warning("send_content_photo retry failed: %s", retry_error)
                return False
        logger.warning("send_content_photo failed: %s", e)
        return False
    except Exception as e:
        logger.warning("send_content_photo failed: %s", e)
        return False


async def send_content_album(
    message: Message,
    *,
    filenames: list[str],
    caption: str | None = None,
    parse_mode: str | None = None,
    request_timeout: int = 15,
) -> None:
    send_caption_separately = _caption_too_long(caption)
    media_caption = None if send_caption_separately else caption

    files: list[BufferedInputFile] = []
    sizes: list[int] = []
    for name in filenames:
        path = _content_dir() / name
        data = path.read_bytes()
        files.append(BufferedInputFile(data, filename=name))
        sizes.append(len(data))
    if any(size > TG_MAX_PHOTO_BYTES for size in sizes):
        # fallback: send as documents (no album)
        for i, f in enumerate(files):
            cap = media_caption if i == 0 else None
            try:
                await message.answer_document(
                    f,
                    caption=cap,
                    request_timeout=request_timeout,
                    **_message_kwargs(parse_mode=parse_mode if cap else None),
                )
            except Exception as e:
                logger.warning("send_content_album document failed: %s", e)
        if send_caption_separately:
            await _send_caption_as_text(
                message, caption=caption, parse_mode=parse_mode
            )
        return

    media: list[InputMediaPhoto] = []
    for i, f in enumerate(files):
        if i == 0 and media_caption:
            media.append(
                InputMediaPhoto(
                    media=f,
                    caption=media_caption,
                    **({"parse_mode": parse_mode} if parse_mode is not None else {}),
                )
            )
        else:
            media.append(InputMediaPhoto(media=f))
    try:
        await message.answer_media_group(media=media, request_timeout=request_timeout)
        if send_caption_separately:
            await _send_caption_as_text(
                message, caption=caption, parse_mode=parse_mode
            )
    except TelegramBadRequest as e:
        if media_caption and _is_caption_too_long_error(e):
            logger.warning(
                "send_content_album caption too long after Telegram validation; retrying without caption"
            )
            retry_media = [InputMediaPhoto(media=f) for f in files]
            try:
                await message.answer_media_group(
                    media=retry_media, request_timeout=request_timeout
                )
                await _send_caption_as_text(
                    message, caption=caption, parse_mode=parse_mode
                )
            except Exception as retry_error:
                logger.warning("send_content_album retry failed: %s", retry_error)
            return
        logger.warning("send_content_album failed: %s", e)
    except Exception as e:
        logger.warning("send_content_album failed: %s", e)
