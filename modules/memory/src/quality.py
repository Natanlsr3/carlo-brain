#!/usr/bin/env python3
"""Mechanical quality score (0-10) for a Claude Code session. The user rates nothing.

Signals from the user's messages: corrections ("no", "that's not what I asked", "I told you",
"redo"), repeated requests, interruptions, hook blocks (negative), "go" / "ok" (positive).
Automatic sessions (no user message) get a null score.

Usage: quality.py <transcript.jsonl>   score one session and append to state/quality.jsonl
       quality.py summary [N]          average of the last N scores (default 20)
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _lib in (os.environ.get("CARLO_LIB"), str(Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain") / "lib")):
    if _lib:
        sys.path.insert(0, _lib)
import carlo_config as cfg  # noqa: E402

CORRECTIONS = [re.compile(p, re.I) for p in (
    r"^\s*no\b", r"\bnot what i (asked|meant|wanted|said)\b", r"\bthat'?s not (it|right|what|correct)\b",
    r"\bi (already |just )?(told|said)\b", r"\bredo\b", r"\bthat'?s wrong\b", r"(^|[.!?]\s*)stop\b",
    r"\byou (didn'?t|did not) (understand|read|listen|get)\b", r"\byou forgot\b", r"\bi didn'?t ask\b",
    r"\bwhy did you (change|modify|delete|remove|touch)\b", r"\bonce again\b", r"\bnope\b",
)]
POSITIVE = re.compile(r"^\s*(go|ok|okay|yes|yep|yeah|perfect|great|nice|thanks|approved|looks good|exactly|do it|send it|sounds good)\b[\s.!,]*(go|ok)?[\s.!]*$", re.I)
INJECTED = ("<system-reminder", "<command-", "<local-command", "Caveat:", "This session is being continued", "<task-notification", "Stop hook feedback")
INTERRUPT = "[Request interrupted"
HOOK_BLOCK = re.compile(r"hook error|blocked by .{0,40}hook", re.I)


def human_text(item: dict) -> Optional[str]:
    """Text of a real user message, or None (tool result, injected context, meta, sub-agent)."""
    if item.get("type") != "user" or item.get("isMeta") or item.get("isSidechain"):
        return None
    content = (item.get("message") or {}).get("content")
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str) or not content.strip() or content.lstrip().startswith(INJECTED):
        return None
    return content.strip()


def is_hook_block(item: dict) -> bool:
    content = (item.get("message") or {}).get("content")
    if item.get("type") != "user" or not isinstance(content, list):
        return False
    return any(isinstance(b, dict) and b.get("type") == "tool_result" and isinstance(b.get("content"), str)
               and HOOK_BLOCK.search(b["content"]) for b in content)


def words(text: str) -> set:
    return set(re.findall(r"\w{4,}", text.lower()))


def count_repeats(messages: list) -> int:
    """Messages that repeat a close request (Jaccard >= 0.7) among the 6 previous messages."""
    total = 0
    for index, message in enumerate(messages):
        a = words(message)
        if len(a) < 4:
            continue
        for previous in messages[max(0, index - 6):index]:
            b = words(previous)
            if len(b) >= 4 and len(a & b) / len(a | b) >= 0.7:
                total += 1
                break
    return total


def score(counts: dict, n_messages: int) -> tuple:
    """Score 0-10 and the reason line, from rates per user message (bonus capped at 1)."""
    rate = (counts["corrections"] + counts["repeats"] + 0.5 * counts["interruptions"]
            + 0.25 * counts["hook_blocks"]) / max(n_messages, 1)
    value = max(0.0, min(10.0, 10 - 12 * rate + min(1.0, 0.25 * counts["positives"])))
    reason = (f"{counts['corrections']} correction(s), {counts['repeats']} repeat(s), {counts['interruptions']} interruption(s), "
              f"{counts['hook_blocks']} hook block(s), {counts['positives']} go/ok over {n_messages} user message(s)")
    return round(value, 1), reason


def analyse(path: Path) -> dict:
    """Read a transcript and return the record to store."""
    counts = {"corrections": 0, "repeats": 0, "interruptions": 0, "hook_blocks": 0, "positives": 0}
    messages: list = []
    first = entry = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        first = first or item.get("timestamp")
        entry = entry or item.get("entrypoint")
        counts["hook_blocks"] += int(is_hook_block(item))
        text = human_text(item)
        if text is None:
            continue
        if text.startswith(INTERRUPT):
            counts["interruptions"] += 1
        elif POSITIVE.match(text) and len(text) <= 30:
            counts["positives"] += 1
            messages.append(text)
        else:
            messages.append(text)
            counts["corrections"] += int(len(text) <= 800 and any(p.search(text) for p in CORRECTIONS))
    counts["repeats"] = count_repeats([m for m in messages if not POSITIVE.match(m)])
    automatic = not messages or entry == "sdk-cli"
    value, reason = (None, "automatic session, no user message") if automatic else score(counts, len(messages))
    return {"session": path.stem, "date": (first or datetime.now(timezone.utc).isoformat())[:10], "score": value,
            "reason": reason, "counts": {**counts, "messages": len(messages)}}


def append(record: dict, file: Path) -> bool:
    """Append unless the last line for the same session is identical. True when written."""
    file.parent.mkdir(parents=True, exist_ok=True)
    new = json.dumps(record, ensure_ascii=False, sort_keys=True)
    if file.exists():
        for old in reversed(file.read_text(encoding="utf-8").splitlines()):
            try:
                data = json.loads(old)
            except ValueError:
                continue
            if data.get("session") == record["session"]:
                if json.dumps(data, ensure_ascii=False, sort_keys=True) == new:
                    return False
                break
    with file.open("a", encoding="utf-8") as handle:
        handle.write(new + "\n")
    return True


def record(transcript_path: str) -> dict:
    """Score a session and store it in state/quality.jsonl."""
    data = analyse(Path(transcript_path))
    append(data, cfg.state_dir() / "quality.jsonl")
    return data


def summary(limit: int = 20) -> str:
    file = cfg.state_dir() / "quality.jsonl"
    scores = []
    for line in file.read_text(encoding="utf-8").splitlines()[-limit * 3:] if file.exists() else []:
        try:
            value = json.loads(line).get("score")
        except ValueError:
            continue
        if isinstance(value, (int, float)):
            scores.append(float(value))
    scores = scores[-limit:]
    return f"average {sum(scores) / len(scores):.1f}/10 over {len(scores)} session(s)" if scores else "no scored session yet"


def main(argv: list) -> int:
    if argv[:1] == ["summary"]:
        print(summary(int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 20))
        return 0
    if len(argv) != 1 or not Path(argv[0]).is_file():
        print("usage: quality.py <transcript.jsonl> | summary [N]", file=sys.stderr)
        return 2
    print(json.dumps(record(argv[0]), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
