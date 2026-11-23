"""State of the deep setup: progress (resume where it stopped) and the planned setup session.

Files, under ~/.carlo-brain/state/setup/:
  progress.json      {status, step, steps_done, answers, updated}
  next_session.json  {date, time, note, created}  (the memory boot reminds on that day)
Every function returns a new dict and writes atomically. Python 3.9+, standard library only.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import carlo_config as cfg

STEPS = ["consent", "scan", "interview", "map", "write", "connectors", "plan", "done"]
MAX_ANSWER = 2000


def setup_dir() -> Path:
    return cfg.state_dir() / "setup"


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict) -> None:
    cfg.atomic_write(path, json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def load_progress() -> dict:
    return _read(setup_dir() / "progress.json")


def in_progress() -> bool:
    return load_progress().get("status") == "in_progress"


def save_progress(step: str, answers: Optional[Dict[str, str]] = None, done: bool = False) -> dict:
    """Record the current step and merge answers. With done=True the step is completed and the next one becomes current."""
    if step not in STEPS:
        raise ValueError(f"unknown step '{step}' (use one of: {', '.join(STEPS)})")
    old = load_progress()
    merged = {**old.get("answers", {}), **{k[:60]: v[:MAX_ANSWER] for k, v in (answers or {}).items()}}
    finished: List[str] = list(old.get("steps_done", []))
    current = step
    if done:
        finished = [s for s in STEPS if s in {*finished, step}]
        current = STEPS[min(STEPS.index(step) + 1, len(STEPS) - 1)]
    complete = done and step == "done"
    new = {"status": "complete" if complete else "in_progress", "step": current, "steps_done": finished,
           "answers": merged, "updated": cfg.now_iso()}
    _write(setup_dir() / "progress.json", new)
    return new


def reset() -> None:
    for name in ("progress.json", "next_session.json"):
        try:
            (setup_dir() / name).unlink()
        except OSError:
            pass


def parse_slot(day: str, at: str = "") -> datetime:
    """Validate 'YYYY-MM-DD' and optional 'HH:MM'. Raises ValueError with a readable message."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("date must look like 2026-11-27")
    if at and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", at):
        raise ValueError("time must look like 18:00")
    return datetime.strptime(f"{day} {at or '09:00'}", "%Y-%m-%d %H:%M")


def plan_session(day: str, at: str = "", today: Optional[date] = None) -> dict:
    """Store the chosen setup slot. A day in the past is refused."""
    slot = parse_slot(day, at)
    if slot.date() < (today or date.today()):
        raise ValueError("that day is already past")
    data = {"date": day, "time": at, "note": "continue the setup", "created": cfg.now_iso()}
    _write(setup_dir() / "next_session.json", data)
    return data


def clear_plan() -> None:
    try:
        (setup_dir() / "next_session.json").unlink()
    except OSError:
        pass


def reminders(today: date) -> List[str]:
    """Lines for the boot context: the planned session (that day only) and an unfinished setup."""
    out: List[str] = []
    plan = _read(setup_dir() / "next_session.json")
    if plan.get("date") == today.isoformat():
        when = f" (slot {plan['time']})" if plan.get("time") else ""
        out.append(f"Setup session planned today{when}: say 'setup' to continue.")
    progress = load_progress()
    if progress.get("status") == "in_progress" and progress.get("steps_done"):
        out.append(f"Setup was left at step '{progress.get('step')}': say 'setup' to resume (answers so far are saved).")
    return out


# ---------------------------------------------------------------- CLI

def run_cli(action: str, step: str = "", answer: Sequence[str] = (), done: bool = False, day: str = "", at: str = "", clear: bool = False) -> int:
    """`carlo setup status | save STEP | plan DATE [TIME] | finish | reset`."""
    try:
        if action == "save":
            pairs = dict(a.split("=", 1) for a in answer if "=" in a)
            state = save_progress(step, pairs, done)
            print(f"setup: step {state['step']} ({len(state['steps_done'])}/{len(STEPS)} done)")
        elif action == "finish":
            save_progress("done", done=True)
            clear_plan()
            print("setup: complete")
        elif action == "plan":
            if clear:
                clear_plan()
                print("setup: planned session cleared")
            else:
                plan = plan_session(day, at)
                print(f"setup: session planned on {plan['date']}" + (f" at {plan['time']}" if plan["time"] else ""))
        elif action == "reset":
            reset()
            print("setup: progress and plan cleared")
        else:
            state = load_progress()
            plan = _read(setup_dir() / "next_session.json")
            print(f"setup: {state.get('status', 'not started')}" + (f", at step {state['step']}" if state.get("step") else ""))
            if state.get("answers"):
                print("answers saved: " + ", ".join(sorted(state["answers"])))
            if plan:
                print(f"planned session: {plan['date']} {plan.get('time', '')}".rstrip())
            if state.get("status") != "complete":
                print("Next: run claude and type: setup")
    except ValueError as exc:
        print(f"setup: {exc}", file=sys.stderr)
        return 1
    return 0
