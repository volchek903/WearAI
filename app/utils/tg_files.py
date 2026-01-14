from __future__ import annotations

from typing import Dict, Tuple

from aiogram import Bot

# (tg_id, file_id) -> bytes
_TG_BYTES_CACHE: Dict[Tuple[int, str], bytes] = {}


def clear_tg_bytes_cache_for_user(tg_id: int) -> None:
    to_del = [k for k in _TG_BYTES_CACHE.keys() if k[0] == tg_id]
    for k in to_del:
        _TG_BYTES_CACHE.pop(k, None)


async def tg_file_id_to_bytes(bot: Bot, file_id: str, *, tg_id: int) -> bytes:
    key = (tg_id, file_id)
    if key in _TG_BYTES_CACHE:
        return _TG_BYTES_CACHE[key]

    file = await bot.get_file(file_id)
    content = await bot.download_file(file.file_path)
    data = content.read()

    _TG_BYTES_CACHE[key] = data
    return data
