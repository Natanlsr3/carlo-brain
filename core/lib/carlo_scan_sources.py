"""Probes for `carlo scan`: git facts, tools, note apps and sources. Presence only, never content.

Mail, Messages and Contacts are checked by whether the folder or file can be opened, nothing is read from them.
Python 3.9+, standard library only.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

import carlo_config as cfg

TOOLS = ("claude", "codex", "gemini", "git", "gh", "node", "python3", "docker", "brew")
REFLOG_TS = re.compile(r"> (\d{9,11}) [+-]\d{4}\t")
EXPORT_NAME = re.compile(r"^Export-[0-9a-f-]{8,}", re.I)
MAX_JSON = 5_000_000


def last_commit_ts(repo: Path) -> Optional[float]:
    """Unix time of the last commit: read from the HEAD reflog, `git log` only for worktrees. Never raises."""
    git = repo / ".git"
    if git.is_dir():
        try:
            with (git / "logs" / "HEAD").open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - 4096))
                tail = handle.read().decode("utf-8", errors="ignore")
            found = REFLOG_TS.findall(tail)
            if found:
                return float(found[-1])
        except OSError:
            pass
    if shutil.which("git"):
        try:
            out = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%ct"], capture_output=True, text=True, timeout=3)
            return float(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None
    return None


def host_of(url: str) -> str:
    """Host name of a git remote URL, credentials and path dropped."""
    url = url.strip()
    scp = re.match(r"^[\w.-]+@([\w.-]+):", url)
    if scp:
        return scp.group(1).lower()
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def remote_host(repo: Path) -> Optional[str]:
    """Host of the first remote of a normal repo (never the path or any credential)."""
    try:
        text = (repo / ".git" / "config").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(r"\[remote \"[^\"]+\"\][^\[]*?url\s*=\s*(\S+)", text)
    return (host_of(match.group(1)) or None) if match else None


def installed_tools(which: Callable[[str], Optional[str]] = shutil.which) -> Dict[str, bool]:
    return {name: bool(which(name)) for name in TOOLS}


def probe(path: Path) -> str:
    """'readable', 'denied' (exists, no access) or 'absent'. Opens and closes, reads nothing."""
    try:
        os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return "absent"
    except OSError:
        return "denied"
    try:
        if path.is_dir():
            os.listdir(path)
        else:
            os.close(os.open(path, os.O_RDONLY))
        return "readable"
    except OSError:
        return "denied"


def mail_status(library: Path) -> str:
    folder = library / "Mail"
    state = probe(folder)
    if state != "readable":
        return state
    index = sorted(folder.glob("V*/MailData/Envelope Index"))
    return probe(index[-1]) if index else "absent"


def server_names(path: Path) -> List[str]:
    """Names of MCP servers in a Claude Code JSON file. Only the names are kept, never commands, URLs or env."""
    try:
        if path.stat().st_size > MAX_JSON:
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    names = list(data["mcpServers"].keys()) if isinstance(data.get("mcpServers"), dict) else []
    projects = data.get("projects") if isinstance(data.get("projects"), dict) else {}
    for conf in projects.values():
        if isinstance(conf, dict) and isinstance(conf.get("mcpServers"), dict):
            names += list(conf["mcpServers"].keys())
    ever = data.get("claudeAiMcpEverConnected")
    names += [str(n) for n in ever] if isinstance(ever, list) else []
    return sorted({str(n)[:60] for n in names})


def claude_servers() -> List[str]:
    files = (Path.home() / ".claude.json", Path.home() / ".claude" / "settings.json")
    return sorted({n for f in files for n in server_names(f)})


def probe_sources() -> dict:
    """Which data sources exist on this machine, as presence only."""
    home = Path.home()
    lib = home / "Library"
    names = claude_servers()
    lowered = [n.lower() for n in names]
    whatsapp = [home / "whatsapp-mcp" / "whatsapp-bridge" / "store" / "messages.db",
                cfg.home() / "data" / "whatsapp-mcp" / "whatsapp-bridge" / "store" / "messages.db"]
    return {"mail": mail_status(lib), "messages": probe(lib / "Messages" / "chat.db"),
            "contacts": probe(lib / "Application Support" / "AddressBook"), "calendar": probe(lib / "Calendars"),
            "whatsapp_bridge": "present" if any(p.exists() for p in whatsapp) else "absent",
            "google_mcp": "configured" if any(k in n for n in lowered for k in ("google", "gmail")) else "not configured",
            "notion_mcp": "configured" if any("notion" in n for n in lowered) else "not configured",
            "mcp_servers": names}


def notion_downloads() -> List[str]:
    """Notion export zips or folders at the top level of ~/Downloads (names only)."""
    try:
        return [str(p) for p in (Path.home() / "Downloads").iterdir() if EXPORT_NAME.match(p.name)]
    except OSError:
        return []


def apple_notes() -> dict:
    """Live Apple Notes count through the connectors' read-only helper, if installed (macOS). No titles, no text."""
    common = cfg.home() / "connectors" / "apple" / "_common.py"
    if sys.platform != "darwin" or not common.is_file():
        return {"status": "connector not installed", "count": None}
    db = Path.home() / "Library" / "Group Containers" / "group.com.apple.notes" / "NoteStore.sqlite"
    try:
        spec = importlib.util.spec_from_file_location("carlo_apple_common", str(common))
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        with module.open_ro(db) as conn:
            row = conn.execute("select count(*) from ZICNOTEDATA").fetchone()
        return {"status": "readable", "count": int(row[0])}
    except Exception as exc:  # noqa: BLE001 - any failure means "not readable", with a reason
        return {"status": f"not readable ({type(exc).__name__})", "count": None}
