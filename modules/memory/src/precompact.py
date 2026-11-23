#!/usr/bin/env python3
"""PreCompact hook: save a mechanical summary (no LLM) of the session before context is lost.

Output: ~/.carlo-brain/state/compactions/<session>_<timestamp>.md. Never raises.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _lib in (os.environ.get("CARLO_LIB"), str(Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain") / "lib")):
    if _lib:
        sys.path.insert(0, _lib)
import carlo_config as cfg  # noqa: E402
import filters  # noqa: E402
import transcript  # noqa: E402

N_MESSAGES, N_FILES, N_COMMANDS, N_DECISIONS = 12, 40, 20, 10


def render(summary: transcript.Summary, session: str) -> str:
    """Markdown of the summary (pure, testable)."""
    start = f"Started {summary.start:%Y-%m-%d %H:%M}" if summary.start else "Start unknown"
    lines = [f"# Summary before compaction: session {session[:8]}", "", start, "",
             f"## Last user messages ({min(len(summary.messages), N_MESSAGES)} of {len(summary.messages)})"]
    lines += [f"- {filters.clip(m, 300)}" for m in summary.messages[-N_MESSAGES:]] or ["- (none)"]
    lines += ["", "## Files written or edited"] + ([f"- {f}" for f in summary.files[-N_FILES:]] or ["- (none)"])
    lines += ["", "## Git and deploy commands"] + ([f"- `{c}`" for c in summary.commands[-N_COMMANDS:]] or ["- (none)"])
    lines += ["", "## Decisions spotted (go / ok / yes)"]
    lines += [f"- {m} | context: {c or 'n/a'}" for c, m in summary.decisions[-N_DECISIONS:]] or ["- (none)"]
    return "\n".join(lines) + "\n"


def write(event: dict, folder: Optional[Path] = None, now: Optional[datetime] = None) -> Optional[Path]:
    """Write the summary; returns its path, or None when there is no readable transcript."""
    path = event.get("transcript_path")
    if not path or not Path(path).is_file():
        return None
    session = re.sub(r"[^A-Za-z0-9_-]", "", str(event.get("session_id") or Path(path).stem)) or "unknown"
    folder = folder or cfg.state_dir() / "compactions"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{session}_{(now or datetime.now()):%Y%m%d-%H%M%S}.md"
    exclude = cfg.get("memory.exclude_patterns", []) or []
    out.write_text(filters.mask(render(transcript.read(path, exclude), session)), encoding="utf-8")
    return out


def main() -> None:
    try:
        write(json.load(sys.stdin))
        cfg.mark_run("precompact")
    except Exception as exc:  # noqa: BLE001
        cfg.log_error("memory.precompact", exc)
        print(f"carlo precompact: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
