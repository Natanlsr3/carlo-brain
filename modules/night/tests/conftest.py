"""Fixtures: a throwaway brain folder. A fake `claude` stands in for the real one; no model is ever called."""
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from night import config  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CARLO_BRAIN_HOME", str(tmp_path / "brain"))


@pytest.fixture
def cfg(tmp_path):
    """Settings with the real claude replaced by `sh` (always found), keep_awake off."""
    brain = tmp_path / "brain"
    brain.mkdir(exist_ok=True)
    settings = config.load(brain)
    values = {**settings.values, "claude_bin": "sh", "keep_awake": False}
    return config.Settings(brain=brain, values=values)
