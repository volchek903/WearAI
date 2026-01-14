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

    Дополнительно:
      - clear_chat(chat_id) очищает все буферы по чату (полезно на /start)
      - clear_all() очищает всё
    """

    def __init__(self, debounce_seconds: float = 0.8) -> None:
        self._debounce = debounce_seconds
        self._items: Dict[Tuple[int, str], List[str]] = {}
        self._locks: Dict[Tuple[int, str], asyncio.Lock] = {}
        # глобальный лок для безопасного создания/удаления ключей
        self._global_lock = asyncio.Lock()

    async def push(self, chat_id: int, media_group_id: str, file_id: str) -> None:
        key = (chat_id, media_group_id)

        # гарантируем наличие lock/буфера под глобальным локом
        async with self._global_lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
                self._items[key] = []

        # добавляем file_id под локом группы
        async with lock:
            # на всякий: ключ мог быть очищен clear_chat/clear_all между локами
            buf = self._items.get(key)
            if buf is None:
                self._items[key] = [file_id]
            else:
                buf.append(file_id)

    async def collect(self, chat_id: int, media_group_id: str) -> AlbumResult:
        key = (chat_id, media_group_id)

        # ждём пока Telegram досыпет все сообщения альбома
        await asyncio.sleep(self._debounce)

        # берём lock (если нет — альбом уже очищен/не существует)
        async with self._global_lock:
            lock = self._locks.get(key)
            if lock is None:
                return AlbumResult(file_ids=[])

        # читаем и очищаем под локом группы
        async with lock:
            file_ids = list(self._items.get(key, []))

            # очищаем записи под глобальным локом,
            # пока держим lock — push не сможет досыпать в этот ключ
            async with self._global_lock:
                self._items.pop(key, None)
                self._locks.pop(key, None)

            return AlbumResult(file_ids=file_ids)

    async def clear_chat(self, chat_id: int) -> None:
        """
        Очищает все накопленные альбомы для указанного чата.
        Вызывать, например, на /start для “жёсткого” сброса.
        """
        async with self._global_lock:
            keys = [k for k in self._locks.keys() if k[0] == chat_id]
            locks = [(k, self._locks[k]) for k in keys]

        # блокируем каждую группу, чтобы никто не пушил/коллектил параллельно
        for key, lock in locks:
            async with lock:
                async with self._global_lock:
                    # удаляем только если ключ всё ещё указывает на тот же lock
                    if self._locks.get(key) is lock:
                        self._items.pop(key, None)
                        self._locks.pop(key, None)

    async def clear_all(self) -> None:
        """
        Полная очистка всех буферов.
        Обычно не нужна, но полезна для админских/диагностических сценариев.
        """
        async with self._global_lock:
            keys = list(self._locks.keys())
            locks = [(k, self._locks[k]) for k in keys]

        for key, lock in locks:
            async with lock:
                async with self._global_lock:
                    if self._locks.get(key) is lock:
                        self._items.pop(key, None)
                        self._locks.pop(key, None)
