"""Small text helpers shared by the news collector and the PDF renderer."""

from __future__ import annotations

import html
import re

ARABIC_CHAR_RE = re.compile(r"[؀-ۿ]")


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def has_arabic(text: str) -> bool:
    return bool(ARABIC_CHAR_RE.search(text))


def complete_sentence_chunks(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    return [match.group(0).strip() for match in re.finditer(r"[^.!?؟]+[.!?؟]+", text) if match.group(0).strip()]


def sentence_safe_excerpt(
    text: str,
    max_chars: int,
    max_sentences: int = 2,
    allow_short_unsentenced: bool = False,
) -> str:
    text = clean_text(text)
    if not text:
        return ""
    if len(text) <= max_chars and (text[-1] in ".!?؟" or allow_short_unsentenced):
        return text

    selected: list[str] = []
    for sentence in complete_sentence_chunks(text):
        candidate = " ".join([*selected, sentence]).strip()
        if selected and len(candidate) > max_chars:
            break
        if not selected and len(sentence) > max_chars:
            break
        selected.append(sentence)
        if len(selected) >= max_sentences:
            break
    return " ".join(selected).strip()


def word_safe_excerpt(text: str, max_chars: int) -> str:
    text = clean_text(text)
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rsplit(" ", 1)[0].strip()
    return f"{clipped}..." if clipped else f"{text[:max_chars].strip()}..."
