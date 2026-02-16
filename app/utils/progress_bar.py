from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Awaitable, Callable

ProgressUpdate = Callable[[str], Awaitable[None]]


PROGRESS_CYCLE: list[str] = [
    "⏳ Генерирую...\n▱▱▱▱▱▱▱▱▱▱",
    "⏳ Генерирую...\n▰▱▱▱▱▱▱▱▱▱",
    "⏳ Генерирую...\n▰▰▱▱▱▱▱▱▱▱",
    "⏳ Генерирую...\n▰▰▰▱▱▱▱▱▱▱",
    "⏳ Генерирую...\n▰▰▰▰▱▱▱▱▱▱",
    "⏳ Генерирую...\n▰▰▰▰▰▱▱▱▱▱",
    "⏳ Генерирую...\n▰▰▰▰▰▰▱▱▱▱",
    "⏳ Генерирую...\n▰▰▰▰▰▰▰▱▱▱",
    "⏳ Генерирую...\n▰▰▰▰▰▰▰▰▱▱",
    "⏳ Генерирую...\n▰▰▰▰▰▰▰▰▰▱",
    "⏳ Генерирую...\n▰▰▰▰▰▰▰▰▰▰",
]


def progress_initial_text() -> str:
    return PROGRESS_CYCLE[0]


async def _safe_update(update: ProgressUpdate, text: str) -> None:
    try:
        await update(text)
    except Exception:
        return


async def progress_loop(
    update: ProgressUpdate, stop: asyncio.Event, interval_s: float = 5.0
) -> None:
    while not stop.is_set():
        for frame in PROGRESS_CYCLE:
            if stop.is_set():
                return
            await _safe_update(update, frame)
            await asyncio.sleep(interval_s)


async def stop_progress(stop: asyncio.Event, task: asyncio.Task) -> None:
    stop.set()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
