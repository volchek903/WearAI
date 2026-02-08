from __future__ import annotations

from pathlib import Path
import logging

from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardMarkup,
    Message,
    InputMediaPhoto,
)

logger = logging.getLogger(__name__)


def _content_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "content"


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
) -> None:
    try:
        path = _content_dir() / filename
        data = path.read_bytes()
        file = BufferedInputFile(data, filename=filename)
        if len(data) > TG_MAX_PHOTO_BYTES:
            await message.answer_document(
                file, caption=caption, reply_markup=reply_markup, parse_mode=parse_mode
            )
            return
        await message.answer_photo(
            file,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception as e:
        logger.warning("send_content_photo failed: %s", e)


async def send_content_album(
    message: Message,
    *,
    filenames: list[str],
    caption: str | None = None,
    parse_mode: str | None = None,
) -> None:
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
            cap = caption if i == 0 else None
            try:
                await message.answer_document(f, caption=cap, parse_mode=parse_mode)
            except Exception as e:
                logger.warning("send_content_album document failed: %s", e)
        return

    media: list[InputMediaPhoto] = []
    for i, f in enumerate(files):
        if i == 0 and caption:
            media.append(
                InputMediaPhoto(
                    media=f,
                    caption=caption,
                    parse_mode=parse_mode,
                )
            )
        else:
            media.append(InputMediaPhoto(media=f))
    try:
        await message.answer_media_group(media=media)
    except Exception as e:
        logger.warning("send_content_album failed: %s", e)
TG_MAX_PHOTO_BYTES = 10_485_760  # 10 MB
