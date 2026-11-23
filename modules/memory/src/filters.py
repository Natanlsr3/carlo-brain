"""Shared text filters: secret masking, user-defined exclusions, injection scan."""
from __future__ import annotations

import re
from typing import Iterable

MASK = "[masked]"
SECRETS = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|ghp_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}|AIza[A-Za-z0-9_\-]{8,}"
    r"|xox[abprs]-[A-Za-z0-9\-]{6,}|(?i:bearer)\s+[A-Za-z0-9._\-]{8,}|AKIA[0-9A-Z]{16}"
    r"|(?<![A-Za-z0-9+_=])(?=[A-Za-z0-9+_=]*\d)(?=[A-Za-z0-9+_=]*[a-z])(?=[A-Za-z0-9+_=]*[A-Z])[A-Za-z0-9+_=]{40,})"
)
INJECTION = re.compile(
    r"\b(ignore\b|disregard\b|forget\b.{0,20}(instructions|rules)|you must|system\s*prompt|\bsystem\b"
    r"|\bassistant:|jailbreak|override)|<\s*/?\s*(system|instructions?)\b|https?://|curl\s|\|\s*(ba)?sh\b",
    re.I,
)


def mask(text: str) -> str:
    """Replace key-like strings (API keys, tokens, long base64 blobs) with [masked]."""
    return SECRETS.sub(MASK, text)


def is_excluded(text: str, patterns: Iterable[str]) -> bool:
    """True when the text matches a user-defined exclusion regex (private channels, topics to keep out of memory)."""
    for pattern in patterns:
        try:
            if re.search(pattern, text, re.I):
                return True
        except re.error:
            continue
    return False


def suspicious(text: str) -> bool:
    """True when the text looks like an instruction or contains a link (possible prompt injection)."""
    return bool(INJECTION.search(text))


def clip(text: str, limit: int) -> str:
    """One line, cut at `limit` characters with a visible mark."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit].rstrip() + " [...]"
