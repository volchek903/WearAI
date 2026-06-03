from __future__ import annotations

import logging
import os
import time

from aiogram.enums import ChatType
from aiogram.methods import SendMessageDraft
from aiogram.types import Message

from app.utils.content_media import TG_MAX_MESSAGE_CHARS

logger = logging.getLogger(__name__)

_DEFAULT_DRAFT_INTERVAL_S = 0.35
_DEFAULT_DRAFT_MIN_CHARS = 48
_HEAD_TAIL_SEPARATOR = "\n...\n"


def _read_float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.05, float(raw))
    except ValueError:
        logger.warning("tg_stream: invalid %s=%r, fallback to %s", name, raw, default)
        return default


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("tg_stream: invalid %s=%r, fallback to %s", name, raw, default)
        return default


def _build_visible_draft_text(text: str, *, limit: int = TG_MAX_MESSAGE_CHARS) -> str:
    if len(text) <= limit:
        return text

    tail_limit = min(1200, max(300, limit // 3))
    head_limit = max(0, limit - tail_limit - len(_HEAD_TAIL_SEPARATOR))
    head = text[:head_limit].rstrip()
    tail = text[-tail_limit:].lstrip()
    return f"{head}{_HEAD_TAIL_SEPARATOR}{tail}"


class TelegramDraftStreamer:
    def __init__(self, message: Message) -> None:
        self._message = message
        self._draft_id = int(time.time() * 1000) % 2147483647
        self._update_interval_s = _read_float_env(
            "WEARAI_AGENT_STREAM_DRAFT_INTERVAL_S",
            _DEFAULT_DRAFT_INTERVAL_S,
        )
        self._min_chars_per_update = _read_int_env(
            "WEARAI_AGENT_STREAM_MIN_CHARS",
            _DEFAULT_DRAFT_MIN_CHARS,
        )
        self._enabled = message.chat.type == ChatType.PRIVATE
        self._started = False
        self._last_update_ts = 0.0
        self._last_sent_text = ""
        self._pending_chars = 0
        self._full_text = ""

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start(self) -> None:
        if not self._enabled or self._started:
            return
        self._started = True
        await self._send("")

    async def push(self, delta: str) -> None:
        text = delta or ""
        if not text:
            return

        self._full_text += text
        self._pending_chars += len(text)
        if not self._enabled:
            return
        if not self._started:
            await self.start()

        now = time.monotonic()
        if (
            self._pending_chars >= self._min_chars_per_update
            and (now - self._last_update_ts) >= self._update_interval_s
        ):
            await self.flush()

    async def flush(self, *, force: bool = False) -> None:
        if not self._enabled or not self._started:
            return
        if not force and self._pending_chars < self._min_chars_per_update:
            return

        visible_text = _build_visible_draft_text(self._full_text)
        if not force and visible_text == self._last_sent_text:
            return
        await self._send(visible_text)

    async def _send(self, text: str) -> None:
        if not self._enabled:
            return

        try:
            await self._message.bot(
                SendMessageDraft(
                    chat_id=self._message.chat.id,
                    draft_id=self._draft_id,
                    text=text,
                    message_thread_id=self._message.message_thread_id,
                )
            )
        except Exception:
            logger.exception("tg_stream: sendMessageDraft failed, fallback to regular reply")
            self._enabled = False
            return

        self._last_sent_text = text
        self._last_update_ts = time.monotonic()
        self._pending_chars = 0
