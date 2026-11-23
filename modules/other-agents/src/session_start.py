#!/usr/bin/env python3
"""SessionStart hook for Codex and Gemini: print the memory module's boot context, then refresh the instruction block.

  session_start.py <codex|gemini>     reads the hook JSON on stdin like the Claude Code hook does

Both tools accept the same output as Claude Code (`hookSpecificOutput.additionalContext`), so the memory module's
`boot.py` is run as it is and its output passed through. The refresh keeps the Codex copy of the system prompt and map
current for the NEXT session (the instructions file is read before this hook runs). Never raises, never blocks the start.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _lib in (os.environ.get("CARLO_LIB"), str(Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain") / "lib")):
    if _lib:
        sys.path.insert(0, _lib)
import carlo_config as cfg  # noqa: E402


def main() -> None:
    stdin = sys.stdin.read()
    boot = cfg.home() / "memory" / "boot.py"
    if boot.is_file():
        result = subprocess.run([sys.executable, "-I", str(boot)], input=stdin, capture_output=True, text=True, timeout=8)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
    import agents_connect
    agents_connect.refresh_all()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - a hook must never block the session
        cfg.log_error("other-agents.session_start", exc)
        print(f"carlo other-agents session_start: {exc}", file=sys.stderr)
