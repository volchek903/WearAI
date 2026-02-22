from __future__ import annotations


SUPPORT_TEXT = "Обратитесь в тех поддержку @wearaimanager и мы вам поможем с любой проблемой"
LAUNCH_LIMITS_MESSAGE = (
    "Превышен лимит бесплатных генераций в день. "
    "Бесплатные генерации недоступны до обновления лимитов."
)


def with_support(text: str) -> str:
    if not text:
        return SUPPORT_TEXT
    if SUPPORT_TEXT in text:
        return text
    return f"{text}\n\n{SUPPORT_TEXT}"


def launch_limits_message() -> str:
    return with_support(LAUNCH_LIMITS_MESSAGE)
