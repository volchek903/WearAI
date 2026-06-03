from __future__ import annotations

import asyncio
import html
import inspect
import io
import json
import logging
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, unquote, urljoin, urlsplit
from xml.etree import ElementTree

import httpx

from app.models.agent_document import AgentDocument
from app.models.agent_message import AgentMessage
from app.repository.agent_settings import AgentToggleState
from app.utils.http_client import external_httpx_client

logger = logging.getLogger(__name__)

BASE_SYSTEM_PROMPT = (
    "Ты WeaRai Agent. Отвечай на русском языке, если пользователь не запросил другой язык. "
    "Давай точные, структурированные и полезные ответы. Используй доступный контекст, документы, "
    "историю диалога и результаты поиска при их наличии. Не упоминай внутренние настройки системы, "
    "используемые модели и техническую реализацию."
)
DEEP_ANALYSIS_PROMPT = (
    "Выполни подробный пошаговый анализ запроса, сформируй план решения, "
    "проверь выводы и только после этого сформируй окончательный ответ."
)
QUICK_MODE_PROMPT = (
    "Работай в быстром режиме: отвечай короче, используй только самый важный контекст, "
    "не расписывай промежуточные рассуждения и отдавай приоритет скорости ответа."
)
WEB_SEARCH_PROMPT = (
    "Если доступен веб-поиск, используй факты из найденных материалов и отвечай сразу по существу. "
    "Не отправляй пользователя искать ответ самостоятельно и не ограничивайся списком ссылок."
)
MULTI_QUESTION_PROMPT = (
    "Если пользователь задал несколько вопросов в одном сообщении, ответь на каждый по порядку, "
    "ничего не пропуская. Сначала дай ответ на первый вопрос, затем на второй и последующие, "
    "после этого при необходимости добавь короткий общий итог."
)
CONTINUATION_PROMPT = (
    "Продолжай ответ строго с места остановки. Не повторяй уже написанный текст. "
    "Если в ответе есть код, пришли оставшуюся часть кода полностью."
)

FULL_HISTORY_LIMIT = 12
QUICK_HISTORY_LIMIT = 4
FULL_SEARCH_LIMIT = 5
QUICK_SEARCH_LIMIT = 3
FULL_DOC_CHAR_LIMIT = 16000
QUICK_DOC_CHAR_LIMIT = 5000
FULL_MAX_COMPLETION_TOKENS = 4096
QUICK_MAX_COMPLETION_TOKENS = 500
FULL_WEB_PAGE_LIMIT = 3
QUICK_WEB_PAGE_LIMIT = 1
FULL_WEB_PAGE_CHAR_LIMIT = 2500
QUICK_WEB_PAGE_CHAR_LIMIT = 1200
MAX_AUTO_CONTINUATIONS = 1
OPENROUTER_MAX_ATTEMPTS = 4
MAX_DOC_STORE_CHARS = 30000
MAX_DOC_UPLOAD_BYTES = 10 * 1024 * 1024

DUCKDUCKGO_SEARCH_URLS = (
    "https://lite.duckduckgo.com/lite/",
    "https://html.duckduckgo.com/html/",
    "https://duckduckgo.com/html/",
)
SEARCH_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0 Safari/537.36"
)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript|svg|iframe)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE | re.DOTALL,
)
_CONTENT_BLOCK_RE = re.compile(
    r"<(article|main|section|p|li|h1|h2|h3)[^>]*>(.*?)</\1>",
    re.IGNORECASE | re.DOTALL,
)
_QUESTION_SPLIT_RE = re.compile(r"[?\n;]+")
_QUESTION_WORD_RE = re.compile(
    r"\b("
    r"кто|что|где|куда|откуда|когда|почему|зачем|как|какой|какая|какое|какие|"
    r"какого|какую|каким|какими|сколько|чей|чья|чье|чьи|можно\s+ли|есть\s+ли|"
    r"будет\s+ли|стоит\s+ли|нужно\s+ли|надо\s+ли|how|what|when|where|why|which|who"
    r")\b",
    re.IGNORECASE,
)
_LITE_RESULT_RE = re.compile(
    r"<a(?P<attrs>[^>]*class=['\"]result-link['\"][^>]*)>(?P<title>.*?)</a>.*?"
    r"<td class=['\"]result-snippet['\"]>(?P<snippet>.*?)</td>",
    re.DOTALL | re.IGNORECASE,
)
_HTML_RESULT_RE = re.compile(
    r"<a(?P<attrs>[^>]*class=['\"]result__a['\"][^>]*)>(?P<title>.*?)</a>.*?"
    r"<a[^>]*class=['\"]result__snippet['\"][^>]*>(?P<snippet>.*?)</a>|"
    r"<a(?P<attrs_alt>[^>]*class=['\"]result__a['\"][^>]*)>(?P<title_alt>.*?)</a>.*?"
    r"<div[^>]*class=['\"]result__snippet['\"][^>]*>(?P<snippet_alt>.*?)</div>",
    re.DOTALL | re.IGNORECASE,
)
_HREF_RE = re.compile(r"""href=['"](?P<href>[^'"]+)['"]""", re.IGNORECASE)
_RETRYABLE_OPENROUTER_ERRORS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)


