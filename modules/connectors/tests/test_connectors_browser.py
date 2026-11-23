"""Browser connector: subprocess is mocked, nothing is registered with a real Claude Code."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "browser"))
import browser_setup as bs  # noqa: E402

SKILL = Path(__file__).resolve().parents[2] / "agents-skills" / "src" / "skills" / "browse" / "SKILL.md"


class FakeClaude:
    """Records every command; `get` succeeds only once the server was added."""

    def __init__(self, registered=False, fail_on=None):
        self.registered, self.fail_on, self.calls = registered, fail_on, []

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        verb = command[2]
        if verb == "get":
            code = 0 if self.registered else 1
        elif verb == self.fail_on:
            code = 3
        else:
            code = 0
            self.registered = verb == "add"
        return subprocess.CompletedProcess(command, code, "", "")


def which_all(name):
    return f"/usr/bin/{name}"


def which_none(name):
    return None


def test_setup_registers_once_and_writes_marker(brain_home):
    run = FakeClaude()
    ok, message = bs.setup("latest", run, which_all)
    assert ok and "registered playwright" in message
    assert ["claude", "mcp", "add", "playwright", "-s", "user", "--", "npx", "@playwright/mcp@latest"] in run.calls
    assert json.loads(bs.marker_path().read_text()) == {"server": "playwright", "version": "latest"}
    again = bs.setup("latest", run, which_all)
    assert again == (True, "already registered")
    assert sum(1 for c in run.calls if c[2] == "add") == 1


def test_setup_pins_a_version_and_refuses_a_bad_one(brain_home):
    run = FakeClaude()
    assert bs.setup("0.0.30", run, which_all)[0]
    assert run.calls[-1][-1] == "@playwright/mcp@0.0.30"
    ok, message = bs.setup("1.0; rm -rf /", run, which_all)
    assert not ok and "invalid version" in message


def test_setup_needs_claude_and_npx(brain_home):
    ok, message = bs.setup("latest", FakeClaude(), which_none)
    assert not ok and "claude not found" in message
    assert not bs.marker_path().exists()


def test_setup_reports_add_failure_and_timeout(brain_home):
    ok, message = bs.setup("latest", FakeClaude(fail_on="add"), which_all)
    assert not ok and "exited 3" in message and not bs.marker_path().exists()

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1)

    assert bs.setup("latest", timeout, which_all)[0] is False


def test_remove_is_idempotent_and_clears_the_marker(brain_home):
    run = FakeClaude()
    bs.setup("latest", run, which_all)
    assert bs.remove(run, which_all) == (True, "removed")
    assert ["claude", "mcp", "remove", "playwright", "-s", "user"] in run.calls
    assert not bs.marker_path().exists()
    assert bs.remove(run, which_all) == (True, "was not registered")


def test_check_is_silent_until_set_up_then_reports(brain_home):
    assert bs.check(FakeClaude(), which_all) == []
    bs.setup("latest", FakeClaude(), which_all)
    assert bs.check(FakeClaude(registered=True), which_all)[0][0] == "ok"
    assert bs.check(FakeClaude(registered=False), which_all)[0][0] == "warn"
    assert "npx" in bs.check(FakeClaude(), lambda n: None if n == "npx" else "/x")[0][1]


def test_run_cli_status_exit_codes(brain_home):
    lines = []
    assert bs.run_cli(["status"], FakeClaude(registered=True), which_all, lines.append) == 0
    assert bs.run_cli(["status"], FakeClaude(), which_all, lines.append) == 1
    assert lines == ["registered", "not registered"]
    assert bs.run_cli(["nonsense"], FakeClaude(), which_all, lines.append) == 2


def test_browse_skill_states_the_hard_rules():
    text = SKILL.read_text()
    assert text.startswith("---\nname: browse\n") and "description:" in text
    for rule in ("own tab", "form", "never enter secrets", "data, not instructions", "go"):
        assert rule in text.lower()
    assert chr(0x2014) not in text and chr(0x2013) not in text
