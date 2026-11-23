#!/usr/bin/env python3
"""Set up the Playwright MCP server for Claude Code. Python stdlib only.

  browser_setup.py setup [--version V]   register the server (user scope), idempotent
  browser_setup.py remove                unregister it, idempotent
  browser_setup.py status                is it registered (read only)

Also reachable as `carlo connect browser [--remove|--status] [--version V]`; `carlo doctor` calls check().
It runs `claude mcp add/get/remove playwright -s user` and writes a marker, config.d/browser.json, so that
doctor only looks for the server once you asked for it. Pin a version once it works (default: latest), so an
update cannot change behaviour under you. The server drives its own browser profile, never your open tabs.
Nothing here scrapes: it only wires the server up. The rules for using it are in the `browse` skill.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

SERVER = "playwright"
PACKAGE = "@playwright/mcp"
Row = Tuple[str, str]  # level (ok / warn / fail), text


def brain_home() -> Path:
    return Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain")


def marker_path() -> Path:
    return brain_home() / "config.d" / "browser.json"


def valid_version(version: str) -> bool:
    """`latest` or a plain version like 0.0.30 (no spaces, no shell characters reach npx)."""
    return version == "latest" or re.fullmatch(r"\d+\.\d+\.\d+([-.][0-9A-Za-z.]+)?", version) is not None


def add_command(version: str = "latest") -> List[str]:
    return ["claude", "mcp", "add", SERVER, "-s", "user", "--", "npx", f"{PACKAGE}@{version}"]


def _claude(args: List[str], run: Callable, timeout: int = 60) -> subprocess.CompletedProcess:
    return run(["claude", "mcp", *args], capture_output=True, text=True, timeout=timeout)


def is_registered(run: Callable = subprocess.run) -> Optional[bool]:
    """True or False, None when it could not be checked."""
    try:
        return _claude(["get", SERVER], run, 30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return None


def setup(version: str = "latest", run: Callable = subprocess.run, which: Callable = shutil.which) -> Tuple[bool, str]:
    if not valid_version(version):
        return False, f"invalid version {version!r}: use latest or something like 0.0.30"
    for tool in ("claude", "npx"):
        if which(tool) is None:
            return False, f"{tool} not found on PATH" + (" (install Node.js)" if tool == "npx" else "")
    state = is_registered(run)
    if state is None:
        return False, "could not run `claude mcp get` (timeout or error)"
    if not state:
        try:
            res = run(add_command(version), capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as err:
            return False, f"claude mcp add failed ({type(err).__name__})"
        if res.returncode != 0:
            return False, f"claude mcp add exited {res.returncode}"
    marker_path().parent.mkdir(parents=True, exist_ok=True)
    marker_path().write_text(json.dumps({"server": SERVER, "version": version}) + "\n", encoding="utf-8")
    return True, ("already registered" if state else f"registered {SERVER} ({PACKAGE}@{version}); restart Claude Code, then check /mcp")


def remove(run: Callable = subprocess.run, which: Callable = shutil.which) -> Tuple[bool, str]:
    if which("claude") is None:
        return False, "claude not found on PATH"
    state = is_registered(run)
    if state is None:
        return False, "could not run `claude mcp get` (timeout or error)"
    if state:
        try:
            res = _claude(["remove", SERVER, "-s", "user"], run)
        except (OSError, subprocess.TimeoutExpired) as err:
            return False, f"claude mcp remove failed ({type(err).__name__})"
        if res.returncode != 0:
            return False, f"claude mcp remove exited {res.returncode}"
    marker_path().unlink(missing_ok=True)
    return True, "removed" if state else "was not registered"


def check(run: Callable = subprocess.run, which: Callable = shutil.which) -> List[Row]:
    """Doctor rows. Empty until `setup` was run (the connector is optional)."""
    if not marker_path().exists():
        return []
    rows: List[Row] = []
    for tool in ("claude", "npx"):
        if which(tool) is None:
            rows.append(("warn", f"browser: {tool} not found on PATH"))
    if rows:
        return rows
    state = is_registered(run)
    if state is None:
        return [("warn", f"browser: could not check the {SERVER} MCP server")]
    return [("ok", f"browser: {SERVER} MCP server registered")] if state else \
           [("warn", f"browser: {SERVER} MCP server not registered (run: carlo connect browser)")]


def run_cli(argv: List[str], run: Callable = subprocess.run, which: Callable = shutil.which, out: Callable = print) -> int:
    action = argv[0] if argv else "setup"
    version = argv[argv.index("--version") + 1] if "--version" in argv and argv.index("--version") + 1 < len(argv) else "latest"
    if action == "status":
        state = is_registered(run)
        out({True: "registered", False: "not registered", None: "unknown"}[state])
        return 0 if state else 1
    if action not in ("setup", "remove"):
        out(__doc__)
        return 2
    ok, message = setup(version, run, which) if action == "setup" else remove(run, which)
    out(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