class WeaAgentError(RuntimeError):
    pass


class WeaAgentConfigError(WeaAgentError):
    pass


class UnsupportedDocumentError(WeaAgentError):
    pass


def _format_transport_error(exc: Exception | None) -> str:
    if exc is None:
        return "unknown transport error"
    text = str(exc).strip()
    if not text:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {text}"


@dataclass(frozen=True, slots=True)
class AgentModelConfig:
    api_key: str
    base_url: str
    model_name: str
    timeout_s: float = 60.0
    http_referer: str | None = None
    x_title: str | None = None


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    page_content: str = ""


def load_agent_model_config() -> AgentModelConfig:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise WeaAgentConfigError("OPENROUTER_API_KEY is not set")

    base_url = (
        os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
        or "https://openrouter.ai/api/v1"
    )
    model_name = os.getenv("MODEL_NAME", "qwen/qwen3-235b-a22b").strip() or "qwen/qwen3-235b-a22b"
    http_referer = os.getenv("OPENROUTER_HTTP_REFERER", "").strip() or None
    x_title = os.getenv("OPENROUTER_X_TITLE", "").strip() or None
    timeout_raw = os.getenv("OPENROUTER_TIMEOUT_S", "").strip()
    timeout_s = 60.0
    if timeout_raw:
        try:
            timeout_s = max(10.0, float(timeout_raw))
        except ValueError:
            logger.warning("wea_agent: invalid OPENROUTER_TIMEOUT_S=%r, fallback to 60", timeout_raw)

    return AgentModelConfig(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        model_name=model_name,
        timeout_s=timeout_s,
        http_referer=http_referer,
        x_title=x_title,
    )


def _clean_html_text(value: str) -> str:
    text = html.unescape(_TAG_RE.sub(" ", value or ""))
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _extract_ddg_redirect_url(raw_url: str) -> str:
    url = raw_url or ""
    if url.startswith("//"):
        url = f"https:{url}"
    if "uddg=" not in url:
        return url
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    target = query.get("uddg", [""])[0]
    return unquote(target) or url


def _normalize_question_text(text: str) -> str:
    value = _WHITESPACE_RE.sub(" ", (text or "").strip())
    value = value.strip(" ,;:-")
    value = re.sub(r"\b(?:и|а|но|also|and)\b\s*$", "", value, flags=re.IGNORECASE).strip(" ,;:-")
    return value


