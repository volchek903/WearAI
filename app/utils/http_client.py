from __future__ import annotations

from typing import Any

import httpx


def external_httpx_client(*, timeout: Any = None, **kwargs: Any) -> httpx.AsyncClient:
    # `main.py` exports Telegram proxy settings into HTTP(S)_PROXY for the bot.
    # Third-party APIs must bypass that proxy unless configured explicitly.
    return httpx.AsyncClient(timeout=timeout, trust_env=False, **kwargs)
