from __future__ import annotations

import asyncio
import logging
import sys
import time
from collections import deque

from aiogram import Bot


class TgErrorReporter(logging.Handler):
    def __init__(
        self,
        *,
        bot: Bot,
        chat_id: int,
        max_lines: int = 30,
        cooldown_sec: int = 20,
        ignore_loggers: set[str] | None = None,
        ignore_phrases: set[str] | None = None,
    ) -> None:
        super().__init__(level=logging.INFO)
        self._bot = bot
        self._chat_id = chat_id
        self._buf: deque[str] = deque(maxlen=max_lines)
        self._cooldown_sec = cooldown_sec
        self._last_sent = 0.0
        self._ignore_loggers = ignore_loggers or set()
        self._ignore_phrases = ignore_phrases or set()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            self._buf.append(line)

            if record.levelno < logging.ERROR:
                return

            if record.name in self._ignore_loggers:
                return
            if any(p in line for p in self._ignore_phrases):
                return

            now = time.time()
            if now - self._last_sent < self._cooldown_sec:
                return

            self._last_sent = now
            self._schedule_send(line)
        except Exception:
            # Don't break logging on reporter failure.
            pass

    def _schedule_send(self, headline: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _send() -> None:
            tail = "\n".join(self._buf)
            text = f"❗️Ошибка:\n{headline}\n\nПоследние логи:\n{tail}"
            # Telegram limit ~4096 chars
            if len(text) > 4000:
                text = text[-4000:]
            try:
                await self._bot.send_message(self._chat_id, text)
            except Exception:
                pass

        loop.create_task(_send())


def install_tg_error_logging(
    *,
    bot: Bot,
    chat_id: int,
    logger: logging.Logger | None = None,
) -> None:
    logger = logger or logging.getLogger()
    handler = TgErrorReporter(
        bot=bot,
        chat_id=chat_id,
        ignore_loggers={"aiogram.dispatcher"},
        ignore_phrases={
            "Failed to fetch updates - TelegramNetworkError",
            "Failed to fetch updates - TelegramServerError",
            "ServerDisconnectedError",
            "Bad Gateway",
        },
    )
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    def _excepthook(exc_type, exc, tb) -> None:
        logger.exception("Unhandled exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = _excepthook

    try:
        loop = asyncio.get_event_loop()

        def _loop_exception_handler(loop, context) -> None:
            err = context.get("exception")
            if err:
                logger.exception("Asyncio exception", exc_info=err)
            else:
                logger.error("Asyncio error: %s", context.get("message"))

        loop.set_exception_handler(_loop_exception_handler)
    except Exception:
        pass
