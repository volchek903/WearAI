from __future__ import annotations


SUPPORT_TEXT = "Обратитесь в тех поддержку @wearaimanager и мы вам поможем с любой проблемой"


def with_support(text: str) -> str:
    if not text:
        return SUPPORT_TEXT
    if SUPPORT_TEXT in text:
        return text
    return f"{text}\n\n{SUPPORT_TEXT}"