def split_user_questions(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []

    parts: list[str] = []
    base_segments = [segment for segment in _QUESTION_SPLIT_RE.split(raw) if segment.strip()]
    if not base_segments:
        base_segments = [raw]

    for segment in base_segments:
        normalized_segment = _normalize_question_text(segment)
        if not normalized_segment:
            continue

        matches = list(_QUESTION_WORD_RE.finditer(normalized_segment))
        if len(matches) <= 1:
            parts.append(normalized_segment)
            continue

        split_points: list[int] = []
        for match in matches[1:]:
            bridge = normalized_segment[: match.start()]
            last_chunk_start = split_points[-1] if split_points else 0
            bridge = normalized_segment[last_chunk_start : match.start()]
            if re.search(r"(,|\bи\b|\bа\b|\bно\b|\balso\b|\band\b)\s*$", bridge, re.IGNORECASE):
                split_points.append(match.start())

        if not split_points:
            parts.append(normalized_segment)
            continue

        segment_parts: list[str] = []
        prev = 0
        for point in split_points:
            chunk = _normalize_question_text(normalized_segment[prev:point])
            if chunk:
                segment_parts.append(chunk)
            prev = point
        tail = _normalize_question_text(normalized_segment[prev:])
        if tail:
            segment_parts.append(tail)
        parts.extend(segment_parts or [normalized_segment])

    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = _normalize_question_text(part)
        if not normalized:
            continue
        lowered = normalized.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(normalized)
    return deduped


def build_user_question_prompt(text: str) -> str:
    normalized_text = (text or "").strip()
    questions = split_user_questions(normalized_text)
    if len(questions) <= 1:
        return normalized_text

    lines = [
        "Пользователь задал несколько вопросов. Ответь на каждый из них по порядку и не пропусти ни один.",
        "",
        "Вопросы пользователя:",
    ]
    for idx, question in enumerate(questions, start=1):
        lines.append(f"{idx}. {question}")
    lines.extend(
        [
            "",
            "Исходное сообщение пользователя:",
            normalized_text,
        ]
    )
    return "\n".join(lines).strip()


def _extract_web_page_text(page_html: str, *, quick_mode: bool) -> str:
    raw_html = page_html or ""
    if not raw_html.strip():
        return ""

    cleaned_html = _SCRIPT_STYLE_RE.sub(" ", raw_html)
    parts: list[str] = []

    title_match = _TITLE_RE.search(cleaned_html)
    if title_match is not None:
        title = _clean_html_text(title_match.group(1))
        if title:
            parts.append(title)

    meta_match = _META_DESC_RE.search(cleaned_html)
    if meta_match is not None:
        meta_description = _clean_html_text(meta_match.group(1))
        if meta_description:
            parts.append(meta_description)

    for _, content in _CONTENT_BLOCK_RE.findall(cleaned_html):
        text = _clean_html_text(content)
        if text and text not in parts:
            parts.append(text)

    if not parts:
        fallback = _clean_html_text(cleaned_html)
        if fallback:
            parts.append(fallback)

    unique_parts: list[str] = []
    used: set[str] = set()
    for part in parts:
        normalized = part.strip()
        if not normalized or normalized in used:
            continue
        used.add(normalized)
        unique_parts.append(normalized)

    limit = QUICK_WEB_PAGE_CHAR_LIMIT if quick_mode else FULL_WEB_PAGE_CHAR_LIMIT
    return _clip("\n".join(unique_parts), limit)


async def _fetch_search_result_content(result: SearchResult, *, quick_mode: bool) -> str:
    try:
        async with external_httpx_client(timeout=15) as client:
            resp = await client.get(
                result.url,
                headers={"User-Agent": SEARCH_USER_AGENT},
                follow_redirects=True,
            )
        resp.raise_for_status()
    except Exception:
        logger.exception("wea_agent.fetch_search_result_content failed: %s", result.url)
        return ""

    content_type = str(resp.headers.get("content-type") or "").lower()
    if content_type and "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        return ""
    return _extract_web_page_text(resp.text, quick_mode=quick_mode)


async def enrich_search_results(results: list[SearchResult], *, quick_mode: bool) -> list[SearchResult]:
    if not results:
        return []

    fetch_limit = QUICK_WEB_PAGE_LIMIT if quick_mode else FULL_WEB_PAGE_LIMIT
    limited_results = results[:fetch_limit]
    fetched_contents = await asyncio.gather(
        *[_fetch_search_result_content(item, quick_mode=quick_mode) for item in limited_results]
    )

    enriched: list[SearchResult] = []
    for idx, item in enumerate(results):
        page_content = fetched_contents[idx] if idx < len(fetched_contents) else ""
        enriched.append(
            SearchResult(
                title=item.title,
                url=item.url,
                snippet=item.snippet,
                page_content=page_content,
            )
        )
    return enriched


def parse_duckduckgo_lite_results(page_html: str, *, limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    html_value = page_html or ""
    for regex in (_LITE_RESULT_RE, _HTML_RESULT_RE):
        for match in regex.finditer(html_value):
            attrs = (match.groupdict().get("attrs") or match.groupdict().get("attrs_alt") or "")
            title_raw = (match.groupdict().get("title") or match.groupdict().get("title_alt") or "")
            snippet_raw = (match.groupdict().get("snippet") or match.groupdict().get("snippet_alt") or "")
            href_match = _HREF_RE.search(attrs)
            if href_match is None:
                continue
            title = _clean_html_text(title_raw)
            snippet = _clean_html_text(snippet_raw)
            url = _extract_ddg_redirect_url(href_match.group("href"))
            if not title or not url:
                continue
            results.append(SearchResult(title=title, url=url, snippet=snippet))
            if len(results) >= max(1, int(limit)):
                return results
    return results


async def search_web(query: str, *, quick_mode: bool) -> list[SearchResult]:
    q = (query or "").strip()
    if not q:
        return []

    limit = QUICK_SEARCH_LIMIT if quick_mode else FULL_SEARCH_LIMIT
    params = {"q": q}
    headers = {"User-Agent": SEARCH_USER_AGENT}

    last_error: Exception | None = None
    for search_url in DUCKDUCKGO_SEARCH_URLS:
        try:
            async with external_httpx_client(timeout=20) as client:
                resp = await client.get(
                    search_url,
                    params=params,
                    headers=headers,
                    follow_redirects=True,
                )
            resp.raise_for_status()
            results = parse_duckduckgo_lite_results(resp.text, limit=limit)
            if results:
                return await enrich_search_results(results, quick_mode=quick_mode)
            logger.warning("wea_agent.search_web: no results parsed from %s", search_url)
        except Exception as exc:
            last_error = exc
            logger.warning("wea_agent.search_web failed for %s: %s", search_url, exc)

    if last_error is not None:
        logger.error(
            "wea_agent.search_web exhausted all providers",
            exc_info=(type(last_error), last_error, last_error.__traceback__),
        )
    return []


def _extract_text_from_content_blocks(content: list[Any]) -> str:
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(part for part in parts if part).strip()


def extract_openrouter_chat_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise WeaAgentError(f"OpenRouter response has no choices: {payload}")

    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        merged = _extract_text_from_content_blocks(content)
        if merged:
            return merged
    raise WeaAgentError(f"OpenRouter response has empty content: {payload}")


def extract_openrouter_stream_delta(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""

    delta = (choices[0] or {}).get("delta") or {}
    content = delta.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _extract_text_from_content_blocks(content)
    return ""


def extract_openrouter_finish_reason(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices") or []
    if not choices:
        return None

    reason = (choices[0] or {}).get("finish_reason")
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    return None


def parse_openrouter_sse_event(raw_event: str) -> dict[str, Any] | str | None:
    data_parts: list[str] = []
    for raw_line in (raw_event or "").splitlines():
        line = raw_line.rstrip("\r")
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_parts.append(line[5:].lstrip())

    if not data_parts:
        return None

    payload = "\n".join(data_parts).strip()
    if not payload:
        return None
    if payload == "[DONE]":
        return payload
    return json.loads(payload)


def _clip(text: str, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _decode_bytes_best_effort(data: bytes) -> str:
    if not data:
        return ""

    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1251", "latin-1"):
        try:
            decoded = data.decode(encoding)
            if decoded.strip():
                return decoded
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml_names = sorted(
                name for name in zf.namelist() if name.startswith("word/") and name.endswith(".xml")
            )
            chunks: list[str] = []
            for name in xml_names:
                root = ElementTree.fromstring(zf.read(name))
                paragraphs: list[str] = []
                for paragraph in root.iterfind(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                    texts = [
                        node.text or ""
                        for node in paragraph.iterfind(
                            ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
                        )
                    ]
                    line = "".join(texts).strip()
                    if line:
                        paragraphs.append(line)
                if paragraphs:
                    chunks.append("\n".join(paragraphs))
    except (zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise UnsupportedDocumentError("Invalid DOCX file") from exc

    text = "\n\n".join(part for part in chunks if part).strip()
    if not text:
        raise UnsupportedDocumentError("DOCX has no readable text")
    return text


def _extract_pdf_text(data: bytes) -> str:
    raw = data.decode("latin-1", errors="ignore")
    matches = re.findall(r"\(([^()]*)\)", raw)
    cleaned = [_clean_html_text(item.replace(r"\n", " ").replace(r"\r", " ")) for item in matches]
    text = "\n".join(item for item in cleaned if item).strip()
    if not text:
        raise UnsupportedDocumentError("PDF text extraction is not supported for this file")
    return text


def extract_document_text(
    data: bytes,
    *,
    file_name: str | None,
    mime_type: str | None,
) -> str:
    if len(data) > MAX_DOC_UPLOAD_BYTES:
        raise UnsupportedDocumentError("Document is too large")

    ext = Path(file_name or "").suffix.lower()
    mime = (mime_type or "").lower()

    if ext == ".docx" or mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        text = _extract_docx_text(data)
    elif ext == ".pdf" or mime == "application/pdf":
        text = _extract_pdf_text(data)
    elif mime.startswith("text/") or ext in {
        ".txt",
        ".md",
        ".csv",
        ".json",
        ".yaml",
        ".yml",
        ".html",
        ".htm",
        ".xml",
        ".log",
        ".ini",
        ".cfg",
        ".toml",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".css",
        ".sql",
        ".java",
        ".go",
        ".rs",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".sh",
    }:
        text = _decode_bytes_best_effort(data)
    else:
        raise UnsupportedDocumentError("Unsupported document format")

    text = _clean_html_text(text)
    text = text.replace(" .", ".").replace(" ,", ",")
    text = _clip(text, MAX_DOC_STORE_CHARS)
    if not text.strip():
        raise UnsupportedDocumentError("Document has no readable text")
    return text


def _format_history_messages(messages: list[AgentMessage], *, quick_mode: bool) -> list[dict[str, str]]:
    if not messages:
        return []
    limit = QUICK_HISTORY_LIMIT if quick_mode else FULL_HISTORY_LIMIT
    result: list[dict[str, str]] = []
    for item in messages[-limit:]:
        role = "assistant" if str(item.role) == "assistant" else "user"
        content = _clip(str(item.content or ""), 1500 if quick_mode else 3000)
        if not content:
            continue
        result.append({"role": role, "content": content})
    return result


def _format_search_context(results: list[SearchResult]) -> str:
    if not results:
        return ""
    lines = ["Результаты веб-поиска:"]
    for idx, item in enumerate(results, start=1):
        lines.append(f"{idx}. {item.title}")
        lines.append(f"URL: {item.url}")
        if item.snippet:
            lines.append(f"Сниппет: {item.snippet}")
        if item.page_content:
            lines.append(f"Материал страницы: {item.page_content}")
    return "\n".join(lines).strip()


def _format_documents_context(
    documents: list[AgentDocument],
    *,
    quick_mode: bool,
) -> str:
    if not documents:
        return ""

    total_limit = QUICK_DOC_CHAR_LIMIT if quick_mode else FULL_DOC_CHAR_LIMIT
    used = 0
    parts: list[str] = []
    for idx, doc in enumerate(documents, start=1):
        remaining = total_limit - used
        if remaining <= 0:
            break
        title = doc.file_name or f"Документ {idx}"
        content = _clip(str(doc.extracted_text or ""), min(remaining, 4000 if quick_mode else 7000))
        if not content:
            continue
        parts.append(f"[{title}]\n{content}")
        used += len(content)
    if not parts:
        return ""
    return "Документы текущей сессии:\n" + "\n\n".join(parts)


def build_agent_messages(
    user_text: str,
    *,
    settings: AgentToggleState,
    history: list[AgentMessage],
    documents: list[AgentDocument],
    search_results: list[SearchResult],
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": BASE_SYSTEM_PROMPT}]
    prepared_user_text = build_user_question_prompt(user_text)
    detected_questions = split_user_questions(user_text)

    if settings.quick_mode_enabled:
        messages.append({"role": "system", "content": QUICK_MODE_PROMPT})
    elif settings.deep_analysis_enabled:
        messages.append({"role": "system", "content": DEEP_ANALYSIS_PROMPT})

    if settings.web_search_enabled:
        messages.append({"role": "system", "content": WEB_SEARCH_PROMPT})
    if len(detected_questions) > 1:
        messages.append({"role": "system", "content": MULTI_QUESTION_PROMPT})

    extra_context_parts: list[str] = []
    if settings.web_search_enabled:
        search_context = _format_search_context(search_results)
        if search_context:
            extra_context_parts.append(search_context)

    if settings.documents_enabled:
        docs_context = _format_documents_context(
            documents,
            quick_mode=settings.quick_mode_enabled,
        )
        if docs_context:
            extra_context_parts.append(docs_context)

    if extra_context_parts:
        messages.append(
            {
                "role": "system",
                "content": "Дополнительный контекст для ответа:\n\n" + "\n\n".join(extra_context_parts),
            }
        )

    if settings.memory_enabled:
        messages.extend(
            _format_history_messages(
                history,
                quick_mode=settings.quick_mode_enabled,
            )
        )

    messages.append({"role": "user", "content": prepared_user_text})
    return messages


def _build_openrouter_headers(cfg: AgentModelConfig) -> dict[str, str]:
    headers: dict[str, str] = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    if cfg.http_referer:
        headers["HTTP-Referer"] = cfg.http_referer
    if cfg.x_title:
        headers["X-Title"] = cfg.x_title
    return headers


def _build_openrouter_body(
    cfg: AgentModelConfig,
    user_text: str,
    *,
    settings: AgentToggleState,
    history: list[AgentMessage],
    documents: list[AgentDocument],
    search_results: list[SearchResult],
    stream: bool,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": cfg.model_name,
        "messages": build_agent_messages(
            user_text,
            settings=settings,
            history=history,
            documents=documents,
            search_results=search_results,
        ),
        "temperature": 0.2 if settings.quick_mode_enabled else 0.4,
        "max_completion_tokens": (
            QUICK_MAX_COMPLETION_TOKENS if settings.quick_mode_enabled else FULL_MAX_COMPLETION_TOKENS
        ),
    }
    if stream:
        body["stream"] = True
    return body


async def _post_openrouter_json_with_retries(
    cfg: AgentModelConfig,
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(1, OPENROUTER_MAX_ATTEMPTS + 1):
        try:
            async with external_httpx_client(timeout=cfg.timeout_s) as client:
                return await client.post(url, headers=headers, json=body)
        except _RETRYABLE_OPENROUTER_ERRORS as exc:
            last_exc = exc
            if attempt >= OPENROUTER_MAX_ATTEMPTS:
                break
            backoff = min(10.0, 1.5 * attempt)
            logger.warning(
                "wea_agent.openrouter request retry attempt=%s/%s error=%s retry_in=%.1fs",
                attempt,
                OPENROUTER_MAX_ATTEMPTS,
                _format_transport_error(exc),
                backoff,
            )
            await asyncio.sleep(backoff)
        except Exception as exc:
            raise WeaAgentError("OpenRouter request failed") from exc

    raise WeaAgentError(
        f"OpenRouter request failed after {OPENROUTER_MAX_ATTEMPTS} attempts: "
        f"{_format_transport_error(last_exc)}"
    ) from last_exc


async def _emit_stream_delta(
    on_delta: Callable[[str], Any] | None,
    delta: str,
) -> None:
    if on_delta is None or not delta:
        return
    result = on_delta(delta)
    if inspect.isawaitable(result):
        await result


async def _stream_openrouter_once(
    cfg: AgentModelConfig,
    *,
    messages: list[dict[str, str]],
    settings: AgentToggleState,
    on_delta: Callable[[str], Any] | None = None,
) -> tuple[str, str | None]:
    url = urljoin(f"{cfg.base_url}/", "chat/completions")
    headers = _build_openrouter_headers(cfg)
    body = {
        "model": cfg.model_name,
        "messages": messages,
        "temperature": 0.2 if settings.quick_mode_enabled else 0.4,
        "max_completion_tokens": (
            QUICK_MAX_COMPLETION_TOKENS if settings.quick_mode_enabled else FULL_MAX_COMPLETION_TOKENS
        ),
        "stream": True,
    }

    last_exc: Exception | None = None

    for attempt in range(1, OPENROUTER_MAX_ATTEMPTS + 1):
        parts: list[str] = []
        finish_reason: str | None = None
        event_lines: list[str] = []

        try:
            async with external_httpx_client(timeout=cfg.timeout_s) as client:
                async with client.stream("POST", url, headers=headers, json=body) as resp:
                    if resp.status_code >= 400:
                        raise WeaAgentError(f"OpenRouter error [{resp.status_code}]")

                    async for raw_line in resp.aiter_lines():
                        line = (raw_line or "").rstrip("\r")
                        if line:
                            event_lines.append(line)
                            continue

                        raw_event = "\n".join(event_lines)
                        event_lines.clear()
                        parsed_event = parse_openrouter_sse_event(raw_event)
                        if parsed_event is None:
                            continue
                        if parsed_event == "[DONE]":
                            break
                        if not isinstance(parsed_event, dict):
                            continue
                        if parsed_event.get("error"):
                            error = parsed_event["error"]
                            if isinstance(error, dict):
                                message = str(error.get("message") or "").strip()
                                raise WeaAgentError(message or "OpenRouter stream failed")
                            raise WeaAgentError("OpenRouter stream failed")

                        parsed_finish_reason = extract_openrouter_finish_reason(parsed_event)
                        if parsed_finish_reason:
                            finish_reason = parsed_finish_reason

                        delta = extract_openrouter_stream_delta(parsed_event)
                        if not delta:
                            continue
                        parts.append(delta)
                        await _emit_stream_delta(on_delta, delta)

                    if event_lines:
                        parsed_event = parse_openrouter_sse_event("\n".join(event_lines))
                        if isinstance(parsed_event, dict):
                            parsed_finish_reason = extract_openrouter_finish_reason(parsed_event)
                            if parsed_finish_reason:
                                finish_reason = parsed_finish_reason
                            delta = extract_openrouter_stream_delta(parsed_event)
                            if delta:
                                parts.append(delta)
                                await _emit_stream_delta(on_delta, delta)
            return "".join(parts), finish_reason
        except WeaAgentError:
            raise
        except _RETRYABLE_OPENROUTER_ERRORS as exc:
            last_exc = exc
            if parts:
                logger.warning(
                    "wea_agent.openrouter stream interrupted after partial output: %s",
                    _format_transport_error(exc),
                )
                return "".join(parts), "interrupted"
            if attempt >= OPENROUTER_MAX_ATTEMPTS:
                break
            backoff = min(10.0, 1.5 * attempt)
            logger.warning(
                "wea_agent.openrouter stream retry attempt=%s/%s error=%s retry_in=%.1fs",
                attempt,
                OPENROUTER_MAX_ATTEMPTS,
                _format_transport_error(exc),
                backoff,
            )
            await asyncio.sleep(backoff)
        except Exception as exc:
            raise WeaAgentError("OpenRouter request failed") from exc

    raise WeaAgentError(
        f"OpenRouter request failed after {OPENROUTER_MAX_ATTEMPTS} attempts: "
        f"{_format_transport_error(last_exc)}"
    ) from last_exc


async def generate_agent_reply_streaming(
    user_text: str,
    *,
    settings: AgentToggleState,
    history: list[AgentMessage],
    documents: list[AgentDocument],
    search_results: list[SearchResult],
    on_delta: Callable[[str], Awaitable[None] | None] | None = None,
) -> str:
    cfg = load_agent_model_config()
    messages = build_agent_messages(
        user_text,
        settings=settings,
        history=history,
        documents=documents,
        search_results=search_results,
    )

    full_reply = ""
    for attempt in range(MAX_AUTO_CONTINUATIONS + 1):
        part, finish_reason = await _stream_openrouter_once(
            cfg,
            messages=messages,
            settings=settings,
            on_delta=on_delta,
        )
        if part:
            full_reply += part

        if full_reply.strip() and finish_reason not in {"length", "interrupted"}:
            return full_reply.strip()
        if full_reply.strip() and attempt >= MAX_AUTO_CONTINUATIONS:
            return full_reply.strip()

        messages = [
            *messages,
            {"role": "assistant", "content": full_reply},
            {"role": "user", "content": CONTINUATION_PROMPT},
        ]

    if not full_reply.strip():
        raise WeaAgentError("OpenRouter returned empty stream")
    return full_reply.strip()


async def generate_agent_reply(
    user_text: str,
    *,
    settings: AgentToggleState,
    history: list[AgentMessage],
    documents: list[AgentDocument],
    search_results: list[SearchResult],
) -> str:
    cfg = load_agent_model_config()
    url = urljoin(f"{cfg.base_url}/", "chat/completions")
    headers = _build_openrouter_headers(cfg)
    body = _build_openrouter_body(
        cfg,
        user_text,
        settings=settings,
        history=history,
        documents=documents,
        search_results=search_results,
        stream=False,
    )

    resp = await _post_openrouter_json_with_retries(
        cfg,
        url=url,
        headers=headers,
        body=body,
    )

    if resp.status_code >= 400:
        raise WeaAgentError(f"OpenRouter error [{resp.status_code}]")

    reply = extract_openrouter_chat_content(resp.json())
    if not reply.strip():
        raise WeaAgentError("OpenRouter returned empty answer")
    return reply.strip()
