import os
import subprocess
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1]
SRC = MODULE / "src"


def test_module_toml_is_valid_for_the_core_cli():
    core_lib = MODULE.parents[1] / "core" / "lib"
    if not (core_lib / "carlo_modules.py").exists():
        pytest.skip("core CLI not present")
    sys.path.insert(0, str(core_lib))
    import carlo_modules

    module = carlo_modules.load_module(MODULE)
    assert module.name == "self-improve"
    assert [h["event"] for h in module.hooks] == ["SessionStart"]
    assert module.launchd[0]["command"].endswith("main.py tick") and module.launchd[0]["interval"] == 1800


@pytest.mark.parametrize("script", sorted(SRC.glob("*.sh")) + [MODULE / "install.sh", MODULE / "uninstall.sh"], ids=lambda p: p.name)
def test_scripts_parse(script):
    assert subprocess.run(["bash", "-n", str(script)], capture_output=True).returncode == 0


def test_example_files_are_valid_and_match_the_built_in_defaults():
    import json

    from selfimprove import scheduler, settings

    example = json.loads((SRC / "settings.example.json").read_text())
    assert example["tiers"] == settings.DEFAULT_TIERS
    tasks = json.loads((SRC / "tasks.example.json").read_text())["tasks"]
    assert [t["name"] for t in tasks] == ["improver", "scout"]
    for task in tasks:
        assert scheduler.NAME.fullmatch(task["name"]) and scheduler.TIME.fullmatch(task["time"])


def test_no_personal_data_or_private_paths():
    banned = ("/users/", "@gmail", "\u2014") + tuple([t.strip().lower() for t in os.environ.get("CARLO_BRAIN_BANNED", "").split(",") if t.strip()])  # extra private terms: CARLO_BRAIN_BANNED=a,b (maintainer, local)
    for path in MODULE.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts and path.name != "test_selfimprove_module.py":
            try:
                text = path.read_text(encoding="utf-8").lower()
            except UnicodeDecodeError:
                continue
            for word in banned:
                assert word not in text, f"{word!r} found in {path}"


def test_create_token_refuses_when_claude_is_missing(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "CARLO_BRAIN_HOME": str(tmp_path / "brain"), "HOME": str(tmp_path)}
    out = subprocess.run(["bash", str(SRC / "create_token.sh")], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    assert out.returncode == 1 and "claude CLI not found" in out.stderr
    assert not (tmp_path / "brain" / "keys").exists()


def test_auth_env_exports_only_a_present_token_and_never_prints_it(tmp_path):
    brain = tmp_path / "brain"
    keys = brain / "keys"
    keys.mkdir(parents=True)
    token_file = keys / "claude_oauth_token"
    token_file.write_text("sk-ant-fake\n")
    base = {"PATH": "/usr/bin:/bin", "CARLO_BRAIN_HOME": str(brain)}
    shown = subprocess.run(["bash", "-c", f'. "{SRC / "auth_env.sh"}"; echo "${{CLAUDE_CODE_OAUTH_TOKEN:-unset}}" | wc -c; env | grep -c CLAUDE_CODE_OAUTH_TOKEN'],
                           capture_output=True, text=True, env=base)
    assert shown.stdout.split() == ["12", "1"]       # "sk-ant-fake" plus newline, exported
    token_file.unlink()
    none = subprocess.run(["bash", "-c", f'. "{SRC / "auth_env.sh"}"; echo "${{CLAUDE_CODE_OAUTH_TOKEN:-unset}}"'], capture_output=True, text=True, env=base)
    assert none.stdout.strip() == "unset"
