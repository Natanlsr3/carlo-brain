import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import connect

MODULE = Path(__file__).resolve().parents[1]
SRC = MODULE / "src"
SCRIPTS = sorted(SRC.rglob("*.sh")) + [MODULE / "install.sh", MODULE / "uninstall.sh"]


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if "KEY" not in k and "TOKEN" not in k}
    env.update(extra)
    return env


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: str(p.relative_to(MODULE)))
def test_every_shell_script_parses(script):
    assert subprocess.run(["bash", "-n", str(script)], capture_output=True).returncode == 0


def test_module_toml_is_valid_for_the_core_cli():
    core_lib = MODULE.parents[1] / "core" / "lib"
    if not (core_lib / "carlo_modules.py").exists():
        pytest.skip("core CLI not present")
    sys.path.insert(0, str(core_lib))
    import carlo_modules

    module = carlo_modules.load_module(MODULE)
    assert module.name == "connectors" and len(module.mcp) >= 4 and not module.hooks and not module.launchd


def test_no_personal_or_private_paths_in_the_module():
    banned = ("/Users/", "@gmail", "\u2014") + tuple([t.strip().lower() for t in os.environ.get("CARLO_BRAIN_BANNED", "").split(",") if t.strip()])  # extra private terms: CARLO_BRAIN_BANNED=a,b (maintainer, local)
    for path in MODULE.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".sh", ".md", ".toml", ".json", ".service", ".example"} and "__pycache__" not in path.parts:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            if path.name == "test_connectors_scripts_and_doctor.py":
                continue
            for word in banned:
                assert word.lower() not in text, f"{word} found in {path}"


def test_rotate_writes_private_token_keeps_backup_and_never_prints_it(tmp_path):
    token_file = tmp_path / "keys" / "vault_mcp_token"
    env = clean_env(VAULT_MCP_TOKEN_FILE=str(token_file), VAULT_MCP_SERVICE="no-such-unit-xyz")
    first = subprocess.run(["bash", str(SRC / "vault-mcp" / "rotate_token.sh")], capture_output=True, text=True, env=env)
    assert first.returncode == 0
    token = token_file.read_text()
    assert len(token) >= 40 and stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert token not in first.stdout + first.stderr
    second = subprocess.run(["bash", str(SRC / "vault-mcp" / "rotate_token.sh")], capture_output=True, text=True, env=env)
    assert token_file.read_text() != token
    backups = list(token_file.parent.glob("vault_mcp_token.bak-*"))
    assert len(backups) == 1 and backups[0].read_text() == token
    assert token not in second.stdout + second.stderr


def test_register_client_needs_arguments_and_a_real_token_file(tmp_path):
    script = str(SRC / "vault-mcp" / "register_client.sh")
    assert subprocess.run(["bash", script], capture_output=True, env=clean_env()).returncode != 0
    empty = tmp_path / "empty"
    empty.write_text("")
    assert subprocess.run(["bash", script, str(empty), "https://x.example/mcp"], capture_output=True, env=clean_env()).returncode == 1
    full = tmp_path / "full"
    full.write_text("x" * 40)
    out = subprocess.run(["bash", script, str(full)], capture_output=True, text=True, env=clean_env(VAULT_MCP_URL=""))
    assert out.returncode == 1 and "pass the server URL" in out.stderr


