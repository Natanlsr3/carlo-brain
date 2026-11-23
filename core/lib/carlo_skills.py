"""Core skills (shipped with the core, not a module): copied into <claude>/skills without overwriting yours.

Same rules as the agents-skills module: a missing target is copied, a target we installed and you did not edit is
updated, anything else is kept and our version is saved next to it as `<file>.new`. A manifest of content hashes
(state/core-skills.json) tells our files from yours. A copy of the sources is kept in ~/.carlo-brain/core-skills so
that other tools (Codex, Gemini exports) can read them.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Dict, List

import carlo_config as cfg
import carlo_settings as settings_io


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_path() -> Path:
    return cfg.home() / "state" / "core-skills.json"


def _load() -> Dict[str, str]:
    try:
        data = json.loads(_manifest_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _files(source: Path) -> List[Path]:
    return sorted(p for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts) if source.is_dir() else []


def install(source: Path) -> List[str]:
    """Install every skill folder under `source`. Returns one line per file that changed or was kept."""
    root = settings_io.claude_dir() / "skills"
    manifest, lines = _load(), []
    shutil.copytree(source, cfg.home() / "core-skills", dirs_exist_ok=True)
    for file in _files(source):
        relative = file.relative_to(source).as_posix()
        target = root / relative
        if target.exists() and _sha(target) == _sha(file):
            manifest[relative] = _sha(file)
            continue
        if target.exists() and manifest.get(relative) != _sha(target):
            shutil.copyfile(file, target.with_name(target.name + ".new"))
            lines.append(f"kept yours: skills/{relative} (ours saved as {target.name}.new)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)
        manifest[relative] = _sha(file)
        lines.append(f"installed: skills/{relative}")
    _manifest_path().parent.mkdir(parents=True, exist_ok=True)
    _manifest_path().write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return lines


def uninstall() -> List[str]:
    """Remove the files that still match what we installed; keep the ones you edited."""
    root = settings_io.claude_dir() / "skills"
    remaining: Dict[str, str] = {}
    lines = []
    for relative, installed in sorted(_load().items()):
        target = root / relative
        if not target.exists():
            continue
        if _sha(target) != installed:
            remaining[relative] = installed
            lines.append(f"kept (you edited it): skills/{relative}")
            continue
        target.unlink()
        new = target.with_name(target.name + ".new")
        if new.exists():
            new.unlink()
        folder = target.parent
        while folder != root and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
        lines.append(f"removed: skills/{relative}")
    if remaining:
        _manifest_path().write_text(json.dumps(remaining, indent=1, sort_keys=True), encoding="utf-8")
    else:
        try:
            _manifest_path().unlink()
        except OSError:
            pass
    shutil.rmtree(cfg.home() / "core-skills", ignore_errors=True)
    return lines
