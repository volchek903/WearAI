from __future__ import annotations


SUPPORT_TEXT = "Обратитесь в тех поддержку @wearaimanager и мы вам поможем с любой проблемой"
LAUNCH_LIMITS_MESSAGE = (
    "Ежедневные бесплатные генерации для новых пользователей исчерпаны. "
    "Это может быть связано с большим спросом пользователей. "
    "Лимиты обновятся в 12:00 по мск. "
    "После 12:00 вы сможете воспользоваться своей бесплатной генерацией фото или видео.\n"
    "Вы можете приобрести любой пакет услуг и не обращать внимание на какие-либо лимиты"
)


def with_support(text: str) -> str:
    if not text:
        return SUPPORT_TEXT
    if SUPPORT_TEXT in text:
        return text
    return f"{text}\n\n{SUPPORT_TEXT}"


def launch_limits_message() -> str:
    return with_support(LAUNCH_LIMITS_MESSAGE)
