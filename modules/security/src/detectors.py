"""Detectors for sensitive data in text. They return findings (type, line, column), NEVER the value."""
from __future__ import annotations

import re
from typing import NamedTuple, Optional


class Finding(NamedTuple):
    """A sensitive item: type and position (1-based line and column), no value."""
    type: str
    line: int
    column: int
    start: int
    end: int


KEYS = (
    ("API key (sk-)", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")),
    ("GitHub token (gh*_)", re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}")),
    ("GitHub token (github_pat_)", re.compile(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{20,}")),
    ("Google key (AIza)", re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])")),
    ("Slack token (xox)", re.compile(r"(?<![A-Za-z0-9])xox[bpa]-[A-Za-z0-9-]{10,}")),
    ("AWS access key id", re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])")),
    ("Telegram bot token", re.compile(r"(?<![0-9A-Za-z])\d{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])")),
    ("Bearer token", re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}")),
    ("private key (PEM)", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("password", re.compile(r"(?i)(?:password|passwd|pwd)\s*[:=]\s*\S{6,}")),
)
IBAN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?(?![A-Za-z0-9])")
CARD_RE = re.compile(r"(?<![\d-])[2-6]\d{3}(?:[ -]?\d{4}){2}(?:[ -]?\d{1,7})(?![\d-])")


def iban_valid(raw: str) -> bool:
    """IBAN checksum (length 15-34, mod 97 equals 1)."""
    compact = raw.replace(" ", "")
    if not 15 <= len(compact) <= 34:
        return False
    rotated = compact[4:] + compact[:4]
    return int("".join(str(int(c, 36)) for c in rotated)) % 97 == 1


def luhn_valid(raw: str) -> bool:
    """Payment card number checksum (13 to 19 digits)."""
    digits = [int(c) for c in re.sub(r"\D", "", raw)]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for index, number in enumerate(reversed(digits)):
        if index % 2:
            number = number * 2 - 9 if number > 4 else number * 2
        total += number
    return total % 10 == 0


def _position(text: str, start: int) -> tuple:
    return text.count("\n", 0, start) + 1, start - (text.rfind("\n", 0, start) + 1) + 1


def scan(text: str, extra: Optional[dict] = None) -> list:
    """Findings sorted by position; an area is reported once. `extra` maps label to regex (user patterns)."""
    found: list = []

    def add(label: str, match: "re.Match[str]") -> None:
        item = Finding(label, *_position(text, match.start()), match.start(), match.end())
        if not any(item.start < o.end and o.start < item.end for o in found):
            found.append(item)

    for label, pattern in KEYS:
        for match in pattern.finditer(text):
            add(label, match)
    for match in IBAN_RE.finditer(text):
        if iban_valid(match.group(0)):
            add("IBAN", match)
    for match in CARD_RE.finditer(text):
        if luhn_valid(match.group(0)):
            add("payment card number", match)
    for label, regex in (extra or {}).items():
        try:
            for match in re.finditer(regex, text):
                add(str(label), match)
        except re.error:
            continue
    return sorted(found, key=lambda f: f.start)
