#!/usr/bin/env python3
"""Outgoing-send guard.

Modes (one hook each):
  tool    PreToolUse: blocks a send that contains a key, token, password, IBAN or card number.
  prompt  UserPromptSubmit: the user typing "send anyway" opens a 5 minute override for ONE send.

Unreadable input or an internal error lets the call through with a stderr warning (fail open) so a broken
hook never freezes every tool call; `carlo config set security.fail_closed true` blocks instead. Values are never printed, only type and position.
Blocked attempts are written to the audit chain as well.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _lib in (os.environ.get("CARLO_LIB"), str(Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain") / "lib")):
    if _lib:
        sys.path.insert(0, _lib)
import audit  # noqa: E402
import carlo_config as cfg  # noqa: E402
import detectors  # noqa: E402
import targets  # noqa: E402

WINDOW_S = 5 * 60
FORCE = re.compile(r"send\s+(it\s+)?anyway|send\s+despite|override\s+the\s+(send\s+)?guard", re.I)


def force_file(session: str) -> Path:
    return cfg.state_dir() / "force" / (re.sub(r"[^A-Za-z0-9_-]", "", session) or "unknown")


def override_active(session: str, now: Optional[float] = None) -> bool:
    """Consume the override if it exists and is fresh."""
    file = force_file(session)
    try:
        stamp = float(file.read_text())
        file.unlink()
    except (OSError, ValueError):
        return False
    return (now or time.time()) - stamp < WINDOW_S


def mode_prompt(data: dict) -> int:
    """Open the override when the user says so (pasted content does not count)."""
    own = re.sub(r"<pasted_content.*?</pasted_content[^>]*>", " ", str(data.get("prompt", "")), flags=re.S)
    if FORCE.search(own):
        file = force_file(str(data.get("session_id", "")))
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(str(time.time()))
    return 0


def findings_for(tool_input: object) -> list:
    extra = cfg.get("security.extra_patterns", {}) or {}
    out = []
    for field, text in targets.text_fields(tool_input):
        for item in detectors.scan(text, extra if isinstance(extra, dict) else {}):
            out.append(f"{item.type} in '{field}' (line {item.line}, column {item.column})")
    return out


def mode_tool(data: dict) -> int:
    """Return 2 (block) when a send holds sensitive data and no override is open."""
    tool, tool_input = str(data.get("tool_name", "")), data.get("tool_input")
    if not targets.is_send(tool, tool_input, tuple(cfg.get("security.send_tools", []) or [])):
        return 0
    found = findings_for(tool_input)
    if not found or override_active(str(data.get("session_id", ""))):
        return 0
    audit.append(tool, tool_input, "blocked", str(data.get("session_id", "")))
    print(f"BLOCKED (send guard) on {tool}: sensitive data detected: " + "; ".join(found[:5])
          + ". Nothing was sent. If this is intended, the user must type 'send anyway' in the chat "
          "(valid 5 minutes, one send). Do not rewrite the message to get around the guard.", file=sys.stderr)
    return 2


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "tool"
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            raise ValueError("JSON object expected")
        return mode_prompt(data) if mode == "prompt" else mode_tool(data)
    except Exception as exc:  # noqa: BLE001
        closed = mode != "prompt" and cfg.get("security.fail_closed", False) is True
        print(f"send guard: error ({type(exc).__name__}); "
              + ("blocking (security.fail_closed)" if closed else "letting the call through (security.fail_closed is off)"),
              file=sys.stderr)
        return 2 if closed else 0


if __name__ == "__main__":
    sys.exit(main())
