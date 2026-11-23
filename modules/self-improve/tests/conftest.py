"""Fixtures: a throwaway home, vault and brain folder. The real ~/.claude and ~/.carlo-brain are never touched."""
import os
import stat
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from selfimprove.settings import Settings  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setenv("CARLO_BRAIN_HOME", str(tmp_path / "home" / ".carlo-brain"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)


@pytest.fixture
def cfg(tmp_path):
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    for folder in (home / ".claude" / "agents", home / ".carlo-brain" / "config.d", vault / "00_System" / "skills",
                   vault / "00_System" / "memory"):
        folder.mkdir(parents=True, exist_ok=True)
    return Settings(home=home, brain=home / ".carlo-brain", vault_path=vault, test_timeout=30)
