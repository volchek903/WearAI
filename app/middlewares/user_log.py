from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

log = logging.getLogger("user_actions")


def _short(text: str, limit: int = 300) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 3] + "..."


class UserActionLogMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        try:
            self._log_event(event)
        except Exception:
            log.exception("Failed to log user action")

        return await handler(event, data)

    def _log_event(self, event: TelegramObject) -> None:
        if isinstance(event, Message):
            self._log_message(event)
            return
        if isinstance(event, CallbackQuery):
            self._log_callback(event)
            return

    def _log_message(self, message: Message) -> None:
        user = message.from_user
        if not user:
            return

        has_photo = bool(message.photo)
        text = message.text or message.caption or ""

        log.info(
            "MSG | tg_id=%s | username=%s | chat_id=%s | has_photo=%s | text=%s",
            user.id,
            user.username,
            message.chat.id if message.chat else None,
            has_photo,
            _short(text),
        )

    def _log_callback(self, call: CallbackQuery) -> None:
        user = call.from_user
        data = call.data or ""
        msg_id: Optional[int] = call.message.message_id if call.message else None

        log.info(
            "CBQ | tg_id=%s | username=%s | msg_id=%s | data=%s",
            user.id,
            user.username,
            msg_id,
            _short(data, 200),
        )