def test_whatsapp_install_dry_run_changes_nothing_and_pins_the_commit(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = clean_env(HOME=str(home), CARLO_BRAIN_HOME=str(home / "brain"), DRY_RUN="1")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("go", "uv", "git"):
        tool = fake_bin / name
        tool.write_text("#!/bin/sh\nexit 0\n")
        tool.chmod(0o755)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    out = subprocess.run(["bash", str(SRC / "whatsapp" / "install_bridge.sh"), "--service"], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert "checkout --quiet 7d6a06dc" in out.stdout and "go build" in out.stdout
    assert not (home / "brain").exists() and not (home / "Library").exists()


def test_whatsapp_install_reports_missing_tools(tmp_path):
    env = clean_env(DRY_RUN="1", PATH="/usr/bin:/bin")  # no go, no uv
    out = subprocess.run(["bash", str(SRC / "whatsapp" / "install_bridge.sh")], capture_output=True, text=True, env=env)
    assert out.returncode == 1 and "missing: go" in out.stderr


def test_server_setup_dry_run_and_guards(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = clean_env(HOME=str(home), CARLO_BRAIN_HOME=str(home / "brain"), DRY_RUN="1", VAULT_REPO="git@example.com:me/vault.git")
    script = str(SRC / "server" / "setup_server.sh")
    out = subprocess.run(["bash", script], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    if "missing:" in out.stderr:
        pytest.skip("git, python3 or tmux not installed here")
    assert out.returncode == 0, out.stderr
    assert "git clone git@example.com:me/vault.git" in out.stdout and "[dry run] would write" in out.stdout
    assert not (home / ".ssh").exists() and not (home / ".claude").exists() and not (home / ".config").exists()
    no_repo = subprocess.run(["bash", script], capture_output=True, text=True, env=clean_env(HOME=str(home)))
    assert no_repo.returncode == 2 and "VAULT_REPO" in no_repo.stderr


def test_start_remote_usage_and_status_without_session(tmp_path):
    script = str(SRC / "remote-control" / "start_remote.sh")
    bad = subprocess.run(["bash", script, "bogus"], capture_output=True, text=True, env=clean_env())
    assert bad.returncode == 2 and "usage" in bad.stderr
    status = subprocess.run(["bash", script, "status"], capture_output=True, text=True,
                            env=clean_env(CARLO_REMOTE_TMUX="carlo-test-no-such-session"))
    assert status.returncode == 1 and "not running" in status.stdout


# ---------- doctor ----------

def test_catalog_lists_every_connector_folder():
    folders = {p.name for p in SRC.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert folders == {name for name, _, _ in connect.CATALOG}
    for name in folders:
        assert (SRC / name / "README.md").exists(), f"{name} has no setup guide"


def test_apple_check_is_skipped_off_macos_and_flags_unreadable_databases(tmp_path, monkeypatch):
    assert connect.check_apple("linux") == [("apple", "skip", "macOS only")]
    monkeypatch.setattr(connect, "APPLE_DBS", {"notes": str(tmp_path / "missing.sqlite"), "messages": str(tmp_path / "bad.db")})
    (tmp_path / "bad.db").write_text("not a database")
    results = dict((d.split(":")[0].split()[0], s) for _, s, d in connect.check_apple("darwin"))
    assert results == {"notes": "warn", "messages": "missing"}


def test_whatsapp_check_reads_database_and_process(tmp_path, monkeypatch):
    import sqlite3

    home = tmp_path / "home"
    db = home / ".carlo-brain" / "data" / "whatsapp-mcp" / "whatsapp-bridge" / "store" / "messages.db"
    monkeypatch.setenv("CARLO_BRAIN_HOME", str(home / ".carlo-brain"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    assert connect.check_whatsapp()[0][1] == "skip"          # never set up is not a failure
    db.parent.mkdir(parents=True)
    sqlite3.connect(db).executescript("create table t(a);")
    up = lambda *a, **k: subprocess.CompletedProcess(a, 0)
    down = lambda *a, **k: subprocess.CompletedProcess(a, 1)
    assert [s for _, s, _ in connect.check_whatsapp(up)] == ["ok", "ok"]
    assert [s for _, s, _ in connect.check_whatsapp(down)] == ["ok", "warn"]


def test_telegram_check_requires_private_token_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CARLO_BRAIN_HOME", str(tmp_path))
    assert connect.check_telegram()[0][1] == "skip"
    (tmp_path / "keys").mkdir()
    token = tmp_path / "keys" / "telegram_bot_token"
    token.write_text("123:abc")
    token.chmod(0o644)
    assert connect.check_telegram()[0][1] == "missing"
    token.chmod(0o600)
    assert connect.check_telegram()[0][1] == "ok"


def test_mcp_check_maps_servers_to_connectors(monkeypatch):
    listing = "claude.ai Gmail: https://x - Connected\nwhatsapp: uv run - Failed to connect\nplaywright: npx - Connected\n"
    monkeypatch.setattr(connect.shutil, "which", lambda name: "/bin/claude")
    run = lambda *a, **k: subprocess.CompletedProcess(a, 0, listing, "")
    results = {c: s for c, s, _ in connect.check_mcp(run)}
    assert results["google"] == "ok" and results["whatsapp"] == "warn" and results["browser"] == "ok"
    assert results["slack"] == "skip" and results["vault-mcp"] == "skip"


def test_render_and_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(connect, "doctor", lambda with_mcp=True: [("apple", "missing", "x"), ("google", "ok", "y")])
    assert connect.main(["doctor", "--no-mcp"]) == 1
    assert "MISSING apple" in capsys.readouterr().out
    monkeypatch.setattr(connect, "doctor", lambda with_mcp=True: [("google", "ok", "y")])
    assert connect.main(["doctor"]) == 0
    assert connect.main(["list"]) == 0
    assert connect.main(["nope"]) == 2
