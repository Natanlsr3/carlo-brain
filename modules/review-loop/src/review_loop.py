#!/usr/bin/env python3
"""Review loop, no LLM (zero tokens except the one reminder it injects).

  start  (SessionStart)  remember the code diff that already exists, so only this session's changes count.
  stop   (Stop)          the diff changed since the start, is big enough, and was not asked about yet:
                         block the stop ONCE for that diff and ask Claude to run the `reviewer` agent on it.

It cannot loop: `stop_hook_active` is honoured, each diff hash is asked about once, and at most
`review_loop.max_per_session` (default 2) reminders are sent per session. State: state/review-loop/<session>.json.

Config (`carlo config set <key> <value>`): review_loop.enabled (default true; false turns it off),
review_loop.max_per_session (default 2), review_loop.min_lines (default 5 changed lines of code).
Skipped when CARLO_HEADLESS=1 (background jobs) and outside a git repository. Never raises.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _lib in (os.environ.get("CARLO_LIB"), str(Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain") / "lib")):
    if _lib:
        sys.path.insert(0, _lib)
import carlo_config as cfg  # noqa: E402

CODE = re.compile(r"\.(py|ts|tsx|js|jsx|mjs|go|rs|swift|rb|java|kt|c|cpp|cs|php|sh)$")
MAX_UNTRACKED_BYTES = 200_000


def git(args: List[str], cwd: str, run: Callable = subprocess.run) -> str:
    """Output of a git command, or "" on any failure (not a repo, git missing, timeout)."""
    try:
        res = run(["git", "-C", cwd] + args, capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return res.stdout if res.returncode == 0 else ""


def code_diff(cwd: str, run: Callable = subprocess.run) -> Tuple[str, Dict[str, int]]:
    """(hash, {file: changed lines}) for code files modified or created, against HEAD."""
    numstat = git(["diff", "HEAD", "--numstat"], cwd, run) or git(["diff", "--numstat"], cwd, run)
    files: Dict[str, int] = {}
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and CODE.search(parts[2]):
            files[parts[2]] = (int(parts[0]) if parts[0].isdigit() else 1) + (int(parts[1]) if parts[1].isdigit() else 0)
    digest = hashlib.sha256(git(["diff", "HEAD"], cwd, run).encode("utf-8", "replace") if files else b"")
    for name in sorted(git(["ls-files", "--others", "--exclude-standard"], cwd, run).splitlines()):
        path = Path(cwd) / name
        if CODE.search(name) and path.is_file() and path.stat().st_size < MAX_UNTRACKED_BYTES:
            text = path.read_bytes()
            files[name] = text.count(b"\n") + 1
            digest.update(name.encode() + text)
    return (digest.hexdigest()[:16] if files else ""), files


def state_file(session: str) -> Path:
    return cfg.state_dir() / "review-loop" / ((re.sub(r"[^A-Za-z0-9_-]", "", session) or "unknown") + ".json")


def load(session: str) -> dict:
    try:
        data = json.loads(state_file(session).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(session: str, state: dict) -> None:
    cfg.atomic_write(state_file(session), json.dumps(state))


def enabled() -> bool:
    return cfg.get("review_loop.enabled", True) is not False and os.environ.get("CARLO_HEADLESS") != "1"


def mode_start(event: dict, run: Callable = subprocess.run) -> dict:
    """New state: the diff hash that exists before the session starts changing things."""
    digest, _ = code_diff(str(event.get("cwd") or os.getcwd()), run)
    return {"baseline": digest, "asked": [], "count": 0}


def reminder(files: Dict[str, int]) -> str:
    listing = "\n".join(f"- {name} ({lines} lines)" for name, lines in sorted(files.items())[:15])
    return ("Review guardrail: code files changed in this session and no independent review has run on them:\n"
            f"{listing}\n"
            "Before saying the work is done, run the `reviewer` agent (it is read only and cannot run git, so give it "
            "these paths and what the change should do). Fix the blockers it finds, or say in one line why a finding "
            "does not apply. If the change is trivial, say so in one line instead.")


def mode_stop(event: dict, state: dict, run: Callable = subprocess.run) -> Tuple[Optional[str], dict]:
    """(reason to block the stop or None, new state). The input state is never mutated."""
    if event.get("stop_hook_active") or not enabled():
        return None, state
    digest, files = code_diff(str(event.get("cwd") or os.getcwd()), run)
    asked = list(state.get("asked") or [])
    limit = int(cfg.get("review_loop.max_per_session", 2) or 2)
    small = sum(files.values()) < int(cfg.get("review_loop.min_lines", 5) or 0)
    if not digest or digest == state.get("baseline") or digest in asked or len(asked) >= limit or small:
        return None, state
    return reminder(files), {**state, "asked": asked + [digest], "count": len(asked) + 1}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(event, dict) or mode not in ("start", "stop"):
        return 0
    session = str(event.get("session_id") or "unknown")
    if mode == "start":
        if enabled():
            save(session, mode_start(event))
        return 0
    reason, state = mode_stop(event, load(session))
    if reason:
        save(session, state)
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        cfg.log_error("review-loop", exc)
        sys.exit(0)
