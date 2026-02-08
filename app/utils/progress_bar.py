from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Awaitable, Callable

ProgressUpdate = Callable[[str], Awaitable[None]]


PROGRESS_TO_90: list[str] = [
    "⏳ Генерирую...\n▱▱▱▱▱▱▱▱▱▱ 0%",
    "⏳ Генерирую...\n▰▱▱▱▱▱▱▱▱▱ 10%",
    "⏳ Генерирую...\n▰▰▱▱▱▱▱▱▱▱ 20%",
    "⏳ Генерирую...\n▰▰▰▱▱▱▱▱▱▱ 30%",
    "⏳ Генерирую...\n▰▰▰▰▱▱▱▱▱▱ 40%",
    "⏳ Генерирую...\n▰▰▰▰▰▱▱▱▱▱ 50%",
    "⏳ Генерирую...\n▰▰▰▰▰▰▱▱▱▱ 60%",
    "⏳ Генерирую...\n▰▰▰▰▰▰▰▱▱▱ 70%",
    "⏳ Генерирую...\n▰▰▰▰▰▰▰▰▱▱ 80%",
    "⏳ Генерирую...\n▰▰▰▰▰▰▰▰▰▱ 90%",
]
PROGRESS_HOLD_90 = "⏳ Генерирую...\n▰▰▰▰▰▰▰▰▰▱ 90%\nОсталось чуть-чуть…"


def progress_initial_text() -> str:
    return PROGRESS_TO_90[0]


async def _safe_update(update: ProgressUpdate, text: str) -> None:
    try:
        await update(text)
    except Exception:
        return


async def progress_loop(
    update: ProgressUpdate, stop: asyncio.Event, interval_s: float = 4.0
) -> None:
    for frame in PROGRESS_TO_90:
        if stop.is_set():
            return
        await _safe_update(update, frame)
        await asyncio.sleep(interval_s)

    while not stop.is_set():
        await _safe_update(update, PROGRESS_HOLD_90)
        await asyncio.sleep(interval_s)


async def stop_progress(stop: asyncio.Event, task: asyncio.Task) -> None:
    stop.set()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
