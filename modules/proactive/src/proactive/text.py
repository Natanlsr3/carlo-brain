"""Small text helpers shared by the sources and the briefing."""
from __future__ import annotations

import re

_REPLY_PREFIX = re.compile(r"^(?:(?:re|fw|fwd|tr)\s*:\s*)+", re.IGNORECASE)


def short(text: str, limit: int = 160) -> str:
    """Collapse whitespace and cut to `limit` characters."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "..."


def clip_words(text: str, limit: int) -> str:
    """Cut to `limit` words."""
    parts = re.sub(r"\s+", " ", text or "").strip().split(" ")
    return " ".join(parts) if len(parts) <= limit else " ".join(parts[:limit]).rstrip(",;:") + "..."


def count_words(text: str) -> int:
    """Number of whitespace separated words."""
    return len(re.findall(r"\S+", text))


def subject_key(subject: str) -> str:
    """Normalised subject (no re:/fwd:, lowercase, punctuation squashed) for de-duplication."""
    bare = _REPLY_PREFIX.sub("", (subject or "").strip().lower())
    return re.sub(r"\W+", " ", bare).strip()


def strip_dashes(text: str) -> str:
    """Replace typographic dashes with plain hyphens (keeps spoken and pasted text clean)."""
    return text.replace("\u2014", "-").replace("\u2013", "-")
