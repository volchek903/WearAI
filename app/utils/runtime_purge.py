from __future__ import annotations

from aiogram.fsm.context import FSMContext

from app.services.album_collector import album_collector
from app.utils.tg_files import clear_tg_bytes_cache_for_user


async def purge_user_runtime_caches(
    *, state: FSMContext, tg_id: int, chat_id: int
) -> None:
    # 1) FSM
    await state.clear()

    # 2) Album collector
    album_collector.clear_chat(chat_id)

    # 3) Telegram bytes cache (если используешь)
    clear_tg_bytes_cache_for_user(tg_id)
