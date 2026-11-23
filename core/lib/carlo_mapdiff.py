"""Weekly map refresh: compare the latest scan with MAP.md and turn the gaps into at most 3 suggestions.

Pure functions plus two small state helpers. This module never edits MAP.md: the assistant asks the user one
closed question at a time and only changes the map after a yes. A suggestion answered "no" is remembered
(state/map/refresh_state.json) and never proposed again. Python 3.9+, standard library only.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Sequence

import carlo_config as cfg

ACTIVE_DAYS = 60
INACTIVE_DAYS = 30
MAX_SUGGESTIONS = 3
# Apple sources the connectors module can read; google and notion are only suggested when their MCP is already there.
CONNECTABLE = {"mail": "Mail", "messages": "Messages", "contacts": "Contacts", "calendar": "Calendar"}


def state_path() -> Path:
    return cfg.state_dir() / "map" / "refresh_state.json"


def load_state() -> dict:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def dismiss(suggestion_id: str) -> dict:
    """Remember a suggestion the user declined. Returns the new state."""
    state = load_state()
    new = {**state, "dismissed": sorted({*state.get("dismissed", []), suggestion_id[:200]})}
    cfg.atomic_write(state_path(), json.dumps(new, indent=1) + "\n")
    return new


def mark_run(now_iso: str) -> dict:
    new = {**load_state(), "last_run": now_iso}
    cfg.atomic_write(state_path(), json.dumps(new, indent=1) + "\n")
    return new


def fold(text: str) -> str:
    """Lowercase, no accents, separators as single spaces."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def map_project_names(map_text: str) -> List[str]:
    """Names listed under **Active projects** in MAP.md (text before the first colon or bracket)."""
    names, inside = [], False
    for line in map_text.splitlines():
        if line.startswith("**"):
            inside = line.lower().startswith("**active projects")
            continue
        if inside and line.lstrip().startswith("- "):
            name = re.split(r"[:(]| - ", line.lstrip()[2:].replace("**", ""), maxsplit=1)[0].strip()
            if name and not name.startswith("(Project name"):
                names.append(name)
    return names


def vault_project_names(vault: Path) -> List[str]:
    folder = vault / "10_Projects"
    try:
        return sorted(p.name for p in folder.iterdir() if p.is_dir())
    except OSError:
        return []


def new_projects(scan: dict, map_text: str, vault_names: Sequence[str]) -> List[dict]:
    """Recently committed repos that the map does not mention (by name or path)."""
    haystack = fold(map_text)
    known = {fold(n) for n in vault_names}
    out = []
    for repo in scan.get("projects", []):
        days = repo.get("last_commit_days")
        name = fold(repo.get("name", ""))
        if days is None or days > ACTIVE_DAYS or not name or name in known:
            continue
        if re.search(r"(^| )%s( |$)" % re.escape(name), haystack) or repo.get("path", "") in map_text:
            continue
        out.append({"id": "project:" + repo["name"], "kind": "project", "name": repo["name"], "path": repo["path"],
                    "text": f"add project {repo['name']} ({repo['path']}) to the map?"})
    return out


def inactive_projects(scan: dict, map_text: str) -> List[dict]:
    """Projects listed in the map whose repo or folder has had no activity for 30 days or more."""
    seen: Dict[str, int] = {}
    for repo in scan.get("projects", []):
        if repo.get("last_commit_days") is not None:
            seen[fold(repo["name"])] = repo["last_commit_days"]
    for folder in scan.get("recent_folders", []):
        seen.setdefault(fold(folder["name"]), folder["last_modified_days"])
    out = []
    for name in map_project_names(map_text):
        key = fold(name)
        ages = [d for n, d in seen.items() if n == key or (len(n) > 3 and n in key) or (len(key) > 3 and key in n)]
        if ages and min(ages) >= INACTIVE_DAYS:
            out.append({"id": "archive:" + name, "kind": "archive", "name": name,
                        "text": f"archive project {name} (no activity for {min(ages)} days)?"})
    return out


def new_sources(scan: dict, connected: Sequence[str]) -> List[dict]:
    """Readable Apple sources while the connectors module is not installed."""
    if "connectors" in connected:
        return []
    src = scan.get("sources", {})
    return [{"id": "source:" + key, "kind": "source", "name": title,
             "text": f"connect {title}? (it is readable on this machine; I give you the exact next step)"}
            for key, title in CONNECTABLE.items() if src.get(key) == "readable"]


def interleave(groups: Sequence[List[dict]], limit: int) -> List[dict]:
    """Take one from each group in turn until `limit` items."""
    out: List[dict] = []
    index = 0
    while len(out) < limit and any(index < len(g) for g in groups):
        out += [g[index] for g in groups if index < len(g)][: limit - len(out)]
        index += 1
    return out


def build_suggestions(scan: dict, map_text: str, vault_names: Sequence[str] = (), dismissed: Sequence[str] = (),
                      connected: Sequence[str] = ()) -> List[dict]:
    groups = [new_projects(scan, map_text, vault_names), inactive_projects(scan, map_text), new_sources(scan, connected)]
    skip = set(dismissed)
    return interleave([[s for s in g if s["id"] not in skip] for g in groups], MAX_SUGGESTIONS)


def render_boot(suggestions: Sequence[dict], date: str) -> str:
    """boot.d drop-in (shown once). Empty string when there is nothing to suggest."""
    if not suggestions:
        return ""
    items = "\n".join(f"{i}. {s['text']}  [id: {s['id']}]" for i, s in enumerate(suggestions, 1))
    return ("<!-- once -->\n"
            f"Map refresh ({date}): {len(suggestions)} suggestion(s) this week from a scan of the computer.\n{items}\n\n"
            "Ask the user ONE closed question at a time (yes / no), at a natural pause, never all at once. "
            "Never edit MAP.md or a project file without a yes, and show the change first. "
            "After a no, run `carlo scan --dismiss <id>` so it is not asked again.\n")
