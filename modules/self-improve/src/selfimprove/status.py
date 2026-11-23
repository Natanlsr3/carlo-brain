"""Make failures and waiting items visible at session start (boot.d/self-improve.md), never silent."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from . import runner
from .settings import Settings

UNREAD = re.compile(r"^status:\s*unread\s*$", re.IGNORECASE | re.MULTILINE)


def unread_reports(cfg: Settings) -> List[Path]:
    """Reports in improvement/reports whose front matter says status: unread."""
    folder = cfg.improvement / "reports"
    found = []
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        try:
            head = path.read_text(encoding="utf-8")[:400]
        except OSError:
            continue
        if head.startswith("---") and UNREAD.search(head):
            found.append(path)
    return found


def waiting_reviews(cfg: Settings) -> List[Path]:
    return sorted(cfg.to_review.glob("*.md")) if cfg.to_review.is_dir() else []


def failing_tasks(cfg: Settings, tasks: List[Dict[str, Any]]) -> List[str]:
    """One line per task whose last run failed (until a later run succeeds)."""
    lines = []
    for task in tasks:
        state = runner.read_state(cfg, task["name"])
        if state.get("status") == "failed":
            lines.append(f"task {task['name']} failed ({state.get('attempts', '?')} attempt(s)): {state.get('error', 'unknown error')}")
    return lines


def lines_for_boot(cfg: Settings, tasks: List[Dict[str, Any]], caught_up: List[str]) -> List[str]:
    """What the user should see at the start of a session. Empty list = say nothing."""
    out = [f"Self-improve: {line}" for line in failing_tasks(cfg, tasks)]
    out += [f"Self-improve: {line}" for line in caught_up]
    reviews = waiting_reviews(cfg)
    if reviews:
        out.append(f"Self-improve: {len(reviews)} proposal(s) wait for your review in {cfg.to_review}")
    reports = unread_reports(cfg)
    if reports:
        out.append(f"Self-improve: {len(reports)} unread report(s) in {cfg.improvement / 'reports'}")
    return out


def write_boot_file(cfg: Settings, lines: List[str]) -> None:
    """Write (or remove when empty) the drop-in read by the core boot injector."""
    target = cfg.brain_dir / "state" / "boot.d" / "self-improve.md"
    if not lines:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines[:8]) + "\n", encoding="utf-8")
