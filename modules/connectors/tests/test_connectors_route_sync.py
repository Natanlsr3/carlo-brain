"""route_sync: model fields and wrapper agents from routing.json. Fake HOME, no network, no `claude`."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "openrouter"))
import route  # noqa: E402
import route_sync as rs  # noqa: E402

AGENT = '---\nname: {n}\ndescription: "Does {n} things."\ntools: Read, Grep\n{m}maxTurns: 5\n---\n\n# {n}\n\nRole text of {n}.\n'


@pytest.fixture
def claude(tmp_path, monkeypatch):
    home = tmp_path / "claude"
    (home / "agents").mkdir(parents=True)
    monkeypatch.setenv("CARLO_CLAUDE_DIR", str(home))
    monkeypatch.setenv("HOME", str(tmp_path))
    return home


def agent(claude, name, model=None):
    path = claude / "agents" / f"{name}.md"
    path.write_text(AGENT.format(n=name, m=f"model: {model}\n" if model else ""), encoding="utf-8")
    return path


def config(brain_home, **data):
    (brain_home / "config.d").mkdir(parents=True, exist_ok=True)
    (brain_home / "config.d" / "routing.json").write_text(json.dumps(data))


def run(action="sync"):
    lines = []
    code = rs.run_cli(action.split(), out=lines.append)
    return code, lines


def test_tier_targets_are_valid_and_route_runs_claude_with_model():
    assert route.valid_target("claude:haiku") and route.valid_target("claude:inherit")
    assert not route.valid_target("claude:gpt")
    seen = {}

    def fake(command, **kwargs):
        seen["c"] = command
        return subprocess.CompletedProcess(command, 0, "ok", "")
    cfg = {**route.DEFAULTS, "agents": {"a": "claude:haiku"}}
    assert route.route("t", cfg, agent="a", run=fake)["answer"] == "ok"
    assert seen["c"][:4] == ["claude", "-p", "--model", "haiku"]
    assert route.claude_tier("claude:inherit") == ""


def test_with_model_replaces_inserts_and_removes():
    text = AGENT.format(n="a", m="model: sonnet\n")
    assert "model: haiku" in rs.with_model(text, "haiku") and "sonnet" not in rs.with_model(text, "haiku")
    assert rs.get_field(rs.with_model(AGENT.format(n="a", m=""), "opus"), "model") == "opus"
    assert rs.get_field(rs.with_model(text, None), "model") is None
    assert "Role text of a." in rs.with_model(text, "haiku")


def test_sync_sets_model_only_for_listed_agents_and_is_idempotent(claude, brain_home):
    mine, other = agent(claude, "researcher", "sonnet"), agent(claude, "cto", "opus")
    before_other = other.read_text()
    config(brain_home, agents={"researcher": "claude:haiku"})
    code, lines = run()
    assert code == 0 and "set researcher: model haiku" in lines
    assert rs.get_field(mine.read_text(), "model") == "haiku"
    assert other.read_text() == before_other
    after = mine.read_text()
    code, lines = run()
    assert mine.read_text() == after and "unchanged researcher: model haiku" in lines
    assert (brain_home / "state" / "route-sync" / "backup" / "researcher.md").read_text().count("model: sonnet") == 1


def test_undo_restores_original_model_and_removes_field_that_was_unset(claude, brain_home):
    a, b = agent(claude, "researcher", "sonnet"), agent(claude, "reader")
    original_a, original_b = a.read_text(), b.read_text()
    config(brain_home, agents={"researcher": "claude:opus", "reader": "claude:haiku"})
    run()
    run()
    assert rs.get_field(b.read_text(), "model") == "haiku"
    code, lines = run("sync --undo")
    assert code == 0 and a.read_text() == original_a and b.read_text() == original_b
    run("sync --undo")  # a second undo does nothing harmful
    assert a.read_text() == original_a


def test_entry_removed_from_config_is_reverted_on_next_sync(claude, brain_home):
    a = agent(claude, "researcher", "sonnet")
    config(brain_home, agents={"researcher": "claude:haiku"})
    run()
    config(brain_home, agents={})
    run()
    assert rs.get_field(a.read_text(), "model") == "sonnet"


def test_missing_agent_or_invalid_entry_is_skipped_not_created(claude, brain_home):
    config(brain_home, agents={"ghost": "claude:haiku", "../evil": "claude:haiku", "bad": "gpt-4"})
    code, lines = run()
    assert code == 0 and not (claude / "agents" / "ghost.md").exists()
    assert any("ghost" in line and "not installed" in line for line in lines)
    assert not (claude / "evil.md").exists() and not any(claude.parent.glob("evil*"))
    assert any("bad" in line and "invalid" in line for line in lines)


def test_openrouter_entry_generates_wrapper_with_bash_only_and_role(claude, brain_home):
    original = agent(claude, "researcher", "sonnet")
    snapshot = original.read_text()
    config(brain_home, agents={"researcher": "openrouter:vendor/cheap"}, kinds={"summarise": "openrouter:v/s", "x": "claude"})
    run()
    wrapper = (claude / "agents" / "researcher-routed.md").read_text()
    assert original.read_text() == snapshot
    assert "name: researcher-routed" in wrapper and "tools: Bash\n" in wrapper and "tools: Bash," not in wrapper
    assert "route.py ask --agent researcher --system-file" in wrapper and rs.MARKER in wrapper
    role = (brain_home / "state" / "route-sync" / "roles" / "researcher.txt").read_text()
    assert "Role text of researcher." in role and "name:" not in role
    skill = (claude / "skills" / "carlo-routing" / "SKILL.md").read_text()
    assert "researcher-routed" in skill and "summarise" in skill and "x," not in skill
    before = wrapper
    run()
    assert (claude / "agents" / "researcher-routed.md").read_text() == before


def test_wrapper_without_original_agent_uses_generic_role(claude, brain_home):
    config(brain_home, agents={"bulk": "openrouter:v/m"})
    run()
    assert "You are the bulk agent" in (brain_home / "state" / "route-sync" / "roles" / "bulk.txt").read_text()


def test_undo_and_removal_clean_wrappers_and_skill_but_not_your_files(claude, brain_home):
    agent(claude, "researcher")
    mine = claude / "agents" / "cto-routed.md"
    mine.write_text("---\nname: cto-routed\n---\nmy own\n")
    config(brain_home, agents={"researcher": "openrouter:v/m", "cto": "openrouter:v/n"})
    code, lines = run()
    assert mine.read_text().endswith("my own\n") and any("skipped cto-routed" in line for line in lines)
    config(brain_home, agents={})
    run()
    assert not (claude / "agents" / "researcher-routed.md").exists()
    assert not (claude / "skills" / "carlo-routing").exists()
    config(brain_home, agents={"researcher": "openrouter:v/m"})
    run()
    run("sync --undo")
    assert not (claude / "agents" / "researcher-routed.md").exists() and not (claude / "skills" / "carlo-routing").exists()
    assert mine.exists()


def test_a_skill_of_yours_with_the_same_name_is_never_overwritten(claude, brain_home):
    skill = claude / "skills" / "carlo-routing" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("mine")
    config(brain_home, agents={"a": "openrouter:v/m"})
    run()
    assert skill.read_text() == "mine"
    run("sync --undo")
    assert skill.read_text() == "mine"


def test_status_and_check_report_sync_state(claude, brain_home):
    agent(claude, "researcher", "sonnet")
    assert rs.check() == [] and run("status")[1] == ["no agent is routed (routing.json has no `agents` entry)"]
    config(brain_home, agents={"researcher": "claude:haiku", "bulk": "openrouter:v/m"})
    lines = run("status")[1]
    assert all("NOT synced" in line for line in lines) and len(lines) == 2
    assert {level for level, _ in rs.check()} == {"warn"}
    run()
    assert all(" synced " in line for line in run("status")[1])
    assert rs.check() == [("ok", "routing: 2 agent(s) match routing.json")]
    (claude / "agents" / "researcher.md").write_text(AGENT.format(n="researcher", m="model: opus\n"))
    assert any("researcher" in text and "model: opus" in text for _, text in rs.check())


def test_check_warns_about_stale_leftovers(claude, brain_home):
    config(brain_home, agents={"bulk": "openrouter:v/m"})
    run()
    config(brain_home, agents={"other": "claude"})
    assert any("bulk-routed" in text for _, text in rs.check())


def test_no_key_variables_leak_and_no_dashes_in_generated_text(claude, brain_home):
    config(brain_home, agents={"bulk": "openrouter:v/m"}, kinds={"summarise": "openrouter:v/s"})
    run()
    text = (claude / "agents" / "bulk-routed.md").read_text() + (claude / "skills" / "carlo-routing" / "SKILL.md").read_text()
    assert chr(0x2014) not in text and chr(0x2013) not in text and "KEY" not in text
