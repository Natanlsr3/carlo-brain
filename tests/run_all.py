#!/usr/bin/env python3
"""Run the repo tests with the standard library only (no pytest needed): python3 tests/run_all.py

Test files that import pytest are left to `pytest` (this runner skips them and says how many).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    loader, suite, skipped = unittest.defaultTestLoader, unittest.TestSuite(), 0
    for folder in [ROOT / "tests"] + sorted((ROOT / "modules").glob("*/tests")):
        for file in sorted(folder.glob("test_*.py")):
            text = file.read_text(encoding="utf-8")
            if "import pytest" in text or "conftest" in text or (folder / "conftest.py").exists():
                skipped += 1
                continue
            suite.addTests(loader.discover(str(folder), pattern=file.name, top_level_dir=str(folder)))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if skipped:
        print(f"note: {skipped} pytest-based test file(s) skipped; run `python3 -m pytest` for them")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
