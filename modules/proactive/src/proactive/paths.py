"""Runtime paths. Everything lives under CARLO_BRAIN_HOME (default ~/.carlo-brain)."""
from __future__ import annotations

import os
from pathlib import Path


def brain_home() -> Path:
    """Root of the Carlo Brain runtime tree."""
    override = os.environ.get("CARLO_BRAIN_HOME")
    return Path(override).expanduser() if override else Path.home() / ".carlo-brain"


def state_dir() -> Path:
    """Where this module keeps its state (signals, briefing, follow-up memory, logs)."""
    return brain_home() / "state" / "proactive"


def boot_dir() -> Path:
    """Directory read by the core boot injector at session start."""
    return brain_home() / "state" / "boot.d"


def config_path() -> Path:
    """Module configuration. Outside the code folder: `carlo add` replaces that folder on upgrade."""
    return brain_home() / "config.d" / "proactive.json"
