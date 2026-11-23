"""Power and time conditions for the nightly start."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional


def minutes(hhmm: str) -> int:
    hours, mins = hhmm.split(":")
    return int(hours) * 60 + int(mins)


def in_window(now: datetime, start: str, end: str) -> bool:
    """True if `now` is inside [start, end), where the window may wrap past midnight (20:30 to 06:00)."""
    here, a, b = now.hour * 60 + now.minute, minutes(start), minutes(end)
    return a <= here < b if a < b else here >= a or here < b


def evening_of(now: datetime, end: str) -> str:
    """Date of the evening a night belongs to: after midnight but before the window end it is still yesterday's."""
    if now.hour * 60 + now.minute < minutes(end):
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")


def on_mains(platform: str = sys.platform, run: Callable = subprocess.run, sysfs: Path = Path("/sys/class/power_supply")) -> Optional[bool]:
    """True on mains power, False on battery, None when it cannot be told (callers treat None as mains)."""
    try:
        if platform == "darwin":
            out = run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=10).stdout
            return "AC Power" in out if out else None
        if sysfs.is_dir():
            states = [(p / "online").read_text().strip() for p in sysfs.glob("*") if (p / "online").exists()]
            return "1" in states if states else None
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None
