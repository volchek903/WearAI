from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery


async def safe_answer(
    call: CallbackQuery, text: str | None = None, *, show_alert: bool = False
) -> None:
    try:
        if text:
            await call.answer(text, show_alert=show_alert)
        else:
            await call.answer()
    except TelegramBadRequest:
        # query is too old / invalid, ignore
        return
    except Exception:
        return
