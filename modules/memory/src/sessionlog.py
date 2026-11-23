"""Automatic SESSION_LOG entry, written only when the session did not write one itself."""
from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import filters
import transcript

MARKER = "<!-- NEW ENTRIES HERE"
TITLE_RE = re.compile(r"^#{2,3} (\d{4})-(\d{2})-(\d{2}) ~(\d{1,2})[h:](\d{2})?", re.M)
ENTRY_RE = re.compile(r"^#{2,3} \d{4}-\d{2}-\d{2}", re.M)
TOLERANCE = timedelta(minutes=20)


def dated_entries(text: str) -> list:
    """Times of entries titled `### YYYY-MM-DD ~HH:MM` (entries without a time do not count)."""
    return [datetime(int(y), int(mo), int(d), int(h), int(mi or 0)) for y, mo, d, h, mi in TITLE_RE.findall(text)]


def already_logged(text: str, start: datetime, end: datetime) -> bool:
    """True when a dated entry falls between session start (minus tolerance) and session end (plus tolerance)."""
    low, high = start.replace(tzinfo=None) - TOLERANCE, end.replace(tzinfo=None) + TOLERANCE
    return any(low <= e <= high for e in dated_entries(text))


def marker_end(text: str) -> Optional[int]:
    """Index just after the marker line, ignoring fenced code blocks; None when absent."""
    position, fenced = 0, False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith(MARKER):
            return position + len(line)
        position += len(line)
    return None


def entries(text: str) -> list:
    """Split a log into entries (newest first as written), trailing rules removed."""
    starts = [m.start() for m in ENTRY_RE.finditer(text)]
    chunks = [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]
    return [re.sub(r"\n-{3,}\s*$", "", c.strip()) for c in chunks]


def build(summary: transcript.Summary, surface: str = "Claude Code") -> str:
    """Entry text: a title and three lines. No em dashes."""
    start = summary.start or datetime.now()
    topics = " | ".join(filters.clip(m, 140) for m in summary.messages[:5]) or "(no message)"
    files = ", ".join(Path(f).name for f in summary.files[:15]) or "none"
    lines = [f"### {start:%Y-%m-%d} ~{start:%H:%M} ({surface}) [auto] (auto, to complete)",
             "- Entry generated mechanically at session end (no manual entry found).",
             f"- Topics: {topics}", f"- Files changed: {files}"]
    return "\n".join(lines).replace("\u2014", "-").replace("\u2013", "-") + "\n"


def add(transcript_path: str, log: Path, exclude: tuple = ()) -> bool:
    """Add the automatic entry when needed. Returns True if one was written."""
    summary = transcript.read(transcript_path, exclude)
    if not (summary.start and summary.end and summary.messages):
        return False
    try:
        text = log.read_text(encoding="utf-8")
    except OSError:
        return False
    position = marker_end(text)
    if position is None or already_logged(text, summary.start, summary.end):
        return False
    new = text[:position] + "\n" + build(summary) + text[position:]
    fd, tmp = tempfile.mkstemp(dir=str(log.parent), prefix=".sl_")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(new)
    os.replace(tmp, log)
    return True
