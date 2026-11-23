#!/usr/bin/env python3
"""Install the agents and skills of this module into Claude Code's folders, without ever overwriting yours.

  install_agents.py install [--skip name,name]   copy agents/*.md to <claude>/agents and skills/* to <claude>/skills
  install_agents.py uninstall                    remove what this module installed and you did not edit
  install_agents.py status                       what is installed, edited, or kept as yours

<claude> is $CARLO_CLAUDE_DIR or ~/.claude. A manifest of content hashes (state/agents-skills/manifest.json)
tells our files from yours:
- target missing: copied;
- target equals what we installed earlier (you did not touch it): updated to the new version;
- target differs (you edited it, or it is your own file with the same name): left alone, our version is saved
  next to it as <name>.new so you can compare;
- uninstall removes only files that still match what we installed.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple

HERE = Path(__file__).resolve().parent


def claude_dir() -> Path:
    return Path(os.environ.get("CARLO_CLAUDE_DIR") or Path.home() / ".claude")


def brain_home() -> Path:
    return Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain")


def manifest_path() -> Path:
    return brain_home() / "state" / "agents-skills" / "manifest.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest() -> Dict[str, str]:
    try:
        data = json.loads(manifest_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_manifest(manifest: Dict[str, str]) -> None:
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def sources(skip: Tuple[str, ...] = ()) -> List[Tuple[str, Path]]:
    """(path relative to the claude folder, source file) for every agent and skill file."""
    items: List[Tuple[str, Path]] = []
    for agent in sorted((HERE / "agents").glob("*.md")):
        if agent.stem not in skip:
            items.append((f"agents/{agent.name}", agent))
    skills = HERE / "skills"
    for skill in sorted(p for p in skills.iterdir() if p.is_dir()) if skills.is_dir() else []:
        if skill.name in skip:
            continue
        for file in sorted(skill.rglob("*")):
            if file.is_file() and "__pycache__" not in file.parts:
                items.append((f"skills/{file.relative_to(skills).as_posix()}", file))
    return items


def safe_target(root: Path, relative: str) -> Path:
    """Target inside the claude folder; refuses anything that resolves elsewhere."""
    target = root / relative
    if os.path.commonpath([os.path.realpath(root), os.path.realpath(target.parent)]) != os.path.realpath(root):
        raise ValueError(f"refusing path outside the claude folder: {relative}")
    return target


def install(skip: Tuple[str, ...] = ()) -> List[str]:
    """Copy agents and skills. Returns one line per file that changed or was kept."""
    root = claude_dir()
    manifest = load_manifest()
    lines: List[str] = []
    for relative, source in sources(skip):
        target = safe_target(root, relative)
        source_hash = sha(source)
        if not target.exists():
            action = "installed"
        elif sha(target) == source_hash:
            manifest[relative] = source_hash
            continue  # already identical
        elif manifest.get(relative) == sha(target):
            action = "updated"
        else:
            shutil.copyfile(source, target.with_name(target.name + ".new"))
            lines.append(f"kept yours: {relative} (our version saved as {target.name}.new)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if source.suffix == ".sh" or os.access(source, os.X_OK):
            target.chmod(target.stat().st_mode | 0o111)
        manifest[relative] = source_hash
        lines.append(f"{action}: {relative}")
    save_manifest(manifest)
    return lines


def uninstall() -> List[str]:
    """Remove files that still match what we installed; keep edited ones. Prunes empty skill folders."""
    root = claude_dir()
    manifest = load_manifest()
    lines: List[str] = []
    remaining: Dict[str, str] = {}
    for relative, installed_hash in sorted(manifest.items()):
        target = safe_target(root, relative)
        if not target.exists():
            continue
        if sha(target) != installed_hash:
            remaining[relative] = installed_hash
            lines.append(f"kept (you edited it): {relative}")
            continue
        target.unlink()
        new = target.with_name(target.name + ".new")
        if new.exists():
            new.unlink()
        lines.append(f"removed: {relative}")
        folder = target.parent
        while folder != root / "skills" and folder != root and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
    save_manifest(remaining)
    return lines


def status() -> List[str]:
    root = claude_dir()
    manifest = load_manifest()
    lines = []
    for relative, source in sources():
        target = root / relative
        if not target.exists():
            state = "missing"
        elif sha(target) == sha(source):
            state = "installed, current"
        elif manifest.get(relative) == sha(target):
            state = "installed, older version (run install to update)"
        else:
            state = "yours or edited (not touched)"
        lines.append(f"{relative}: {state}")
    return lines


def main(argv: List[str]) -> int:
    command = argv[0] if argv else ""
    skip: Tuple[str, ...] = ()
    if "--skip" in argv and argv.index("--skip") + 1 < len(argv):
        skip = tuple(x.strip() for x in argv[argv.index("--skip") + 1].split(",") if x.strip())
    try:
        if command == "install":
            lines = install(skip)
            print("\n".join(lines) if lines else "nothing to do: everything is already installed")
            return 0
        if command == "uninstall":
            print("\n".join(uninstall()) or "nothing to remove")
            return 0
        if command == "status":
            print("\n".join(status()))
            return 0
    except (OSError, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
