from __future__ import annotations

import asyncio
import logging
from typing import Dict, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError

# (tg_id, file_id) -> bytes
_TG_BYTES_CACHE: Dict[Tuple[int, str], bytes] = {}
logger = logging.getLogger(__name__)


def _is_transient_download_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    markers = {
        "clientoserror",
        "connection reset by peer",
        "connection lost",
        "server disconnected",
        "ssl",
        "timeout",
    }
    return any(marker in text for marker in markers)


async def _download_tg_file_bytes(bot: Bot, file_id: str) -> bytes:
    file = await bot.get_file(file_id)
    content = await bot.download_file(file.file_path)
    return content.read()


def clear_tg_bytes_cache_for_user(tg_id: int) -> None:
    to_del = [k for k in _TG_BYTES_CACHE.keys() if k[0] == tg_id]
    for k in to_del:
        _TG_BYTES_CACHE.pop(k, None)


async def tg_file_id_to_bytes(bot: Bot, file_id: str, *, tg_id: int) -> bytes:
    key = (tg_id, file_id)
    if key in _TG_BYTES_CACHE:
        return _TG_BYTES_CACHE[key]

    attempts = 3
    data: bytes | None = None
    last_error: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            data = await _download_tg_file_bytes(bot, file_id)
            break
        except TelegramNetworkError as e:
            last_error = e
            if attempt >= attempts or not _is_transient_download_error(e):
                raise
            logger.warning(
                "Telegram file download retry %d/%d for tg_id=%s file_id=%s: %s",
                attempt,
                attempts,
                tg_id,
                file_id,
                e,
            )
            await asyncio.sleep(0.75 * attempt)

    if data is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Failed to download Telegram file {file_id}")

    _TG_BYTES_CACHE[key] = data
    return data
