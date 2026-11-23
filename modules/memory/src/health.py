#!/usr/bin/env python3
"""One short line per problem found in Carlo Brain itself. Prints nothing when all is well.

Cheap, read-only checks run at every session start: recent hook errors, a session-end hook that
stopped running, a missing vault. `carlo doctor` does the deep check.
Usage: health.py [--max N]
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _lib in (os.environ.get("CARLO_LIB"), str(Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain") / "lib")):
    if _lib:
        sys.path.insert(0, _lib)
import carlo_config as cfg  # noqa: E402


def _parse(stamp: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def recent_errors(now: datetime, hours: int = 24) -> list:
    path = cfg.state_dir() / "errors.log"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    recent = [l for l in lines if (_parse(l.split(" ", 1)[0]) or datetime.min.astimezone()) > now - timedelta(hours=hours)]
    return [f"{len(recent)} hook error(s) in the last {hours}h, last: {recent[-1][:140]}"] if recent else []


def stale_session_end(now: datetime, days: int = 7) -> list:
    """Warn when sessions keep starting but the session-end hook has been silent for `days` days."""
    runs = cfg.last_runs()
    ended = _parse(runs.get("session_end", ""))
    since = ended or _parse(runs.get("first_boot", ""))
    if since is None or since > now - timedelta(days=days):
        return []
    boot = _parse(runs.get("boot", ""))
    if boot is None or boot < now - timedelta(days=1):
        return []
    return [f"the session-end hook has not run for {days}+ days: session logs are not being written (run `carlo doctor`)"]


def vault_missing() -> list:
    vault = cfg.vault()
    return [] if vault and vault.is_dir() else [f"vault folder not found: {vault} (run `carlo doctor`)"]


def check(now: Optional[datetime] = None) -> list:
    """All problems, one line each."""
    now = now or datetime.now().astimezone()
    return vault_missing() + recent_errors(now) + stale_session_end(now)


def fit(lines: list, limit: int) -> str:
    """Join lines under `limit` characters, saying how many were left out."""
    if limit <= 0:
        return "\n".join(lines)
    out: list = []
    for index, line in enumerate(lines):
        if len("\n".join(out + [line])) > limit:
            out.append(f"(+{len(lines) - index} more: run `carlo doctor`)")
            break
        out.append(line)
    return "\n".join(out)


def main(argv: list) -> int:
    limit = int(argv[argv.index("--max") + 1]) if "--max" in argv and argv.index("--max") + 1 < len(argv) else 0
    text = fit(check(), limit)
    if text:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
