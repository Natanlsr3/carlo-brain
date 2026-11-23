"""Test helpers shared by every test file. Standard library only (unittest style, also runs under pytest)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "lib"))

import carlo_cli  # noqa: E402

ENV_KEYS = ("HOME", "CARLO_BRAIN_HOME", "CARLO_CLAUDE_DIR", "CARLO_VAULT", "CARLO_LIB", "CARLO_NO_LAUNCHD",
            "CARLO_REPO", "CARLO_HEADLESS", "CARLO_EXTRACTION")


def module_src(name: str) -> str:
    """Put a module's src folder on sys.path and return it."""
    path = str(ROOT / "modules" / name / "src")
    if path not in sys.path:
        sys.path.insert(0, path)
    return path


class BrainEnv:
    """A throwaway HOME with a rendered vault, Carlo Brain home and Claude dir. Restores the environment on exit."""

    def __init__(self, with_vault: bool = True) -> None:
        self.with_vault = with_vault
        self._tmp: Optional[tempfile.TemporaryDirectory] = None
        self._saved: dict = {}

    def __enter__(self) -> "BrainEnv":
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.home = self.root / "home"
        self.brain = self.home / ".carlo-brain"
        self.claude = self.home / ".claude"
        self.vault = self.root / "vault"
        for path in (self.home, self.brain / "state", self.claude):
            path.mkdir(parents=True, exist_ok=True)
        self._saved = {k: os.environ.get(k) for k in ENV_KEYS}
        os.environ.update({"HOME": str(self.home), "CARLO_BRAIN_HOME": str(self.brain), "CARLO_CLAUDE_DIR": str(self.claude),
                           "CARLO_VAULT": str(self.vault), "CARLO_LIB": str(ROOT / "core" / "lib"),
                           "CARLO_NO_LAUNCHD": "1", "CARLO_REPO": str(ROOT)})
        os.environ.pop("CARLO_HEADLESS", None)
        os.environ.pop("CARLO_EXTRACTION", None)
        if self.with_vault:
            values = {"ASSISTANT_NAME": "Testy", "USER_NAME": "Sam", "VAULT": str(self.vault)}
            carlo_cli.copy_template(ROOT / "core" / "vault-template", self.vault, values)
        return self

    def __exit__(self, *exc: object) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        assert self._tmp is not None
        self._tmp.cleanup()

    def env(self, **extra: str) -> dict:
        """Environment dict for subprocesses (hooks)."""
        return {**os.environ, **extra}

    @property
    def system(self) -> Path:
        return self.vault / "00_System"


def run_script(script: Path, stdin: str = "", args: tuple = (), env: Optional[dict] = None) -> subprocess.CompletedProcess:
    """Run a hook script the way Claude Code does (python -I, event JSON on stdin)."""
    return subprocess.run([sys.executable, "-I", str(script), *args], input=stdin, capture_output=True, text=True,
                          env=env or os.environ.copy(), timeout=60)


def write_transcript(path: Path, messages: list, start: Optional[datetime] = None, tool_uses: Optional[list] = None) -> Path:
    """Write a minimal Claude Code JSONL transcript: user messages, each followed by an assistant reply."""
    start = start or datetime.now().astimezone()
    lines = []
    for index, text in enumerate(messages):
        stamp = (start + timedelta(minutes=index)).isoformat()
        lines.append({"type": "user", "timestamp": stamp, "message": {"role": "user", "content": text}})
        content = [{"type": "text", "text": f"reply {index}"}] + ((tool_uses or []) if index == 0 else [])
        lines.append({"type": "assistant", "timestamp": stamp, "message": {"role": "assistant", "content": content}})
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return path
