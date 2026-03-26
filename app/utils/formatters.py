from __future__ import annotations

from collections import Counter
from collections.abc import Sequence


def materialize_song_sections(section_types: Sequence[str]) -> list[dict[str, str]]:
    counts: Counter[str] = Counter()
    out: list[dict[str, str]] = []
    labels = {
        "verse": "Куплет",
        "chorus": "Припев",
        "bridge": "Бридж",
        "intro": "Интро",
        "outro": "Аутро",
    }

    for section_type in section_types:
        counts[section_type] += 1
        idx = counts[section_type]
        marker = labels.get(section_type, section_type.title())
        label = f"{marker} {idx}" if counts[section_type] > 1 else marker
        out.append(
            {
                "key": f"{section_type}_{idx}",
                "type": section_type,
                "marker": marker,
                "label": label,
            }
        )
    return out


def should_skip_lyrics(selected_tags: Sequence[str]) -> bool:
    normalized = {str(tag).strip().lower() for tag in selected_tags}
    return "instrumental" in normalized


def compile_song_lyrics(
    *,
    sections: Sequence[dict[str, str]],
    section_texts: dict[str, str],
    instrumental: bool,
) -> str:
    if instrumental:
        return "[instrumental]"

    chunks: list[str] = []
    for section in sections:
        text = (section_texts.get(section["key"]) or "").strip()
        if not text:
            continue
        api_marker = section.get("api_marker") or section["marker"]
        chunks.append(f"[{api_marker}]\n{text}")
    return "\n\n".join(chunks).strip()


def format_song_summary(
    *,
    tags_display: Sequence[str],
    sections: Sequence[dict[str, str]],
    lyrics: str,
    duration: int,
    seed: int,
    instrumental: bool,
) -> str:
    del seed
    tags_line = ", ".join(tags_display) if tags_display else "—"
    structure_line = " → ".join(section["label"] for section in sections) if sections else "—"
    vocals_mode = "Без слов" if instrumental else "С вокалом"
    lyrics_block = "🎼 <b>Текст:</b>\n[instrumental]" if instrumental else f"🎤 <b>Текст:</b>\n{lyrics or '—'}"

    return (
        "🎵 <b>Параметры вашей песни</b>\n\n"
        f"🏷 <b>Теги:</b>\n{tags_line}\n\n"
        f"🧱 <b>Структура:</b>\n{structure_line}\n\n"
        f"{lyrics_block}\n\n"
        f"⏱ <b>Длительность:</b>\n{duration} сек\n\n"
        f"🎙 <b>Режим:</b>\n{vocals_mode}\n\n"
        "Все верно? 👇"
    )
