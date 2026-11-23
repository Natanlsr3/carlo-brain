"""Marathon: repeated passes over a backlog until a morning deadline (opt-in, uses a lot of your quota).

You keep BACKLOG.md (a checklist, order = priority) and the agent works through it pass after pass, writes
JOURNAL.md (what it did, and why it picked what it picked), and ticks items. Each pass is a fresh `claude -p`
that starts by reading the backlog and the journal, so progress survives between passes.
Stops at the deadline, after `max_passes`, when the backlog is empty, or after 5 failed passes in a row.
A usage limit pauses instead of failing.
"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import statusline
from .config import Settings
from .power import minutes
from .runner import Runner, log_to, prompts_dir, rules_text, run_claude

OPEN_ITEM = re.compile(r"^- \[ \]|^- (?!\[[xX]\]).*\[in progress\]", re.MULTILINE)  # a ticked item is never open


@dataclass(frozen=True)
class MarathonResult:
    passes: int
    ok: int
    failed: int
    reason: str


def open_items(backlog: str) -> int:
    """Number of unchecked items (`- [ ]`) and items marked `[in progress]`."""
    return len(OPEN_ITEM.findall(backlog))


def deadline_passed(now: datetime, cfg: Settings) -> bool:
    """True after the deadline in the morning (before noon), so an evening start is never cut."""
    here = now.hour * 60 + now.minute
    return minutes(cfg.values["marathon"]["end"]) <= here < 12 * 60


def ensure_files(cfg: Settings) -> Path:
    """Create the marathon folder with the template prompt, an empty journal and an example backlog."""
    folder = cfg.marathon
    folder.mkdir(parents=True, exist_ok=True)
    if not (folder / "prompt.md").exists():
        (folder / "prompt.md").write_text((prompts_dir() / "marathon.md").read_text(encoding="utf-8"), encoding="utf-8")
    if not (folder / "JOURNAL.md").exists():
        (folder / "JOURNAL.md").write_text("# Marathon journal\n", encoding="utf-8")
    if not (folder / "BACKLOG.md").exists():
        (folder / "BACKLOG.md").write_text("# Backlog (order = priority; tick with [x] when done and reviewed)\n\n- [ ] Example: summarise this week's notes into one page\n", encoding="utf-8")
    return folder


def pass_prompt(cfg: Settings, number: int, now: datetime) -> str:
    folder = cfg.marathon
    text = (folder / "prompt.md").read_text(encoding="utf-8")
    for key, value in {"{PASS}": str(number), "{TIME}": now.strftime("%H:%M"), "{FOLDER}": str(folder)}.items():
        text = text.replace(key, value)
    return f"{text}\n\n{rules_text()}\n\n{statusline.INSTRUCTION}\n"


def run_marathon(cfg: Settings, now_fn: Callable[[], datetime] = datetime.now, runner: Runner = subprocess.run,
                 sleep: Callable[[float], None] = time.sleep, respect_deadline: bool = True) -> MarathonResult:
    """Run passes until a stop condition. Never raises on a failed pass. `respect_deadline=False` for a manual run."""
    own = cfg.values["marathon"]
    folder = ensure_files(cfg)
    passes = ok = failed = streak = 0
    reason = "finished"
    while True:
        if respect_deadline and deadline_passed(now_fn(), cfg):
            reason = f"deadline {own['end']} reached"
            break
        if passes >= own["max_passes"]:
            reason = "maximum number of passes reached"
            break
        if open_items((folder / "BACKLOG.md").read_text(encoding="utf-8")) == 0:
            reason = "backlog empty"
            break
        passes += 1
        code, output = run_claude(cfg, pass_prompt(cfg, passes, now_fn()), own["model"], own["allowed_tools"], cfg.denied(),
                                  [], folder, own["pass_max_s"], runner)
        log_to(cfg, "marathon", passes, code, output)
        status, _why = statusline.read(output)
        if statusline.hit_limit(output) and status != "done":
            passes -= 1  # a limit pause is not a pass
            sleep(own["pause_on_limit_s"])
            continue
        if code == 0 and status == "done":
            ok += 1
            streak = 0
            sleep(20)
        else:
            failed += 1
            streak += 1
            if streak >= 5:
                reason = "5 failed passes in a row"
                break
            sleep(120)
    return MarathonResult(passes, ok, failed, reason)
