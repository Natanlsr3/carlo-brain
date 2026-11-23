#!/usr/bin/env python3
"""Connector check-up. Python stdlib only.

  connect.py list              the connectors, platform and what each needs
  connect.py doctor [--no-mcp] which ones work on this machine (read only, changes nothing)

`doctor` looks at: Full Disk Access for the Apple databases (macOS), the WhatsApp bridge database and
process, the Telegram bridge files, a running Remote Control tmux session, and which MCP servers
Claude Code knows (`claude mcp list`, skipped with --no-mcp because it contacts every server).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

Result = Tuple[str, str, str]  # connector, status (ok / missing / warn / skip), detail

CATALOG: List[Tuple[str, str, str]] = [
    ("apple", "macOS", "Full Disk Access for the app running the scripts (contacts, messages, notes, calendar, reminders)"),
    ("whatsapp", "macOS, Linux", "go, uv, a paired phone; see whatsapp/README.md"),
    ("google", "any", "claude.ai connectors (Gmail, Calendar, Drive, Docs, Sheets)"),
    ("notion", "any", "claude.ai connector"),
    ("slack", "any", "claude.ai connector"),
    ("browser", "any", "Claude in Chrome, Playwright MCP, or a hosted automation connector"),
    ("openrouter", "any", "an OpenRouter (or other OpenAI-compatible) key file in ~/.carlo-brain/keys/openrouter"),
    ("web-research", "any", "WebSearch, context7, the researcher agent"),
    ("remote-control", "macOS, Linux", "tmux + claude --remote-control, or the Telegram bridge"),
    ("server", "Linux (systemd)", "a small server; setup_server.sh"),
    ("vault-mcp", "macOS, Linux", "python3; token file; TLS proxy for remote use"),
]

APPLE_DBS = {
    "contacts": "~/Library/Application Support/AddressBook/AddressBook-v22.abcddb",
    "messages": "~/Library/Messages/chat.db",
    "notes": "~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite",
    "calendar": "~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb",
}


def brain_home() -> Path:
    return Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain")


def can_read_sqlite(path: Path) -> Optional[str]:
    """None if the file opens read-only, else a short reason."""
    if not path.exists():
        return "not found"
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.execute("select count(*) from sqlite_master").fetchone()
        con.close()
        return None
    except sqlite3.Error as err:
        return f"unreadable ({err})"


def check_apple(platform: str = sys.platform) -> List[Result]:
    if platform != "darwin":
        return [("apple", "skip", "macOS only")]
    results: List[Result] = []
    for name, raw in APPLE_DBS.items():
        path = Path(os.path.expanduser(raw))
        if name == "contacts" and not path.exists():
            sources = list(path.parent.glob("Sources/*/AddressBook-v22.abcddb"))
            path = sources[0] if sources else path
        problem = can_read_sqlite(path)
        if problem is None:
            results.append(("apple", "ok", f"{name} readable"))
        elif problem == "not found":
            results.append(("apple", "warn", f"{name}: database not found (app never used?)"))
        else:
            results.append(("apple", "missing", f"{name}: {problem}. Give this app Full Disk Access."))
    return results


def check_whatsapp(run: Callable = subprocess.run) -> List[Result]:
    candidates = [
        Path.home() / "whatsapp-mcp" / "whatsapp-bridge" / "store" / "messages.db",
        brain_home() / "data" / "whatsapp-mcp" / "whatsapp-bridge" / "store" / "messages.db",
    ]
    db = next((c for c in candidates if c.exists()), None)
    if db is None:
        return [("whatsapp", "skip", "not set up (optional): see whatsapp/README.md, then run whatsapp/install_bridge.sh and pair")]
    out = [("whatsapp", "ok" if can_read_sqlite(db) is None else "missing", f"database {'readable' if can_read_sqlite(db) is None else 'unreadable'}")]
    try:
        running = run(["pgrep", "-f", "whatsapp-bridge"], capture_output=True, text=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return out + [("whatsapp", "warn", "could not check the bridge process")]
    return out + [("whatsapp", "ok" if running else "warn", "bridge running" if running else "bridge not running (messages are not being collected)")]


def check_telegram() -> List[Result]:
    token = brain_home() / "keys" / "telegram_bot_token"
    config = brain_home() / "config.d" / "telegram.json"
    if not token.exists() and not config.exists():
        return [("remote-control", "skip", "telegram bridge not configured (optional)")]
    out: List[Result] = []
    if not token.exists():
        out.append(("remote-control", "missing", "telegram bot token file missing"))
    elif token.stat().st_mode & 0o077:
        out.append(("remote-control", "missing", "telegram bot token file is readable by others: chmod 600"))
    else:
        out.append(("remote-control", "ok", "telegram bot token file present, mode 600"))
    out.append(("remote-control", "ok" if config.exists() else "missing", "telegram config present" if config.exists() else "telegram config missing (allowed_user_ids)"))
    return out


def check_tmux(run: Callable = subprocess.run) -> List[Result]:
    if shutil.which("tmux") is None:
        return [("remote-control", "skip", "tmux not installed (only needed for start_remote.sh)")]
    try:
        up = run(["tmux", "has-session", "-t", os.environ.get("CARLO_REMOTE_TMUX", "carlo")], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return [("remote-control", "warn", "could not query tmux")]
    return [("remote-control", "ok" if up else "skip", "remote control session running" if up else "no remote control session (start_remote.sh start)")]


def check_mcp(run: Callable = subprocess.run) -> List[Result]:
    """Which MCP servers Claude Code lists, and whether they report as connected."""
    if shutil.which("claude") is None:
        return [("google", "missing", "claude CLI not found")]
    try:
        res = run(["claude", "mcp", "list"], capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as err:
        return [("google", "warn", f"claude mcp list failed ({err.__class__.__name__})")]
    text = res.stdout or ""
    wanted: Dict[str, Tuple[str, ...]] = {
        "google": ("gmail", "google calendar", "google drive", "google docs", "google sheets"),
        "notion": ("notion",),
        "slack": ("slack",),
        "browser": ("playwright", "chrome"),
        "web-research": ("context7", "tinyfish"),
        "whatsapp": ("whatsapp",),
        "vault-mcp": ("vault",),
    }
    lines = [l.lower() for l in text.splitlines() if l.strip()]
    results: List[Result] = []
    for connector, needles in wanted.items():
        found = [l for l in lines if any(n in l.split(":")[0] for n in needles)]
        if not found:
            results.append((connector, "skip", "no MCP server registered for it"))
            continue
        bad = [l for l in found if "failed" in l or "needs auth" in l or "disconnected" in l]
        results.append((connector, "warn" if bad else "ok", f"{len(found)} MCP server(s) listed" + (f", {len(bad)} not healthy" if bad else "")))
    return results


def doctor(with_mcp: bool = True) -> List[Result]:
    results = check_apple() + check_whatsapp() + check_telegram() + check_tmux()
    if with_mcp:
        results += check_mcp()
    return results


def render(results: List[Result]) -> str:
    marks = {"ok": "OK     ", "missing": "MISSING", "warn": "WARN   ", "skip": "skip   "}
    return "\n".join(f"{marks[s]} {c:<15} {d}" for c, s, d in results)


def main(argv: List[str]) -> int:
    command = argv[0] if argv else "list"
    if command == "list":
        for name, platform, needs in CATALOG:
            print(f"{name:<15} {platform:<16} {needs}")
        return 0
    if command == "doctor":
        results = doctor("--no-mcp" not in argv)
        print(render(results))
        return 1 if any(s == "missing" for _, s, _ in results) else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
