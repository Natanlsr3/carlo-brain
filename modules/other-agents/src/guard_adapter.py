#!/usr/bin/env python3
"""Run a security-module guard on a Codex or Gemini pre-tool hook payload.

  guard_adapter.py <codex|gemini> <block_secret_reads.py|send_guard.py> [args...]

The guards read Claude Code's payload (`tool_name` Bash, Read, Grep..., `tool_input`). Codex already uses `Bash` and
`tool_input.command` (its edits are `apply_patch`, whose `command` is the patch text, paths included); Gemini names the
tools run_shell_command, read_file, and so on. This adapter renames the tool and its arguments, runs the guard with the
same interpreter, and returns its exit code and stderr. Exit 2 plus a reason on stderr blocks the call in both tools
(checked in their hooks docs). An unreadable payload is passed to the guard unchanged, which decides (fail open by default).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ALLOWED = {"block_secret_reads.py", "send_guard.py"}
GEMINI_TOOLS = {"run_shell_command": "Bash", "read_file": "Read", "read_many_files": "Read", "glob": "Glob",
                "grep_search": "Grep", "list_directory": "Glob", "write_file": "Write", "replace": "Edit"}


def normalize(agent: str, data: dict) -> dict:
    """Payload in Claude Code's shape. Pure: returns a new dict."""
    name, tool_input = str(data.get("tool_name", "")), data.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if agent == "codex" and name == "apply_patch":
        return {**data, "tool_name": "Write", "tool_input": {"file_path": str(tool_input.get("command", ""))}}
    if agent != "gemini" or name not in GEMINI_TOOLS:
        return data
    new = {"command": tool_input.get("command", "")} if name == "run_shell_command" else {
        "file_path": tool_input.get("file_path") or " ".join(str(x) for x in tool_input.get("include", []) or []),
        "path": tool_input.get("dir_path", ""), "pattern": tool_input.get("pattern", "")}
    return {**data, "tool_name": GEMINI_TOOLS[name], "tool_input": new}


def main(argv: list) -> int:
    if len(argv) < 2 or argv[1] not in ALLOWED:
        print("guard_adapter: usage: guard_adapter.py <codex|gemini> <guard script> [args]", file=sys.stderr)
        return 0
    home = Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain")
    script = home / "security" / argv[1]
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
        raw = json.dumps(normalize(argv[0], data)) if isinstance(data, dict) else raw
    except ValueError:
        pass
    if not script.is_file():
        print(f"guard_adapter: {script} not found (module security removed?): guard skipped", file=sys.stderr)
        return 0
    result = subprocess.run([sys.executable, "-I", str(script), *argv[2:]], input=raw, capture_output=True, text=True, timeout=8)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
