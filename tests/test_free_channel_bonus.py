from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from app.services import free_channel_bonus


class _BotStub:
    def __init__(self, send_message: AsyncMock) -> None:
        self.send_message = send_message


class FreeChannelBonusTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_message_safe_ignores_blocked_user(self) -> None:
        error = TelegramForbiddenError(
            method=SendMessage(chat_id=123, text="hi"),
            message="Forbidden: bot was blocked by the user",
        )
        bot = _BotStub(send_message=AsyncMock(side_effect=error))

        with patch.object(free_channel_bonus, "logger") as logger_mock:
            await free_channel_bonus._send_message_safe(
                bot,
                123,
                "hi",
                log_context="bonus message",
            )

        logger_mock.info.assert_called_once_with(
            "%s skipped tg_id=%s reason=bot_blocked",
            "bonus message",
            123,
        )
        logger_mock.exception.assert_not_called()

    async def test_send_message_safe_logs_unexpected_error(self) -> None:
        bot = _BotStub(send_message=AsyncMock(side_effect=RuntimeError("boom")))

        with patch.object(free_channel_bonus, "logger") as logger_mock:
            await free_channel_bonus._send_message_safe(
                bot,
                456,
                "hello",
                log_context="reminder",
            )

        logger_mock.exception.assert_called_once_with(
            "%s failed tg_id=%s",
            "reminder",
            456,
        )


if __name__ == "__main__":
    unittest.main()
