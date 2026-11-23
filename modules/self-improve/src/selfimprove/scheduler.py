"""A tiny scheduler with catch-up. One job calls `tick` every ~30 minutes (launchd or cron).

Why not one launchd job per task: a laptop that was asleep or on battery at 09:00 simply misses the
slot. Here each task has weekly slots (days + time); on every tick the latest slot is compared with the
last slot already launched, so a missed slot runs as soon as the machine is back, within `window_h`.
A slot is marked launched BEFORE the task starts, so it can never run twice.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import runner
from .settings import Settings

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,40}")
TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def load_tasks(cfg: Settings, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Tasks from config.d/self-improve-tasks.json. Raises ValueError when invalid, [] when absent."""
    path = path or cfg.brain_dir / "config.d" / "self-improve-tasks.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as err:
        raise ValueError(f"cannot read {path}: {err}") from err
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(tasks, list):
        raise ValueError("tasks file must be {\"tasks\": [...]}")
    seen = set()
    for task in tasks:
        if not isinstance(task, dict) or not NAME.fullmatch(str(task.get("name", ""))):
            raise ValueError("every task needs a name (lowercase letters, digits, - _)")
        if task["name"] in seen:
            raise ValueError(f"duplicate task name: {task['name']}")
        seen.add(task["name"])
        if not isinstance(task.get("command"), str) or not task["command"].strip():
            raise ValueError(f"task {task['name']}: command missing")
        if not TIME.fullmatch(str(task.get("time", ""))):
            raise ValueError(f"task {task['name']}: time must be HH:MM")
        days = task.get("days", DAYS)
        if not isinstance(days, list) or not days or any(d not in DAYS for d in days):
            raise ValueError(f"task {task['name']}: days must be a subset of {DAYS}")
    return tasks


def latest_slot(task: Dict[str, Any], now: datetime) -> Optional[datetime]:
    """Most recent slot at or before `now` (looking back 8 days)."""
    hour, minute = (int(x) for x in task["time"].split(":"))
    days = {DAYS.index(d) for d in task.get("days", DAYS)}
    for back in range(8):
        slot = (now - timedelta(days=back)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if slot <= now and slot.weekday() in days:
            return slot
    return None


def due_slot(task: Dict[str, Any], state: Dict[str, Any], now: datetime, tolerance_min: int = 45) -> Optional[datetime]:
    """The slot to run now, or None. Missed slots run when `catch_up` is true and they are within `window_h`."""
    slot = latest_slot(task, now)
    if slot is None:
        return None
    try:
        if datetime.fromisoformat(state["last_slot"]) >= slot:
            return None
    except (KeyError, ValueError):
        pass
    age = now - slot
    if age > timedelta(hours=int(task.get("window_h", 24))):
        return None
    if not task.get("catch_up", True) and age > timedelta(minutes=tolerance_min):
        return None
    return slot


def launch_detached(name: str) -> None:
    """Start `run-task` in its own session so tick returns immediately."""
    main = Path(__file__).resolve().parents[1] / "main.py"
    subprocess.Popen([sys.executable, "-I", str(main), "run-task", name],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def tick(cfg: Settings, tasks: List[Dict[str, Any]], now: datetime,
         launch: Callable[[str], None] = launch_detached) -> List[str]:
    """Launch every due task once. Returns one line per task started."""
    lines = []
    for task in tasks:
        state = runner.read_state(cfg, task["name"])
        slot = due_slot(task, state, now)
        if slot is None:
            continue
        runner.write_state(cfg, task["name"], {"last_slot": slot.isoformat(timespec="seconds")})
        launch(task["name"])
        late = now - slot
        lines.append(f"started: {task['name']} (slot {slot:%a %H:%M}" + (f", {int(late.total_seconds() // 3600)} h late" if late >= timedelta(hours=1) else "") + ")")
    return lines
