"""Task wrapper for unattended jobs: lock per task, state file, bounded retries, honest status.

`execute("scout", "bash ...")` records the last attempt, last success, attempt count and the last error
line in state/tasks/<name>.json, never runs two copies of the same task, and retries a failed run a
bounded number of times with a growing wait (except for definitive failures: exit 126, 127, 78).
Unix only (fcntl).
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

from .settings import Settings

DEFINITIVE = {126, 127, 78}  # not executable, not found, configuration error
LOG_LIMIT = 200_000  # bytes kept per task log


def tasks_dir(cfg: Settings) -> Path:
    return cfg.state / "tasks"


def read_state(cfg: Settings, name: str) -> Dict[str, Any]:
    """Current state of a task; {} if absent or unreadable."""
    try:
        return json.loads((tasks_dir(cfg) / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(cfg: Settings, name: str, update: Dict[str, Any]) -> Dict[str, Any]:
    """Merge `update` into the state (atomic write) and return it."""
    folder = tasks_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    state = {**read_state(cfg, name), **update}
    tmp = folder / f".{name}.json.tmp"
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    os.replace(tmp, folder / f"{name}.json")
    return state


def stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def last_line(output: str, code: int) -> str:
    """Last non-empty output line (120 characters), else the exit code."""
    lines = [x.strip() for x in output.splitlines() if x.strip()]
    return lines[-1][:120] if lines else f"exit code {code}"


def run_once(cfg: Settings, name: str, command: str) -> Tuple[int, str]:
    """Run the command through bash, append its output to the task log. Returns (code, output)."""
    log = cfg.state / "logs" / f"{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "CARLO_TASK": name, "CARLO_BRAIN_HOME": str(cfg.brain_dir)}
    try:
        res = subprocess.run(["bash", "-c", command], capture_output=True, text=True, errors="replace", env=env)
    except OSError as err:
        return 127, str(err)
    out = (res.stdout or "") + (res.stderr or "")
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"=== {stamp()} {name} exit {res.returncode}\n{out}\n")
    if log.stat().st_size > LOG_LIMIT:  # keep the tail only
        log.write_bytes(log.read_bytes()[-LOG_LIMIT // 2:])
    return res.returncode, out


def execute(cfg: Settings, name: str, command: str, retries: int = 1, wait_s: float = 60.0,
            once: Callable[[Settings, str, str], Tuple[int, str]] = run_once,
            sleep: Callable[[float], None] = time.sleep) -> int:
    """Run with a lock and bounded retries. Returns the final exit code (0 = success)."""
    folder = tasks_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    lock = open(folder / f"{name}.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0  # already running: a second copy is not an error
    code = 1
    try:
        for attempt in range(1, retries + 2):
            write_state(cfg, name, {"last_attempt": stamp(), "attempts": attempt, "status": "running"})
            code, output = once(cfg, name, command)
            if code == 0:
                write_state(cfg, name, {"last_success": stamp(), "status": "done", "error": "", "code": 0})
                return 0
            write_state(cfg, name, {"status": "failed", "error": last_line(output, code), "code": code})
            if code in DEFINITIVE or attempt > retries:
                break
            sleep(wait_s * 2 ** (attempt - 1))
        return code
    finally:
        lock.close()
