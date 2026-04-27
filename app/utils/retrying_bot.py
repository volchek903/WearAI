from __future__ import annotations

import asyncio
import logging
from typing import Any, TypeVar

from aiogram import Bot
from aiogram.client.session.base import TelegramType
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import TelegramMethod

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=TelegramType)


class RetryingBot(Bot):
    def __init__(
        self,
        *args: Any,
        retry_after_attempts: int = 2,
        retry_after_max_sleep_s: float = 30.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._retry_after_attempts = max(0, int(retry_after_attempts))
        self._retry_after_max_sleep_s = max(0.0, float(retry_after_max_sleep_s))

    async def __call__(
        self,
        method: TelegramMethod[T],
        request_timeout: int | None = None,
    ) -> T:
        last_exc: TelegramRetryAfter | None = None

        for attempt in range(self._retry_after_attempts + 1):
            try:
                return await super().__call__(method, request_timeout=request_timeout)
            except TelegramRetryAfter as e:
                last_exc = e
                if attempt >= self._retry_after_attempts:
                    raise

                sleep_for = min(
                    max(0.0, float(getattr(e, "retry_after", 1) or 1)),
                    self._retry_after_max_sleep_s,
                )
                logger.warning(
                    "telegram retry-after: method=%s attempt=%s/%s sleep=%.2fs",
                    method.__class__.__name__,
                    attempt + 1,
                    self._retry_after_attempts + 1,
                    sleep_for,
                )
                await asyncio.sleep(sleep_for)

        if last_exc is not None:
            raise last_exc
        return await super().__call__(method, request_timeout=request_timeout)
