"""Read the briefing aloud once a day (opt-in). macOS `say`; Linux `spd-say` or `espeak`.

Rules: off unless voice.enabled; only inside voice.hours; once per day (marker file); a file named
voice_off in the state directory mutes it; failures are logged to voice.log and show up as an
outage line in the next briefing, so a broken voice is never silent.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from .paths import state_dir


def due(now: datetime, cfg: Dict[str, Any], directory: Optional[Path] = None) -> bool:
    """True if voice is enabled, inside the hours window, not muted, and not yet played today."""
    directory = directory or state_dir()
    start, end = cfg["voice"]["hours"]
    if not cfg["voice"]["enabled"] or (directory / "voice_off").exists() or not start <= now.hour < end:
        return False
    try:
        return (directory / "voice_day").read_text(encoding="utf-8").strip() != f"{now:%Y-%m-%d}"
    except OSError:
        return True


def spoken_text(markdown: str) -> str:
    """Briefing markdown without symbols and list numbers."""
    text = re.sub(r"^#+\s*", "", markdown, flags=re.MULTILINE)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    return re.sub(r"[*_`>|#]", "", text).strip()


def installed_voices(run: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run) -> List[str]:
    """Names of the macOS voices (empty on other systems)."""
    if not shutil.which("say"):
        return []
    out = run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    return [line.split()[0] for line in out.splitlines() if line.strip()]


def command_for(cfg: Dict[str, Any], voices: Sequence[str]) -> List[str]:
    """Command that reads stdin aloud. Raises RuntimeError with a readable cause when none is available."""
    custom = cfg["voice"]["command"].strip()
    if custom:
        return custom.split()
    if shutil.which("say"):
        wanted = cfg["voice"]["voice"] or next((v for v in cfg["voice"]["prefer"] if v in voices), "")
        return ["say", "-v", wanted, "-f", "-"] if wanted else ["say", "-f", "-"]
    for tool, args in (("spd-say", ["-e"]), ("espeak", ["--stdin"])):
        if shutil.which(tool):
            return [tool, *args]
    raise RuntimeError("no text to speech tool found (macOS say, spd-say or espeak); set voice.command")


def log(directory: Path, message: str) -> None:
    """Append 'YYYY-MM-DD HH:MM OK ...' or '... FAIL cause' to voice.log."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "voice.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now():%Y-%m-%d %H:%M} {message}\n")


def speak(cfg: Dict[str, Any], directory: Optional[Path] = None,
          run: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run) -> bool:
    """Speak briefing.md now. Returns True on success; logs either way."""
    directory = directory or state_dir()
    try:
        text = spoken_text((directory / "briefing.md").read_text(encoding="utf-8"))
    except OSError:
        log(directory, "FAIL briefing.md missing")
        return False
    if not text:
        log(directory, "FAIL briefing.md empty")
        return False
    try:
        command = command_for(cfg, installed_voices())
        result = run(command, input=text, capture_output=True, text=True, timeout=300)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as err:
        log(directory, f"FAIL {str(err)[:100]}")
        return False
    if result.returncode != 0:
        log(directory, f"FAIL {' '.join((result.stderr or '').split())[:100] or 'exit ' + str(result.returncode)}")
        return False
    log(directory, f"OK {command[0]}")
    return True


def play_if_due(now: datetime, cfg: Dict[str, Any], directory: Optional[Path] = None,
                spawn: Optional[Callable[[], None]] = None) -> bool:
    """Mark today as played, then speak in the background (`spawn` is injectable for tests)."""
    directory = directory or state_dir()
    if not due(now, cfg, directory):
        return False
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "voice_day").write_text(f"{now:%Y-%m-%d}\n", encoding="utf-8")
    if spawn is not None:
        spawn()
        return True
    import sys

    subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve().parents[1] / "run.py"), "say"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return True
