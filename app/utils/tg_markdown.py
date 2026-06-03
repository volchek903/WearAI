from __future__ import annotations

import html
import re

from app.utils.content_media import TG_MAX_MESSAGE_CHARS

_CODE_FENCE_RE = re.compile(r"^```(?P<lang>[a-zA-Z0-9_+-]*)\s*$")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD_STAR_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_BOLD_UNDERSCORE_RE = re.compile(r"__(.+?)__", re.DOTALL)
_STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", re.DOTALL)
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)", re.DOTALL)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_HR_RE = re.compile(r"^\s*([*_ -])(?:\s*\1){2,}\s*$")

_PLACEHOLDER_PREFIX = "\x00TGMD"
_PLACEHOLDER_SUFFIX = "TGMD\x00"


def render_markdown_to_html_chunks(
    text: str,
    *,
    limit: int = TG_MAX_MESSAGE_CHARS,
) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return [" "]

    chunks: list[str] = []
    block_buffer: list[str] = []
    in_code_block = False
    code_lines: list[str] = []

    def flush_text_block() -> None:
        nonlocal block_buffer
        if not block_buffer:
            return
        chunks.extend(_render_text_block_to_chunks("\n".join(block_buffer), limit=limit))
        block_buffer = []

    for line in raw.splitlines():
        if in_code_block:
            if _CODE_FENCE_RE.match(line.strip()):
                chunks.extend(_render_code_block_to_chunks("\n".join(code_lines), limit=limit))
                code_lines = []
                in_code_block = False
            else:
                code_lines.append(line)
            continue

        if _CODE_FENCE_RE.match(line.strip()):
            flush_text_block()
            in_code_block = True
            code_lines = []
            continue

        block_buffer.append(line)

    flush_text_block()
    if in_code_block:
        chunks.extend(_render_code_block_to_chunks("\n".join(code_lines), limit=limit))

    return chunks or [" "]


def _render_text_block_to_chunks(text: str, *, limit: int) -> list[str]:
    lines = text.splitlines()
    chunks: list[str] = []
    current = ""

    for raw_line in lines:
        rendered_line = _render_text_line(raw_line)
        candidate = rendered_line if not current else f"{current}\n{rendered_line}"
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(rendered_line) <= limit:
            current = rendered_line
            continue

        chunks.extend(_split_long_rendered_line(rendered_line, limit=limit))

    if current:
        chunks.append(current)
    return chunks or [" "]


def _render_code_block_to_chunks(code_text: str, *, limit: int) -> list[str]:
    prefix = "<pre><code>"
    suffix = "</code></pre>"
    inner_limit = max(64, limit - len(prefix) - len(suffix))
    result: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for line in (code_text or "").splitlines():
        escaped_line = html.escape(line)
        pieces = [escaped_line[i : i + inner_limit] for i in range(0, len(escaped_line), inner_limit)] or [""]
        for piece in pieces:
            extra_len = len(piece) + (1 if current_lines else 0)
            if current_lines and (current_len + extra_len) > inner_limit:
                result.append(f"{prefix}{chr(10).join(current_lines)}{suffix}")
                current_lines = []
                current_len = 0
            current_lines.append(piece)
            current_len += len(piece) + (1 if current_lines[:-1] else 0)

    if current_lines or not result:
        result.append(f"{prefix}{chr(10).join(current_lines)}{suffix}")
    return result


def _render_text_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if _HR_RE.match(line):
        return "────────"

    heading_match = _HEADING_RE.match(line)
    if heading_match is not None:
        content = _render_inline_markdown(heading_match.group(1).strip())
        return f"<b>{content}</b>" if content else ""

    return _render_inline_markdown(line)


def _render_inline_markdown(text: str) -> str:
    placeholders: list[str] = []

    def store(value: str) -> str:
        token = f"{_PLACEHOLDER_PREFIX}{len(placeholders)}{_PLACEHOLDER_SUFFIX}"
        placeholders.append(value)
        return token

    def restore(value: str) -> str:
        for idx, item in enumerate(placeholders):
            value = value.replace(f"{_PLACEHOLDER_PREFIX}{idx}{_PLACEHOLDER_SUFFIX}", item)
        return value

    prepared = text or ""
    prepared = _LINK_RE.sub(
        lambda match: store(
            f'<a href="{html.escape(match.group(2), quote=True)}">{html.escape(match.group(1))}</a>'
        ),
        prepared,
    )
    prepared = _INLINE_CODE_RE.sub(
        lambda match: store(f"<code>{html.escape(match.group(1))}</code>"),
        prepared,
    )

    rendered = html.escape(prepared)
    rendered = _BOLD_STAR_RE.sub(r"<b>\1</b>", rendered)
    rendered = _BOLD_UNDERSCORE_RE.sub(r"<b>\1</b>", rendered)
    rendered = _STRIKE_RE.sub(r"<s>\1</s>", rendered)
    rendered = _ITALIC_STAR_RE.sub(r"<i>\1</i>", rendered)
    rendered = _ITALIC_UNDERSCORE_RE.sub(r"<i>\1</i>", rendered)
    return restore(rendered)


def _split_long_rendered_line(line: str, *, limit: int) -> list[str]:
    if len(line) <= limit:
        return [line]

    chunks: list[str] = []
    current = line
    while len(current) > limit:
        split_at = current.rfind(" ", 0, limit)
        if split_at < limit // 3:
            split_at = limit
        chunks.append(current[:split_at].rstrip())
        current = current[split_at:].lstrip()
    if current:
        chunks.append(current)
    return chunks
