"""Settings and paths. Everything derives from `brain` so tests use a temp folder."""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Tools that act on other people or systems. A night task never gets them.
# Names depend on your connectors (list yours with /mcp); extend with config `extra_denied_tools`.
DENIED_TOOLS: List[str] = [
    "Bash(git push:*)", "Bash(rm:*)", "Bash(curl:*)", "Bash(brew:*)", "Bash(npm install -g:*)", "Bash(launchctl:*)",
    "mcp__whatsapp__send_message", "mcp__whatsapp__send_file", "mcp__whatsapp__send_audio_message",
    "mcp__claude_ai_Gmail__send_message", "mcp__claude_ai_Gmail__create_draft",
    "mcp__claude_ai_Google_Calendar__create_event", "mcp__claude_ai_Google_Calendar__update_event",
    "mcp__claude_ai_Google_Calendar__delete_event",
    "mcp__claude_ai_Notion__notion-create-pages", "mcp__claude_ai_Notion__notion-update-page",
    "mcp__claude_ai_Slack__slack_send_message",
]

DEFAULTS: Dict[str, Any] = {
    "window": {"start": "20:30", "end": "06:00"},   # the queue starts inside this window
    "last_step_before": "08:30",                     # no new step after this time in the morning
    "require_ac": True,                               # laptops: only on mains power
    "step_max_s": 10800,                              # one step may run 3 hours at most
    "default_model": "sonnet",
    "claude_bin": "claude",
    "keep_awake": True,                               # macOS caffeinate during a step
    "extra_denied_tools": [],
    "marathon": {"enabled": False, "end": "09:15", "max_passes": 40, "pass_max_s": 5400, "model": "opus",
                 "pause_on_limit_s": 600, "allowed_tools": "Read,Grep,Glob,Edit,Write,WebSearch,WebFetch,Agent"},
}


@dataclass(frozen=True)
class Settings:
    brain: Path
    values: Dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULTS))

    @property
    def data(self) -> Path:
        """Queue and work folders. Outside the code folder: upgrading the module replaces that one."""
        return self.brain / "data" / "night"

    @property
    def queue(self) -> Path:
        return self.data / "queue"

    @property
    def done(self) -> Path:
        return self.data / "done"

    @property
    def marathon(self) -> Path:
        return self.data / "marathon"

    @property
    def state(self) -> Path:
        return self.brain / "state" / "night"

    @property
    def logs(self) -> Path:
        return self.state / "logs"

    def denied(self, task_denied: Optional[List[str]] = None) -> List[str]:
        return list(dict.fromkeys(DENIED_TOOLS + list(self.values["extra_denied_tools"]) + list(task_denied or [])))


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in over.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else copy.deepcopy(value)
    return out


def _hhmm(value: Any) -> bool:
    try:
        hours, minutes = str(value).split(":")
        return 0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59
    except ValueError:
        return False


def load(brain: Optional[Path] = None) -> Settings:
    """Defaults merged with config.d/night.json. Raises ValueError on a wrong value."""
    brain = brain or (Path(os.environ["CARLO_BRAIN_HOME"]).expanduser() if os.environ.get("CARLO_BRAIN_HOME") else Path.home() / ".carlo-brain")
    values = copy.deepcopy(DEFAULTS)
    path = brain / "config.d" / "night.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise ValueError(f"cannot read {path}: {err}") from err
        if not isinstance(data, dict):
            raise ValueError(f"{path} must be a JSON object")
        values = _merge(values, data)
    for key in ("start", "end"):
        if not _hhmm(values["window"][key]):
            raise ValueError(f"window.{key} must be HH:MM")
    if not _hhmm(values["last_step_before"]) or not _hhmm(values["marathon"]["end"]):
        raise ValueError("last_step_before and marathon.end must be HH:MM")
    if not isinstance(values["step_max_s"], int) or values["step_max_s"] < 60:
        raise ValueError("step_max_s must be an integer >= 60")
    if not isinstance(values["extra_denied_tools"], list):
        raise ValueError("extra_denied_tools must be a list")
    return Settings(brain=brain, values=values)
