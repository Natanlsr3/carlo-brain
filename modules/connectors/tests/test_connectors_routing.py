"""Routing layer: HTTP and `claude -p` are mocked, no network, no real key."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "openrouter"))
import route  # noqa: E402

CONFIG = {**route.DEFAULTS, "agents": {"researcher": "openrouter:vendor/cheap"},
          "kinds": {"summarise": "openrouter:vendor/small", "bad": "gpt-4"}}


def fake_run(stdout="claude answer", code=0, seen=None):
    def run(command, **kwargs):
        if seen is not None:
            seen.update(command=command, kwargs=kwargs)
        return subprocess.CompletedProcess(command, code, stdout, "")
    return run


def put_key(brain_home):
    (brain_home / "keys").mkdir(parents=True)
    path = brain_home / "keys" / "openrouter"
    path.write_text("test-key-not-real")
    os.chmod(path, 0o600)


def test_resolve_order_agent_then_kind_then_default():
    assert route.resolve(CONFIG, agent="researcher", kind="summarise") == "openrouter:vendor/cheap"
    assert route.resolve(CONFIG, agent="cto", kind="summarise") == "openrouter:vendor/small"
    assert route.resolve(CONFIG, agent="cto", kind="classify") == "claude"
    assert route.resolve({**CONFIG, "default": "openrouter:x/y"}, kind="nothing") == "openrouter:x/y"


def test_invalid_targets_are_ignored_not_guessed():
    assert route.resolve(CONFIG, kind="bad") == "claude"
    assert route.resolve({**CONFIG, "default": "nonsense"}) == "claude"


def test_missing_or_broken_config_means_all_claude(brain_home):
    assert route.load_config()["default"] == "claude"
    (brain_home / "config.d").mkdir(parents=True)
    (brain_home / "config.d" / "routing.json").write_text("{not json")
    assert route.resolve(route.load_config(), agent="researcher") == "claude"
    (brain_home / "config.d" / "routing.json").write_text(json.dumps({"agents": {"a": "openrouter:m/n"}}))
    assert route.resolve(route.load_config(), agent="a") == "openrouter:m/n"


def test_routed_task_goes_to_the_provider_with_the_model_and_key(brain_home):
    put_key(brain_home)
    seen = {}

    def ask(model, prompt, key, base_url, system, max_tokens):
        seen.update(model=model, prompt=prompt, key=key, system=system)
        return "cheap answer"

    out = route.route("text", CONFIG, agent="researcher", system="be brief", ask=ask, run=fake_run())
    assert out == {"answer": "cheap answer", "target": "openrouter:vendor/cheap", "note": ""}
    assert seen["model"] == "vendor/cheap" and seen["key"] == "test-key-not-real" and seen["system"] == "be brief"


def test_provider_error_falls_back_to_claude(brain_home):
    put_key(brain_home)

    def ask(*args):
        raise RuntimeError("provider answered HTTP 500")

    out = route.route("text", CONFIG, kind="summarise", ask=ask, run=fake_run("from claude"))
    assert out["answer"] == "from claude" and out["target"] == "claude"
    assert "HTTP 500" in out["note"] and "test-key" not in out["note"]


def test_missing_key_falls_back_to_claude(brain_home):
    out = route.route("text", CONFIG, kind="summarise", ask=lambda *a: "never", run=fake_run("from claude"))
    assert out["target"] == "claude" and "key file not found" in out["note"]


def test_fallback_none_raises(brain_home):
    with pytest.raises(RuntimeError, match="failed"):
        route.route("t", {**CONFIG, "fallback": "none"}, kind="summarise", ask=lambda *a: "x", run=fake_run())


def test_claude_target_runs_claude_p_in_a_clean_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "should-not-pass")
    monkeypatch.setenv("SOME_SECRET", "nor-this")
    seen = {}
    out = route.route("hello", CONFIG, agent="cto", system="sys", run=fake_run(seen=seen))
    assert out["target"] == "claude"
    assert seen["command"] == ["claude", "-p", "--append-system-prompt", "sys"]
    assert seen["kwargs"]["input"] == "hello"
    assert "OPENROUTER_API_KEY" not in seen["kwargs"]["env"] and "SOME_SECRET" not in seen["kwargs"]["env"]


def test_claude_failure_raises():
    with pytest.raises(RuntimeError, match="claude exited 1"):
        route.run_claude("x", run=fake_run("", code=1))


def test_cli_resolve_and_ask(brain_home, monkeypatch, capsys):
    (brain_home / "config.d").mkdir(parents=True)
    (brain_home / "config.d" / "routing.json").write_text(json.dumps({"kinds": {"summarise": "openrouter:m/n"}}))
    assert route.main(["resolve", "--kind", "summarise"]) == 0
    assert capsys.readouterr().out.strip() == "openrouter:m/n"
    monkeypatch.setattr(route.subprocess, "run", fake_run("fallback text"))
    assert route.main(["ask", "--kind", "summarise", "do it"]) == 0   # no key file: falls back
    captured = capsys.readouterr()
    assert "fallback text" in captured.out and "answered by claude" in captured.err
    assert route.main(["ask", "   "]) == 2


def test_example_agent_is_tool_limited_and_uses_the_router():
    text = (Path(route.__file__).parent / "agent_routed.example.md").read_text()
    assert "tools: Bash" in text and "route.py ask" in text and chr(0x2014) not in text
