"""The nightly trigger: decides whether to start now. Called every 10 minutes by the scheduler."""
from __future__ import annotations

import fcntl
import subprocess
import time
from datetime import datetime
from typing import Callable, List, Optional, Tuple

from . import report, marathon, power, runner, tasks
from .config import Settings


def log(cfg: Settings, message: str) -> None:
    cfg.logs.mkdir(parents=True, exist_ok=True)
    with (cfg.logs / "trigger.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now():%F %T} {message}\n")


def has_work(cfg: Settings) -> bool:
    """Something in the queue, or a marathon with open items."""
    if tasks.discover(cfg):
        return True
    backlog = cfg.marathon / "BACKLOG.md"
    return bool(cfg.values["marathon"]["enabled"] and backlog.exists() and marathon.open_items(backlog.read_text(encoding="utf-8")))


def should_start(cfg: Settings, now: datetime, mains: Optional[bool], force: bool = False) -> Tuple[bool, str]:
    """(start?, reason). Reasons are logged so a night that did not run can be explained."""
    if not has_work(cfg):
        return False, "nothing queued"
    if force:
        return True, "forced"
    win = cfg.values["window"]
    if not power.in_window(now, win["start"], win["end"]):
        return False, "outside the night window"
    marker = cfg.state / f"launched_{power.evening_of(now, win['end'])}"
    if marker.exists():
        return False, "already launched tonight"
    if cfg.values["require_ac"] and mains is False:
        return False, "waiting: on battery"
    return True, "conditions met"


def trigger(cfg: Settings, now_fn: Callable[[], datetime] = datetime.now, mains_fn: Callable[[], Optional[bool]] = power.on_mains,
            force: bool = False, run: runner.Runner = subprocess.run, sleep: Callable[[float], None] = time.sleep) -> List[str]:
    """Start the night if the conditions are met. Returns the lines of the run (empty when nothing started)."""
    cfg.state.mkdir(parents=True, exist_ok=True)
    lock = open(cfg.state / "trigger.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return []  # a night is already running
    try:
        now = now_fn()
        go, why = should_start(cfg, now, mains_fn(), force)
        if not go:
            if why.startswith("waiting"):
                log(cfg, why)
            return []
        evening = power.evening_of(now, cfg.values["window"]["end"])
        (cfg.state / f"launched_{evening}").write_text(now.isoformat(timespec="seconds"))  # marked before starting: never twice
        log(cfg, f"start ({why})")
        results = runner.run_queue(cfg, now_fn, run, respect_clock=not force) if tasks.discover(cfg) else []
        extra: List[str] = []
        if cfg.values["marathon"]["enabled"]:
            outcome = marathon.run_marathon(cfg, now_fn, run, sleep, respect_deadline=not force)
            extra.append(f"- **marathon**: {outcome.passes} pass(es), {outcome.ok} done, {outcome.failed} not done. Stopped: {outcome.reason}")
        report.write(cfg, results, now_fn(), extra)
        log(cfg, "end")
        return report.lines_for(results) + extra
    finally:
        lock.close()
