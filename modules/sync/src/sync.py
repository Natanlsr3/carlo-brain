#!/usr/bin/env python3
"""Git sync of the vault at session start and end.

  start  commit local changes, then pull the remote (merge, never rebase, never reset).
  end    commit local changes, push the remote, then (optional) ask a server copy to fast-forward.

Without a remote it only commits locally: that is already a free history of your vault.
On a merge conflict it aborts the merge, leaves the vault as it was, and drops a signal in
~/.carlo-brain/state/boot.d/ so the next session tells you. It never force-pushes.

Hook usage: `sync.py start --detach` (returns at once, work continues in the background).
Config (carlo config set ...): sync.remote (git URL), sync.branch (default main),
sync.server (JSON: {"host": "user@host", "path": "/path/to/vault"}).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _lib in (os.environ.get("CARLO_LIB"), str(Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain") / "lib")):
    if _lib:
        sys.path.insert(0, _lib)
import carlo_config as cfg  # noqa: E402

TIMEOUT = 40
IDENTITY = ["-c", "user.name=carlo-brain", "-c", "user.email=carlo-brain@localhost"]
GITIGNORE = ".DS_Store\n.obsidian/workspace*\n.obsidian/cache\n.trash/\n"
CONFLICT_SIGNAL = "sync-conflict.md"


def git(vault: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run git in the vault with prompts disabled. Never raises on a non-zero exit unless check=True."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true"}
    return subprocess.run(["git", *IDENTITY, *args], cwd=str(vault), capture_output=True, text=True,
                          timeout=TIMEOUT, env=env, check=check)


def log(message: str) -> None:
    try:
        path = cfg.state_dir() / "logs" / "sync.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{cfg.now_iso()} {message}\n")
    except OSError:
        pass


def ensure_repo(vault: Path, remote: Optional[str], branch: str) -> None:
    """Create the repository and the `origin` remote when they are missing."""
    if not (vault / ".git").exists():
        git(vault, "init", "-b", branch, check=True)
        if not (vault / ".gitignore").exists():
            (vault / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    if remote and git(vault, "remote", "get-url", "origin").returncode != 0:
        git(vault, "remote", "add", "origin", remote, check=True)


def commit_all(vault: Path) -> bool:
    """Commit every change. True when a commit was made."""
    git(vault, "add", "-A")
    if git(vault, "diff", "--cached", "--quiet").returncode == 0:
        return False
    message = f"sync: {socket.gethostname()} {time.strftime('%Y-%m-%d %H:%M')}"
    return git(vault, "commit", "-m", message).returncode == 0


def merging(vault: Path) -> bool:
    return (vault / ".git" / "MERGE_HEAD").exists()


def signal_conflict(detail: str) -> None:
    cfg.atomic_write(cfg.boot_dir() / CONFLICT_SIGNAL,
                     "Vault sync paused: a pull conflicted and was aborted, nothing was lost or overwritten.\n"
                     f"{detail.strip()[:400]}\nResolve it in the vault (keep both sides, then commit), "
                     "then delete this file. Tell the user in one line.\n")


def clear_conflict() -> None:
    try:
        (cfg.boot_dir() / CONFLICT_SIGNAL).unlink()
    except OSError:
        pass


def has_upstream(vault: Path, branch: str) -> bool:
    return git(vault, "ls-remote", "--exit-code", "--heads", "origin", branch).returncode == 0


def pull(vault: Path, branch: str) -> str:
    """Merge the remote branch. Returns ok, nothing (no remote branch yet) or conflict."""
    if not has_upstream(vault, branch):
        return "nothing"
    result = git(vault, "pull", "--no-rebase", "--no-edit", "origin", branch)
    if result.returncode == 0:
        clear_conflict()
        return "ok"
    if merging(vault):
        git(vault, "merge", "--abort")
    signal_conflict(result.stdout + result.stderr)
    return "conflict"


def push(vault: Path, branch: str) -> str:
    """Push; on rejection merge once and retry. Never forces."""
    if git(vault, "push", "-u", "origin", f"HEAD:{branch}").returncode == 0:
        return "ok"
    if pull(vault, branch) == "conflict":
        return "conflict"
    return "ok" if git(vault, "push", "-u", "origin", f"HEAD:{branch}").returncode == 0 else "failed"


def update_server(server: dict) -> str:
    """Ask the server copy of the vault to fast-forward. Needs working SSH keys (no prompt)."""
    host, path = str(server.get("host", "")), str(server.get("path", ""))
    if not host or not path:
        return "skipped"
    remote_cmd = f"cd {_quote(path)} && git pull --ff-only"
    try:
        result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, remote_cmd],
                                capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return "failed"
    return "ok" if result.returncode == 0 else "failed"


def _quote(value: str) -> str:
    import shlex
    return shlex.quote(value)


def run(mode: str, vault: Optional[Path] = None) -> dict:
    """Do the sync. Returns what happened, for logs and tests."""
    vault = vault or cfg.vault()
    out = {"mode": mode, "committed": False, "pull": "skipped", "push": "skipped", "server": "skipped"}
    if vault is None or not vault.is_dir():
        return {**out, "error": "vault not found"}
    remote = cfg.get("sync.remote") or None
    branch = str(cfg.get("sync.branch") or "main")
    ensure_repo(vault, remote, branch)
    if merging(vault):
        signal_conflict("A merge is already in progress in the vault.")
        return {**out, "pull": "conflict"}
    out["committed"] = commit_all(vault)
    has_remote = git(vault, "remote", "get-url", "origin").returncode == 0
    if has_remote and mode == "start":
        out["pull"] = pull(vault, branch)
    if has_remote and mode == "end":
        out["push"] = push(vault, branch)
        server = cfg.get("sync.server")
        if out["push"] == "ok" and isinstance(server, dict):
            out["server"] = update_server(server)
    return out


def main(argv: list) -> int:
    mode = argv[0] if argv else "start"
    if mode not in ("start", "end") or cfg.is_headless():
        return 0
    if "--detach" in argv:
        subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), mode], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                         env={**os.environ})
        return 0
    try:
        result = run(mode)
        log(str(result))
        cfg.mark_run(f"sync_{mode}")
    except Exception as exc:  # noqa: BLE001 - sync problems must never block a session
        cfg.log_error("sync", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
