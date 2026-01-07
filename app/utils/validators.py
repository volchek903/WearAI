from __future__ import annotations


MAX_TEXT_LEN = 20_000


def is_text_too_long(text: str, limit: int = MAX_TEXT_LEN) -> bool:
    return len(text) > limit
