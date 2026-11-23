"""Test doubles for subprocess.run and a task builder."""
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


class FakeRun:
    """Plays a script of (exit code, output) results, one per call, and records every call."""

    def __init__(self, script: List[Tuple[int, str]]):
        self.script = list(script)
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        code, out = self.script.pop(0) if self.script else (0, "STATUS: done - fine")
        return subprocess.CompletedProcess(cmd, code, out, "")


def done(reason="all good"):
    return 0, f"work work\nSTATUS: done - {reason}"


def make_task(cfg, name="01_demo", steps=2, tools="Read,Write", prompt="Step {STEP} of {STEPS} on {DATE} in {WORKDIR}", extra: Optional[dict] = None) -> Path:
    import json

    path = cfg.queue / name
    path.mkdir(parents=True)
    spec = {"title": name, "steps": steps, "allowed_tools": tools, **(extra or {})}
    (path / "task.json").write_text(json.dumps(spec))
    (path / "prompt.md").write_text(prompt)
    return path
