"""Configuration: JSON file merged over defaults. Unknown keys are kept, wrong types are rejected."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULTS: Dict[str, Any] = {
    "identity": {
        # Names people use for you in group chats (mention detection), and your own mail addresses.
        "names": [],
        "addresses": [],
    },
    "lookback_hours": 30,
    "refresh_minutes": 120,
    "sources": {
        "whatsapp": {
            "enabled": False,
            "db": "",  # path to the whatsapp-mcp bridge messages.db; empty = try the usual places
            "group_min_messages": 3,
            "extra_keywords": [],
            "write_raw": False,  # also write every message of the period for the LLM triage pass
        },
        "apple_mail": {"enabled": False, "root": "", "unread_direct": True, "max_items": 5},
        "followups": {
            "enabled": False,
            "min_wait_days": 2,
            "max_wait_days": 21,
            "keep_replies_hours": 48,
            "ignore": [],  # names, numbers or addresses never followed
            "channels": ["whatsapp", "mail"],
        },
        "schedules": {"enabled": False, "days": 7, "keywords": [], "max_items": 5},
        "slots": {"enabled": False, "max_items": 20},
        "todo": {"enabled": False, "file": ""},  # JSON list of {"title","due","done"}
    },
    "contacts": {"csv": ""},  # optional CSV with columns name,email used to name mail senders
    "scoring": {
        "kinds": {
            "reply": {"weight": 100, "cap": 3},
            "deadline": {"weight": 80, "cap": 3},
            "schedule": {"weight": 60, "cap": 2},
            "followup": {"weight": 40, "cap": 2},
            "direct_unanswered": {"weight": 35, "cap": 2},
            "direct_unread": {"weight": 30, "cap": 2},
            "group_activity": {"weight": 18, "cap": 1},
            "slot": {"weight": 20, "cap": 1},
            "mention": {"weight": 15, "cap": 1},
        },
        "important_names": [],  # people whose replies rank higher
        "important_bonus": 5,
    },
    "briefing": {"max_points": 5, "max_words": 200, "words_per_point": 22, "boot_max_chars": 1400},
    "voice": {"enabled": False, "hours": [6, 13], "command": "", "voice": "", "prefer": ["Samantha", "Alex"]},
}


def merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge, returns a new dict (inputs untouched)."""
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def validate(cfg: Dict[str, Any]) -> None:
    """Reject the mistakes that would otherwise fail silently. Raises ValueError."""
    for name, src in cfg["sources"].items():
        if not isinstance(src, dict) or not isinstance(src.get("enabled"), bool):
            raise ValueError(f"sources.{name}.enabled must be true or false")
    for kind, rule in cfg["scoring"]["kinds"].items():
        if not isinstance(rule.get("weight"), int) or not isinstance(rule.get("cap"), int) or rule["cap"] < 1:
            raise ValueError(f"scoring.kinds.{kind}: weight and cap must be integers (cap >= 1)")
    brief = cfg["briefing"]
    if brief["max_points"] < 1 or brief["max_words"] < 20:
        raise ValueError("briefing.max_points must be >= 1 and briefing.max_words >= 20")
    hours = cfg["voice"]["hours"]
    if not (isinstance(hours, list) and len(hours) == 2 and 0 <= hours[0] < hours[1] <= 24):
        raise ValueError("voice.hours must be [start, end] with 0 <= start < end <= 24")


def load(path: Optional[Path] = None) -> Dict[str, Any]:
    """Defaults merged with the JSON file at `path` (missing file = defaults). Raises ValueError if invalid."""
    cfg = copy.deepcopy(DEFAULTS)
    if path is not None and Path(path).exists():
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise ValueError(f"config {path} unreadable: {err}") from err
        if not isinstance(data, dict):
            raise ValueError(f"config {path} must be a JSON object")
        cfg = merge(cfg, data)
    validate(cfg)
    return cfg
