"""Mechanical reading of a Claude Code transcript (JSONL): human messages, written files, commands."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import filters

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
GIT_RE = re.compile(r"\bgit\s+(commit|push|merge|rebase|tag|checkout\s+-b|switch\s+-c|pull)\b")
DEPLOY_RE = re.compile(r"\b(vercel\s+(deploy|--prod)|fly(ctl)?\s+deploy|gh\s+pr\s+(merge|create)|npm\s+publish|docker\s+push)\b")
DECISION_RE = re.compile(r"^\s*(go|ok|okay|yes|approved?|do it|send it|looks good|perfect)\b[\s.!,]*", re.I)
NOISE_RE = re.compile(r"^\s*<(system-reminder|command-|local-command|task-notification)", re.I)


@dataclass(frozen=True)
class Summary:
    """What a transcript contains. Immutable."""
    start: Optional[datetime]
    end: Optional[datetime]
    messages: tuple = ()
    files: tuple = ()
    commands: tuple = ()
    decisions: tuple = ()  # (previous assistant text, user message)


def _timestamp(value: object) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def _texts(message: dict) -> str:
    content = message.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _tool_uses(message: dict) -> Iterable[dict]:
    content = message.get("message", {}).get("content")
    for part in content if isinstance(content, list) else []:
        if isinstance(part, dict) and part.get("type") == "tool_use":
            yield part


def read(path: object, exclude: Iterable[str] = ()) -> Summary:
    """Parse the JSONL. Unreadable lines are skipped. Secrets are masked, excluded text is dropped."""
    exclude = tuple(exclude)
    messages, files, commands, decisions = [], {}, [], []
    last_assistant = ""
    start = end = None
    try:
        lines = Path(str(path)).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if not isinstance(item, dict):
            continue
        stamp = _timestamp(item.get("timestamp"))
        if stamp:
            start, end = start or stamp, stamp
        if item.get("isSidechain"):
            continue
        if item.get("type") == "user":
            text = _texts(item).strip()
            if not text or NOISE_RE.match(text) or filters.is_excluded(text, exclude):
                continue
            text = filters.mask(text)
            messages.append(text)
            if DECISION_RE.match(text) and len(text) < 120:
                context = "" if filters.is_excluded(last_assistant, exclude) else filters.mask(last_assistant)
                decisions.append((filters.clip(context, 300), filters.clip(text, 120)))
        elif item.get("type") == "assistant":
            last_assistant = _texts(item) or last_assistant
            for use in _tool_uses(item):
                data = use.get("input") or {}
                if use.get("name") in WRITE_TOOLS and data.get("file_path"):
                    files[str(data["file_path"])] = None
                elif use.get("name") == "Bash":
                    command = str(data.get("command", ""))
                    if (GIT_RE.search(command) or DEPLOY_RE.search(command)) and not filters.is_excluded(command, exclude):
                        commands.append(filters.clip(filters.mask(command), 200))
    return Summary(start, end, tuple(messages), tuple(files), tuple(commands), tuple(decisions))
