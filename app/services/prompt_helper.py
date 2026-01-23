from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


class PromptHelperError(RuntimeError):
    pass


@dataclass(slots=True)
class OpenRouterConfig:
    api_key: str
    model: str = "openai/gpt-oss-120b"
    base_url: str = "https://openrouter.ai/api/v1"
    timeout_s: float = 60.0
    http_referer: str | None = None  # optional
    x_title: str | None = None  # optional


def _section_instruction(section: str) -> str:
    section = (section or "").strip()

    if section == "presentation_desc":
        return (
            "Ты — ассистент, который пишет промпты для генерации изображений моделью nano-banana-pro.\n"
            "Сгенерируй ОДИН итоговый промпт на русском языке.\n"
            "Он должен описывать кадр и подачу товара: где товар находится (на руке/ушах/ногтях и т.д.), "
            "ракурс, план (крупный/по пояс/портрет), свет, фон, стиль.\n"
            "Важно: проси сохранить товар максимально точным по референс-фото (цвет/фактура/форма/принты/логотипы).\n"
            "Запрещено: markdown, списки, кавычки, пояснения.\n"
            "Формат ответа: только промпт (1 абзац)."
        )

    if section == "model_desc":
        return (
            "Ты — ассистент, который пишет промпты для генерации изображений моделью nano-banana-pro.\n"
            "Сгенерируй ОДИН итоговый промпт на русском языке.\n"
            "Он должен описывать внешность модели и постановку кадра: возраст, внешность, стиль/одежда, "
            "поза, выражение лица, свет, фон, композиция.\n"
            "Запрещено: markdown, списки, кавычки, пояснения.\n"
            "Формат ответа: только промпт (1 абзац)."
        )

    if section == "tryon_desc":
        return (
            "Ты — ассистент, который пишет промпты для генерации изображений моделью nano-banana-pro.\n"
            "Сгенерируй ОДИН итоговый промпт на русском языке для виртуальной примерки одежды (try-on): "
            "часть тела/кадр, как должна сидеть вещь, реалистичность ткани/складок, свет, фон, поза.\n"
            "Важно: сохранить идентичность человека с фото и точность вещи по фото.\n"
            "Запрещено: markdown, списки, кавычки, пояснения.\n"
            "Формат ответа: только промпт (1 абзац)."
        )

    return (
        "Ты — ассистент, который пишет промпты для генерации изображений моделью nano-banana-pro.\n"
        "Сгенерируй ОДИН итоговый промпт на русском языке по вводу пользователя.\n"
        "Запрещено: markdown, списки, кавычки, пояснения.\n"
        "Формат ответа: только промпт (1 абзац)."
    )


def _user_payload(section: str, user_text: str) -> str:
    return (
        f"Раздел: {section}\n"
        "Ввод пользователя:\n"
        f"{user_text}\n\n"
        "Собери итоговый промпт."
    )


def _extract_chat_content(payload: dict[str, Any]) -> str:
    # OpenAI-совместимый формат: choices[0].message.content
    choices = payload.get("choices") or []
    if not choices:
        raise PromptHelperError(f"OpenRouter response has no choices: {payload}")

    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        raise PromptHelperError(f"OpenRouter response has empty content: {payload}")

    return content.strip()


def _load_cfg() -> OpenRouterConfig:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise PromptHelperError("OPENROUTER_API_KEY is not set in .env")

    model = (
        os.getenv("OPENROUTER_MODEL", "bytedance-seed/seed-1.6-flash").strip()
        or "bytedance-seed/seed-1.6-flash"
    )
    http_referer = os.getenv("OPENROUTER_HTTP_REFERER", "").strip() or None
    x_title = os.getenv("OPENROUTER_X_TITLE", "").strip() or None

    return OpenRouterConfig(
        api_key=api_key,
        model=model,
        http_referer=http_referer,
        x_title=x_title,
    )


async def generate_nano_banana_prompt_ru(section: str, user_text: str) -> str:
    """
    Генерирует русский промпт для nano-banana-pro, используя OpenRouter + bytedance-seed/seed-1.6-flash.
    """
    cfg = _load_cfg()

    url = f"{cfg.base_url}/chat/completions"

    headers: dict[str, str] = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    # Эти заголовки опциональны, но рекомендуются OpenRouter для идентификации приложения
    if cfg.http_referer:
        headers["HTTP-Referer"] = cfg.http_referer
    if cfg.x_title:
        headers["X-Title"] = cfg.x_title

    system = _section_instruction(section)
    user = _user_payload(section, user_text)

    body = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
        "max_tokens": 700,
    }

    async with httpx.AsyncClient(timeout=cfg.timeout_s) as client:
        resp = await client.post(url, headers=headers, json=body)

    if resp.status_code >= 400:
        raise PromptHelperError(f"OpenRouter error [{resp.status_code}]: {resp.text}")

    return _extract_chat_content(resp.json())
