"""Shared paths, config and small helpers for Carlo Brain scripts.

Python 3.9+, standard library only. Every hook script imports this module, so it must stay
tiny and must never raise on import.

Layout on the user's machine:
    ~/.carlo-brain/            (override with CARLO_BRAIN_HOME)
        config.json            vault path, assistant name, per-module settings
        lib/                   this file
        <module>/              installed module code
        state/                 logs, runs, boot.d drop-ins, audit chain
        keys/                  key files (chmod 600), read through *_KEY_FILE variables
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SENSITIVE_ENV = re.compile(r"(API_KEY|_KEY$|SECRET|PASSWORD|PASSWD)", re.I)
KEEP_ENV = {"CLAUDE_CODE_OAUTH_TOKEN"}


def home() -> Path:
    """Root directory of Carlo Brain on this machine."""
    return Path(os.environ.get("CARLO_BRAIN_HOME") or (Path.home() / ".carlo-brain"))


def state_dir() -> Path:
    return home() / "state"


def boot_dir() -> Path:
    """Drop-in directory: any module can write `*.md` here to inject a signal at session start."""
    return state_dir() / "boot.d"


def keys_dir() -> Path:
    return home() / "keys"


def config_path() -> Path:
    return home() / "config.json"


def load_config() -> dict:
    """Read config.json; a missing or broken file gives an empty dict."""
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get(dotted: str, default: Any = None, config: Optional[dict] = None) -> Any:
    """Read `a.b.c` from the config."""
    node: Any = load_config() if config is None else config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def with_value(config: dict, dotted: str, value: Any) -> dict:
    """Return a copy of config with `a.b.c` set (no mutation of the input)."""
    head, _, rest = dotted.partition(".")
    new = dict(config)
    if not rest:
        new[head] = value
    else:
        child = config.get(head)
        new[head] = with_value(child if isinstance(child, dict) else {}, rest, value)
    return new


def save_config(config: dict) -> None:
    atomic_write(config_path(), json.dumps(config, indent=2, ensure_ascii=False) + "\n")


def vault() -> Optional[Path]:
    """Vault root: CARLO_VAULT first, then config.json."""
    raw = os.environ.get("CARLO_VAULT") or load_config().get("vault")
    return Path(str(raw)).expanduser() if raw else None


def system_dir() -> Optional[Path]:
    v = vault()
    return v / "00_System" if v else None


def atomic_write(path: Path, text: str) -> None:
    """Write through a temp file in the same directory, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".cb_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def mark_run(name: str) -> None:
    """Record that a hook ran (read by `carlo doctor`). Never raises."""
    try:
        atomic_write(state_dir() / "runs" / f"{name}.txt", now_iso() + "\n")
    except OSError:
        pass


def last_runs() -> dict:
    runs = state_dir() / "runs"
    out = {}
    for f in sorted(runs.glob("*.txt")) if runs.is_dir() else []:
        try:
            out[f.stem] = f.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return out


def log_error(component: str, exc: BaseException) -> None:
    """Append one line to state/errors.log. Never raises."""
    try:
        path = state_dir() / "errors.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{now_iso()} {component}: {type(exc).__name__}: {exc}\n")
    except OSError:
        pass


def clean_env(base: Optional[dict] = None) -> dict:
    """Environment for background LLM calls: no API keys (the CLI uses the user's own login)."""
    source = os.environ if base is None else base
    env = {k: v for k, v in source.items() if k in KEEP_ENV or not SENSITIVE_ENV.search(k)}
    env["CARLO_HEADLESS"] = "1"
    return env


def is_headless() -> bool:
    """True inside background sessions started by Carlo itself (no log entries, no loops)."""
    return bool(os.environ.get("CARLO_HEADLESS"))
