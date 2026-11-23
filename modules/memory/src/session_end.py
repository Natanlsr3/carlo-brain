#!/usr/bin/env python3
"""SessionEnd hook: automatic log entry if the session wrote none, quality score, fact extraction.

Fact extraction (an LLM call) runs in a detached background process so the hook returns at once.
Does nothing inside Carlo's own background sessions (CARLO_HEADLESS), which prevents ghost entries and loops.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _lib in (os.environ.get("CARLO_LIB"), str(Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain") / "lib")):
    if _lib:
        sys.path.insert(0, _lib)
import carlo_config as cfg  # noqa: E402
import quality  # noqa: E402
import sessionlog  # noqa: E402


def run(event: dict) -> dict:
    """Do the work; returns what happened (testable)."""
    path = event.get("transcript_path") or ""
    result = {"logged": False, "scored": False, "facts_started": False}
    if not path or not Path(path).is_file():
        return result
    system = cfg.system_dir()
    exclude = tuple(cfg.get("memory.exclude_patterns", []) or [])
    if system:
        result["logged"] = sessionlog.add(path, system / "SESSION_LOG.md", exclude)
    try:
        quality.record(path)
        result["scored"] = True
    except Exception as exc:  # noqa: BLE001
        cfg.log_error("memory.quality", exc)
    if cfg.get("memory.extract_facts", True):
        log = cfg.state_dir() / "logs" / "facts.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as handle:
            subprocess.Popen([sys.executable, "-I", str(Path(__file__).with_name("facts.py")), path,
                              str(event.get("session_id", "unknown"))], stdout=handle, stderr=handle,
                             stdin=subprocess.DEVNULL, start_new_session=True, env={**os.environ})
        result["facts_started"] = True
    return result


def main() -> None:
    if cfg.is_headless():
        return
    try:
        run(json.load(sys.stdin))
        cfg.mark_run("session_end")
    except Exception as exc:  # noqa: BLE001 - a hook never blocks
        cfg.log_error("memory.session_end", exc)
        print(f"carlo session_end: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
