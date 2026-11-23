"""Fixtures for the connector tests: simulated Apple databases only, never real data."""
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SRC / "apple"))
sys.path.insert(0, str(SRC / "vault-mcp"))


@pytest.fixture(autouse=True)
def brain_home(tmp_path, monkeypatch):
    home = tmp_path / "brain"
    monkeypatch.setenv("CARLO_BRAIN_HOME", str(home))
    monkeypatch.delenv("CARLO_DEFAULT_COUNTRY_CODE", raising=False)
    return home
