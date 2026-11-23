"""Merge Carlo Brain hooks into ~/.claude/settings.json and a managed block into ~/.claude/CLAUDE.md.

Rules: never overwrite a file we could not parse, always take a timestamped backup before a change,
tag everything we add so removal touches only our entries. Functions that transform data are pure
(they return new objects).
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

TAG = "carlo-brain"
TAG_RE = re.compile(r"\s*#\s*" + TAG + r":([\w.-]+)\s*$")
BEGIN, END = f"<!-- {TAG}:begin -->", f"<!-- {TAG}:end -->"


class SettingsError(RuntimeError):
    """settings.json exists but cannot be used safely."""


def claude_dir() -> Path:
    return Path(os.environ.get("CARLO_CLAUDE_DIR") or (Path.home() / ".claude"))


def settings_path() -> Path:
    return claude_dir() / "settings.json"


def claude_md_path() -> Path:
    return claude_dir() / "CLAUDE.md"


def tag_command(command: str, module: str) -> str:
    """Append the ownership marker (a shell comment) to a hook command."""
    return f"{TAG_RE.sub('', command)} # {TAG}:{module}"


def owner_of(command: str) -> Optional[str]:
    match = TAG_RE.search(command or "")
    return match.group(1) if match else None


def load_settings(path: Optional[Path] = None) -> dict:
    path = path or settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except ValueError as exc:
        raise SettingsError(f"{path} is not valid JSON ({exc}); fix it first, nothing was changed") from exc
    if not isinstance(data, dict):
        raise SettingsError(f"{path} must contain a JSON object")
    _check_hooks_shape(data, path)
    return data


def _check_hooks_shape(data: dict, path: Path) -> None:
    """Refuse a hooks entry we would have to drop or guess about (nothing is changed on refusal)."""
    if "hooks" not in data:
        return
    hooks = data["hooks"]
    if not isinstance(hooks, dict):
        raise SettingsError(f'{path}: "hooks" must be an object of event name to list of groups; '
                            "fix it first, nothing was changed")
    for event, groups in hooks.items():
        bad = not isinstance(groups, list) or any(
            not isinstance(g, dict) or ("hooks" in g and not isinstance(g["hooks"], list)) for g in groups)
        if bad:
            raise SettingsError(f'{path}: hooks["{event}"] must be a list of groups with a "hooks" list; '
                                "fix it first, nothing was changed")


def remove_module_hooks(settings: dict, module: Optional[str] = None) -> dict:
    """Copy of settings without hooks tagged for `module` (all Carlo Brain hooks when None)."""
    new = copy.deepcopy(settings)
    hooks = new.get("hooks")
    if not isinstance(hooks, dict):
        return new
    for event in list(hooks):
        groups = []
        for group in hooks[event] if isinstance(hooks[event], list) else []:
            kept = [h for h in group.get("hooks", []) if not _ours(h, module)]
            if kept or "hooks" not in group:
                groups.append({**group, "hooks": kept} if "hooks" in group else group)
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not hooks:
        del new["hooks"]
    return new


def _ours(hook: object, module: Optional[str]) -> bool:
    owner = owner_of(hook.get("command", "")) if isinstance(hook, dict) else None
    return owner is not None and (module is None or owner == module)


def add_module_hooks(settings: dict, module: str, entries: list) -> dict:
    """Copy of settings with the module's hooks added (existing ones of the module replaced).

    Each entry: {event, command, matcher?, timeout?} with the command already rendered.
    """
    new = remove_module_hooks(settings, module)
    hooks = new.setdefault("hooks", {})
    for entry in entries:
        hook = {"type": "command", "command": tag_command(entry["command"], module),
                "timeout": int(entry.get("timeout", 10))}
        group = {"hooks": [hook]}
        if entry.get("matcher"):
            group = {"matcher": entry["matcher"], **group}
        hooks.setdefault(entry["event"], []).append(group)
    return new


def installed_commands(settings: dict, module: str) -> list:
    out = []
    for groups in (settings.get("hooks") or {}).values():
        for group in groups if isinstance(groups, list) else []:
            out += [h["command"] for h in group.get("hooks", []) if _ours(h, module)]
    return out


def backup(path: Path) -> Optional[Path]:
    """Copy `path` to `<name>.bak-carlo-<timestamp>`; None if it does not exist."""
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.bak-carlo-{stamp}")
    n = 1
    while target.exists():
        target = path.with_name(f"{path.name}.bak-carlo-{stamp}-{n}")
        n += 1
    shutil.copy2(path, target)
    return target


def write_settings(settings: dict, path: Optional[Path] = None) -> Optional[Path]:
    """Write settings.json atomically; returns the backup path when the content changed."""
    path = path or settings_path()
    text = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return None
    saved = backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".carlo-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return saved


def with_block(text: str, block: str) -> str:
    """Return `text` with the managed block inserted or replaced."""
    managed = f"{BEGIN}\n{block.strip()}\n{END}\n"
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.S)
    if pattern.search(text):
        return pattern.sub(lambda _m: managed, text)
    return (text.rstrip("\n") + "\n\n" if text.strip() else "") + managed


def without_block(text: str) -> str:
    pattern = re.compile(r"\n*" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.S)
    return pattern.sub("\n", text).lstrip("\n") if pattern.search(text) else text


def install_block(block: str, path: Optional[Path] = None) -> bool:
    """Insert the managed block in CLAUDE.md. Returns True when the file did not exist before."""
    path = path or claude_md_path()
    existed = path.exists()
    old = path.read_text(encoding="utf-8") if existed else ""
    new = with_block(old, block)
    if new != old:
        backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
    return not existed


def remove_block(path: Optional[Path] = None, delete_if_empty: bool = False) -> bool:
    path = path or claude_md_path()
    if not path.exists():
        return False
    old = path.read_text(encoding="utf-8")
    new = without_block(old)
    if new == old:
        return False
    backup(path)
    if delete_if_empty and not new.strip():
        path.unlink()
    else:
        path.write_text(new, encoding="utf-8")
    return True
