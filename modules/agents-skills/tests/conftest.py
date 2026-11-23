"""Fixtures: a throwaway Claude folder and brain folder; the real ~/.claude is never touched."""
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CARLO_BRAIN_HOME", str(tmp_path / "brain"))
    monkeypatch.setenv("CARLO_CLAUDE_DIR", str(tmp_path / "claude"))
    return tmp_path
