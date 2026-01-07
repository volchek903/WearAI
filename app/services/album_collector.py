from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class AlbumResult:
    file_ids: List[str]


class AlbumCollector:
    """
    Собирает file_id фото из media_group_id (альбом).
    Логика:
      - push() кладёт очередное фото в буфер
      - collect() ждёт debounce, затем отдаёт весь список и очищает буфер
    """

    def __init__(self, debounce_seconds: float = 0.8) -> None:
        self._debounce = debounce_seconds
        self._items: Dict[Tuple[int, str], List[str]] = {}
        self._locks: Dict[Tuple[int, str], asyncio.Lock] = {}

    async def push(self, chat_id: int, media_group_id: str, file_id: str) -> None:
        key = (chat_id, media_group_id)
        if key not in self._items:
            self._items[key] = []
            self._locks[key] = asyncio.Lock()

        async with self._locks[key]:
            self._items[key].append(file_id)

    async def collect(self, chat_id: int, media_group_id: str) -> AlbumResult:
        key = (chat_id, media_group_id)

        # ждём пока Telegram досыпет все сообщения альбома
        await asyncio.sleep(self._debounce)

        if key not in self._items:
            return AlbumResult(file_ids=[])

        async with self._locks[key]:
            file_ids = list(self._items.get(key, []))
            # очистка
            self._items.pop(key, None)
            self._locks.pop(key, None)
            return AlbumResult(file_ids=file_ids)
