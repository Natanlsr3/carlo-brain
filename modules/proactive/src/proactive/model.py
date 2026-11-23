"""Data model: a Signal is one thing that may need attention; sources return SourceResult."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class Signal:
    """One fact for the briefing.

    kind: key of scoring.kinds in the config (reply, deadline, schedule, followup, ...).
    question: closed question to ask when this signal is ranked first ("" = information only).
    bonus: added to the kind weight (urgency, importance of the person).
    """

    kind: str
    title: str
    source: str
    question: str = ""
    bonus: int = 0
    detail: Tuple[str, ...] = ()


@dataclass
class SourceResult:
    """What a source returns: signals plus human readable outage lines."""

    signals: List[Signal] = field(default_factory=list)
    outages: List[str] = field(default_factory=list)
    extra: Dict[str, str] = field(default_factory=dict)


class SourceError(Exception):
    """A source cannot be read (missing file, denied access). Reported as an outage, never silent."""


def explain_outage(source: str, err: Exception) -> str:
    """One readable outage line. Permission errors get the Full Disk Access hint."""
    text = str(err) or err.__class__.__name__
    if isinstance(err, PermissionError) or "authorization denied" in text or "not authorized" in text:
        text += " (macOS: give the app that runs this Full Disk Access; background jobs need it too)"
    return f"{source}: cannot read ({text})"
