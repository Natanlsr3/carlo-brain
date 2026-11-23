"""Todo deadlines from a local JSON export: [{"title": str, "due": "YYYY-MM-DD", "done": bool}].

The Apple Reminders connector (modules/connectors/apple) can write this file; any other tool can too.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List

from ..model import Signal, SourceError, SourceResult, explain_outage
from ..text import clip_words


def load(path: Path) -> List[Dict[str, Any]]:
    """Export file -> list of dict items. Raises SourceError if absent or not a list."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as err:
        raise SourceError(f"todo export not found: {path}") from err
    except (OSError, ValueError) as err:
        raise SourceError(f"todo export unreadable: {err}") from err
    if not isinstance(data, list):
        raise SourceError("todo export must be a JSON list")
    return [item for item in data if isinstance(item, dict)]


def signals(items: List[Dict[str, Any]], today: date) -> List[Signal]:
    """Overdue, due today, due tomorrow. Done or undated items are skipped."""
    out = []
    for item in items:
        try:
            due = date.fromisoformat(str(item.get("due", ""))[:10])
        except ValueError:
            continue
        title = str(item.get("title") or "").strip()
        if item.get("done") or not title:
            continue
        gap = (due - today).days
        label = {0: "today", 1: "tomorrow"}.get(gap, "overdue" if gap < 0 else "")
        if not label:
            continue
        bonus = {"overdue": 8, "today": 5, "tomorrow": 0}[label]
        short_title = clip_words(title, 12)
        out.append(
            Signal("deadline", f"Due {label}: {short_title}", "todo", bonus=bonus,
                   question=f"'{short_title}' is due {label}: do it now? (yes / later)")
        )
    return out


def collect(cfg: Dict[str, Any], now: datetime) -> SourceResult:
    """Todo source."""
    own = cfg["sources"]["todo"]
    result = SourceResult()
    if not own["file"]:
        result.outages.append("todo: no export file configured (sources.todo.file)")
        return result
    try:
        result.signals = signals(load(Path(own["file"]).expanduser()), now.date())
    except SourceError as err:
        result.outages.append(explain_outage("todo", err))
    return result
