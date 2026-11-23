"""Unattended LLM jobs: the weekly scout (looks outside) and the weekly improver (looks at your own setup).

Design (each point answers a way an unattended agent goes wrong):
- The model gets a private output folder as its working directory and may only write there. Your vault is
  mounted read-only (a deny rule on edits under the vault). A post-step, in code, copies the report into
  the vault and validates every proposal JSON, so the model never writes to your real files.
- Nothing can be sent: every send, create and update tool of the usual connectors is denied.
- Success is judged on the RESULT (a non-empty report exists), not on the exit code.
- API key variables are removed from the environment so the job uses your subscription login.
- The job proposes; `main.py pending` applies or queues proposals later, by tier.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import apply as apply_mod
from .settings import Settings
from .verify import clean_env

# Names of tools that act on other people or other systems. Unattended jobs never get them.
# Exact names depend on the connector: list yours with /mcp and extend this list if needed.
UNATTENDED_DENY: List[str] = [
    "Bash(git push:*)", "Bash(rm:*)", "Bash(curl:*)", "Bash(brew:*)", "Bash(npm install -g:*)",
    "mcp__whatsapp__send_message", "mcp__whatsapp__send_file", "mcp__whatsapp__send_audio_message",
    "mcp__claude_ai_Gmail__send_message", "mcp__claude_ai_Gmail__create_draft",
    "mcp__claude_ai_Google_Calendar__create_event", "mcp__claude_ai_Google_Calendar__update_event",
    "mcp__claude_ai_Google_Calendar__delete_event",
    "mcp__claude_ai_Notion__notion-create-pages", "mcp__claude_ai_Notion__notion-update-page",
    "mcp__claude_ai_Slack__slack_send_message",
]

JOBS: Dict[str, Dict[str, Any]] = {
    "scout": {"prompt": "scout.md", "model": "opus", "tools": "Read,Grep,Glob,Edit(./**),WebSearch,WebFetch,Agent"},
    "improver": {"prompt": "improver.md", "model": "opus", "tools": "Read,Grep,Glob,Edit(./**),Agent"},
}


def login_env(cfg: Settings) -> Dict[str, str]:
    """Clean environment, plus the long-lived subscription login if create_token.sh made one (and only if private)."""
    env = clean_env()
    file = cfg.brain_dir / "keys" / "claude_oauth_token"
    try:
        if file.is_file() and not file.stat().st_mode & 0o077:
            value = file.read_text(encoding="utf-8").strip()
            if value:
                env["CLAUDE_CODE_OAUTH_TOKEN"] = value
    except OSError:
        pass
    return env


def prompts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts"


def build_prompt(job: str, out_dir: Path, cfg: Settings, today: str) -> str:
    """Prompt text with placeholders filled and the automatic-mode footer appended."""
    text = (prompts_dir() / JOBS[job]["prompt"]).read_text(encoding="utf-8")
    vault = str(cfg.vault_path) if cfg.vault_path else "(no vault configured)"
    for key, value in {"{DATE}": today, "{OUT}": str(out_dir), "{VAULT}": vault, "{STATE}": str(cfg.state)}.items():
        text = text.replace(key, value)
    return (text + f"\n\n## Automatic mode (overrides anything above)\nYour working folder is {out_dir}. "
            f"Write ONLY there: the report as REPORT.md and, optionally, proposal files under proposals/. "
            f"Everything else, including the vault, is read-only. You send nothing to anyone.\n")


def command_for(job: str, cfg: Settings, out_dir: Path, claude_bin: str) -> List[str]:
    """The claude command line (prompt goes on stdin)."""
    spec = JOBS[job]
    deny = list(UNATTENDED_DENY)
    cmd = [claude_bin, "-p", "--model", spec["model"], "--permission-mode", "acceptEdits", "--allowedTools", spec["tools"]]
    if cfg.vault_path:
        vault = os.path.realpath(cfg.vault_path)
        cmd += ["--add-dir", vault]
        deny.append(f"Edit(/{vault}/**)")  # "//path" form: absolute path from the filesystem root
    return cmd + ["--disallowedTools", ",".join(deny)]


def with_status_header(report: str, job: str, today: str) -> str:
    """Front matter that marks the report unread (shown at session start until you open it)."""
    if report.startswith("---"):
        return report
    return f"---\ntype: {job}\ndate: {today}\nstatus: unread\n---\n{report}"


def collect_outputs(job: str, out_dir: Path, cfg: Settings, today: str) -> Dict[str, Any]:
    """Post-step in code: validate and copy the report and the proposals into the improvement folder."""
    summary: Dict[str, Any] = {"report": None, "proposals": 0, "rejected": []}
    report = out_dir / "REPORT.md"
    if report.is_file() and report.stat().st_size > 0:
        target = cfg.improvement / "reports" / f"{job.upper()}_{today}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(with_status_header(report.read_text(encoding="utf-8"), job, today), encoding="utf-8")
        summary["report"] = target
    for path in sorted((out_dir / "proposals").glob("*.json")) if (out_dir / "proposals").is_dir() else []:
        try:
            apply_mod.validate(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError) as err:
            summary["rejected"].append(f"{path.name}: {err}")
            continue
        cfg.proposals.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, cfg.proposals / path.name)
        summary["proposals"] += 1
    return summary


def run_job(job: str, cfg: Settings, claude_bin: str = "claude", today: Optional[str] = None,
            runner: Callable[..., Any] = subprocess.run, dry_run: bool = False) -> int:
    """Run one job. Returns 0 when a report was produced, 1 otherwise (127 when claude is missing)."""
    if job not in JOBS:
        raise ValueError(f"unknown job: {job} (choose {', '.join(JOBS)})")
    today = today or datetime.now().strftime("%Y-%m-%d")
    out_dir = cfg.state / "jobs" / job / today
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    prompt = build_prompt(job, out_dir, cfg, today)
    cmd = command_for(job, cfg, out_dir, claude_bin)
    if dry_run:
        print(f"DRY RUN: {job}, prompt {len(prompt)} chars, output {out_dir}\n{' '.join(cmd[:8])} ...")
        return 0
    if shutil.which(claude_bin) is None and not Path(claude_bin).exists():
        print(f"claude not found: {claude_bin}")
        return 127
    log = cfg.state / "logs" / f"{job}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        res = runner(cmd, input=prompt, capture_output=True, text=True, cwd=out_dir, env=login_env(cfg), timeout=3 * 3600)
    except (OSError, subprocess.TimeoutExpired) as err:
        print(f"{job}: could not run ({err.__class__.__name__})")
        return 1
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"=== {datetime.now():%F %T} {job} exit {res.returncode}\n{(res.stdout or '')[-2000:]}{(res.stderr or '')[-1000:]}\n")
    summary = collect_outputs(job, out_dir, cfg, today)
    for rejected in summary["rejected"]:
        print(f"{job}: proposal rejected, {rejected}")
    if summary["report"] is None:  # judge the result, not the exit code
        print(f"{job}: no report produced (claude exit {res.returncode}); see {log}")
        return 1
    print(f"{job}: report {summary['report']}, {summary['proposals']} proposal(s) queued")
    return 0
