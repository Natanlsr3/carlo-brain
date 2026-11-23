"""Task folders: <queue>/<NN_name>/{task.json, prompt.md}. Discovery and the pre-flight check."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .config import Settings

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,60}")
DEFAULT_TOOLS = "Read,Grep,Glob,Edit,Write,WebSearch,WebFetch,Agent"
# macOS keeps these folders away from background agents unless they have Full Disk Access.
PROTECTED = ("Desktop", "Documents", "Downloads", "Library/Mobile Documents")


@dataclass(frozen=True)
class Task:
    name: str
    path: Path
    title: str
    steps: int
    model: str
    workdir: Path
    add_dirs: Tuple[str, ...]
    allowed_tools: str
    denied_tools: Tuple[str, ...]

    @property
    def steps_done(self) -> int:
        try:
            return int((self.path / "steps_done").read_text().strip())
        except (OSError, ValueError):
            return 0


def protected_folder(path: Path, home: Optional[Path] = None, platform: str = sys.platform) -> Optional[str]:
    """Name of the macOS protected folder `path` is under, else None (the check only applies on macOS)."""
    if platform != "darwin":
        return None
    home = Path(os.path.realpath(home or Path.home()))
    real = Path(os.path.realpath(path))
    for name in PROTECTED:
        try:
            real.relative_to(home / name)
            return name
        except ValueError:
            continue
    return None


def load_task(path: Path, cfg: Settings) -> Task:
    """Parse and validate task.json. Raises ValueError with a readable reason."""
    try:
        data = json.loads((path / "task.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError("task.json missing") from None
    except (OSError, ValueError) as err:
        raise ValueError(f"task.json unreadable: {err}") from None
    if not isinstance(data, dict):
        raise ValueError("task.json must be a JSON object")
    steps = data.get("steps", 1)
    if not isinstance(steps, int) or isinstance(steps, bool) or not 1 <= steps <= 50:
        raise ValueError("steps must be an integer between 1 and 50")
    tools = data.get("allowed_tools", DEFAULT_TOOLS)
    if not isinstance(tools, str) or not tools.strip():
        raise ValueError("allowed_tools must be a non-empty string")
    if any(part.strip() == "Bash" for part in tools.split(",")):
        raise ValueError("bare `Bash` is not allowed: list specific commands, for example Bash(git status:*)")
    add_dirs = data.get("add_dirs", [])
    denied = data.get("denied_tools", [])
    if not isinstance(add_dirs, list) or not all(isinstance(d, str) for d in add_dirs):
        raise ValueError("add_dirs must be a list of folders")
    if not isinstance(denied, list) or not all(isinstance(d, str) for d in denied):
        raise ValueError("denied_tools must be a list")
    workdir = Path(os.path.expanduser(str(data.get("workdir") or path / "work")))
    return Task(name=path.name, path=path, title=str(data.get("title", path.name)), steps=steps,
                model=str(data.get("model") or cfg.values["default_model"]), workdir=workdir,
                add_dirs=tuple(os.path.expanduser(d) for d in add_dirs), allowed_tools=tools, denied_tools=tuple(denied))


def check(path: Path, cfg: Settings, which=shutil.which) -> List[str]:
    """Pre-flight problems of a task (empty list = it can run). Nothing is executed."""
    if not NAME.fullmatch(path.name):
        return [f"folder name {path.name!r} is not a plain name"]
    problems: List[str] = []
    try:
        task = load_task(path, cfg)
    except ValueError as err:
        return [str(err)]
    prompt = path / "prompt.md"
    if not prompt.is_file() or not prompt.read_text(encoding="utf-8").strip():
        problems.append("prompt.md missing or empty")
    for folder in (task.workdir, *map(Path, task.add_dirs)):
        blocked = protected_folder(folder)
        if blocked:
            problems.append(f"{folder} is under ~/{blocked}: macOS blocks background jobs there (use a folder outside it)")
    try:
        task.workdir.mkdir(parents=True, exist_ok=True)
        probe = task.workdir / ".night_write_test"
        probe.write_text("ok")
        probe.unlink()
    except OSError:
        problems.append(f"workdir not writable: {task.workdir}")
    for folder in task.add_dirs:
        if not Path(folder).is_dir():
            problems.append(f"add_dirs folder not found: {folder}")
    claude = cfg.values["claude_bin"]
    if which(claude) is None and not Path(claude).exists():
        problems.append(f"command not found: {claude}")
    return problems


def discover(cfg: Settings) -> List[Path]:
    """Task folders in the queue, sorted by name (use NN_ prefixes for order)."""
    return sorted(p for p in cfg.queue.iterdir() if p.is_dir() and not p.name.startswith(".")) if cfg.queue.is_dir() else []


def create(cfg: Settings, name: str, prompt: str, steps: int = 1, model: Optional[str] = None, tools: str = DEFAULT_TOOLS) -> Path:
    """Create a task folder. Raises ValueError for a bad name or an existing task."""
    if not NAME.fullmatch(name):
        raise ValueError("name: letters, digits, _ . - only")
    path = cfg.queue / name
    if path.exists():
        raise ValueError(f"task {name} already exists")
    path.mkdir(parents=True)
    spec = {"title": name, "steps": steps, "allowed_tools": tools}
    if model:
        spec["model"] = model
    (path / "task.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    (path / "prompt.md").write_text(prompt, encoding="utf-8")
    return path
