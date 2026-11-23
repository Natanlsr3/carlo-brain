"""Shared fixtures: fake WhatsApp bridge and fake Apple Mail data. Never touches real data."""
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def brain_home(tmp_path, monkeypatch):
    """Every test runs against a throwaway CARLO_BRAIN_HOME."""
    home = tmp_path / "brain"
    monkeypatch.setenv("CARLO_BRAIN_HOME", str(home))
    return home


@pytest.fixture
def cfg():
    from proactive import config

    return config.load(None)
