"""A fake `claude` executable for tests: no model is ever called."""
import stat
import sys
from pathlib import Path


def make_fake_claude(path: Path, body: str) -> Path:
    """An executable python script standing in for `claude` (no model is ever called)."""
    path.write_text(f"#!{sys.executable}\nimport sys, os, json\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path
