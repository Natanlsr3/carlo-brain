#!/usr/bin/env python3
"""Weekly map refresh: quick scan, diff against MAP.md, write boot.d/map-refresh.md with up to 3 suggestions.

Runs from a daily launchd job (cron on Linux) but acts at most once every 6 days. It needs the user's earlier
consent to scan (`carlo scan --yes`, stored in state/scan/consent.json), only scans the folders consented to,
and never edits MAP.md: the next session asks one closed question at a time.

Usage: refresh.py run [--force]
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _lib in (os.environ.get("CARLO_LIB"), str(Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain") / "lib")):
    if _lib:
        sys.path.insert(0, _lib)
import carlo_config as cfg  # noqa: E402
import carlo_mapdiff as mapdiff  # noqa: E402
import carlo_scan as scanner  # noqa: E402

GAP_DAYS = 6


def due(last_run: str, now: datetime) -> bool:
    """True when the last refresh is missing, unreadable, or at least 6 days old."""
    try:
        return now - datetime.fromisoformat(last_run).replace(tzinfo=None) >= timedelta(days=GAP_DAYS)
    except ValueError:
        return True


def run(force: bool = False, now: Optional[datetime] = None, scan_fn: Optional[Callable] = None) -> str:
    """One refresh. Returns a short reason or result (also printed). Never edits MAP.md."""
    now = now or datetime.now()
    system = cfg.system_dir()
    map_file = system / "MAP.md" if system else None
    if not map_file or not map_file.is_file():
        return "skipped: no MAP.md"
    map_text = map_file.read_text(encoding="utf-8")
    if "<!-- map-template" in map_text:
        return "skipped: the setup was not done yet"
    state = mapdiff.load_state()
    if not force and not due(str(state.get("last_run", "")), now):
        return "skipped: refreshed less than 6 days ago"
    roots = scanner.consented_roots()
    if not roots:
        return "skipped: no consent to scan yet (run `carlo scan --quick --yes`)"
    scan = (scan_fn or scanner.run_and_store)("quick", roots)
    connected = list((cfg.load_config().get("modules") or {}).keys())
    items = mapdiff.build_suggestions(scan, map_text, mapdiff.vault_project_names(cfg.vault()), state.get("dismissed", []), connected)
    target = cfg.boot_dir() / "map-refresh.md"
    text = mapdiff.render_boot(items, now.strftime("%Y-%m-%d"))
    if text:
        cfg.atomic_write(target, text)
    elif target.exists():
        target.unlink()
    mapdiff.mark_run(now.replace(microsecond=0).isoformat())
    return f"{len(items)} suggestion(s) written" if items else "nothing to suggest"


def main(argv: list) -> int:
    if cfg.is_headless() or not argv or argv[0] != "run":
        print("usage: refresh.py run [--force]", file=sys.stderr)
        return 2
    try:
        print(f"map refresh: {run(force='--force' in argv)}")
    except Exception as exc:  # noqa: BLE001 - a scheduled job must leave a trace, not a stack
        cfg.log_error("memory.refresh", exc)
        print(f"map refresh failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
