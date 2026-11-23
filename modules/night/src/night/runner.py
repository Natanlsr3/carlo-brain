"""Run night tasks step by step. One `claude -p` process per step, judged on its STATUS line.

Each step is a fresh process, so a long task is split into steps that each fit in one session and hand
over through notes the task writes in its working folder. The queue is processed in order; a task stops at
its first step that is not `done`, so the morning report says exactly where to resume.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from . import report, statusline, tasks
from .config import Settings
from .power import minutes

SENSITIVE_ENV = re.compile(r"(API_KEY|_KEY$|SECRET|PASSWORD|PASSWD)", re.IGNORECASE)
KEEP_ENV = {"CLAUDE_CODE_OAUTH_TOKEN"}
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class TaskResult:
    name: str
    title: str
    steps_done: int
    steps_total: int
    state: str      # finished | partial | blocked | not_started
    reason: str


def prompts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts"


def login_env(cfg: Settings) -> Dict[str, str]:
    """Environment without key-like variables (a background job must not bill an API key by accident),
    plus the long-lived subscription login when a private token file exists."""
    env = {k: v for k, v in os.environ.items() if k in KEEP_ENV or not SENSITIVE_ENV.search(k)}
    token_file = cfg.brain / "keys" / "claude_oauth_token"
    try:
        if token_file.is_file() and not token_file.stat().st_mode & 0o077:
            value = token_file.read_text(encoding="utf-8").strip()
            if value:
                env["CLAUDE_CODE_OAUTH_TOKEN"] = value
    except OSError:
        pass
    return env


def build_command(cfg: Settings, model: str, allowed: str, denied: List[str], add_dirs: List[str]) -> List[str]:
    """The claude command line (prompt on stdin), wrapped in caffeinate on macOS when asked."""
    cmd = [cfg.values["claude_bin"], "-p", "--model", model, "--permission-mode", "acceptEdits"]
    for folder in add_dirs:
        cmd += ["--add-dir", folder]
    cmd += ["--allowedTools", allowed, "--disallowedTools", ",".join(denied)]
    if cfg.values["keep_awake"] and sys.platform == "darwin" and shutil.which("caffeinate"):
        cmd = ["caffeinate", "-i", "-s"] + cmd
    return cmd


def run_claude(cfg: Settings, prompt: str, model: str, allowed: str, denied: List[str], add_dirs: List[str],
               cwd: Path, timeout: int, runner: Runner = subprocess.run) -> Tuple[int, str]:
    """Run one claude process. Returns (exit code, output). A timeout is exit code 124."""
    cmd = build_command(cfg, model, allowed, denied, add_dirs)
    try:
        res = runner(cmd, input=prompt, capture_output=True, text=True, cwd=cwd, env=login_env(cfg), timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"
    except OSError as err:
        return 127, f"cannot start: {err}"
    return res.returncode, (res.stdout or "") + (res.stderr or "")


def rules_text() -> str:
    return (prompts_dir() / "rules.md").read_text(encoding="utf-8")


def step_prompt(task: tasks.Task, step: int, today: str) -> str:
    """Task prompt with {STEP} {STEPS} {DATE} {WORKDIR} filled, then the standing rules and the STATUS instruction."""
    text = (task.path / "prompt.md").read_text(encoding="utf-8")
    for key, value in {"{STEP}": str(step), "{STEPS}": str(task.steps), "{DATE}": today, "{WORKDIR}": str(task.workdir)}.items():
        text = text.replace(key, value)
    return f"{text}\n\n{rules_text()}\n\n{statusline.INSTRUCTION}\n"


def too_late(now: datetime, cfg: Settings) -> bool:
    """True in the morning after `last_step_before` (and before the evening window): start nothing new."""
    here = now.hour * 60 + now.minute
    return minutes(cfg.values["last_step_before"]) <= here < minutes(cfg.values["window"]["start"])


def log_to(cfg: Settings, name: str, step: int, code: int, output: str) -> None:
    cfg.logs.mkdir(parents=True, exist_ok=True)
    with (cfg.logs / f"{name}.log").open("a", encoding="utf-8") as handle:
        handle.write(f"=== {datetime.now():%F %T} step {step} exit {code}\n{output}\n")


def run_task(cfg: Settings, task: tasks.Task, now_fn: Callable[[], datetime] = datetime.now, runner: Runner = subprocess.run,
             respect_clock: bool = True) -> TaskResult:
    """Run the remaining steps of one task. `respect_clock=False` ignores the morning stop (manual run)."""
    done = task.steps_done
    if done >= task.steps:
        return TaskResult(task.name, task.title, done, task.steps, "finished", "already complete")
    problems = tasks.check(task.path, cfg)
    if problems:
        return TaskResult(task.name, task.title, done, task.steps, "blocked", "; ".join(problems))
    denied = cfg.denied(list(task.denied_tools))
    while done < task.steps:
        now = now_fn()
        if respect_clock and too_late(now, cfg):
            return TaskResult(task.name, task.title, done, task.steps, "partial", f"stopped at {now:%H:%M}: no new step after {cfg.values['last_step_before']}")
        step = done + 1
        code, output = run_claude(cfg, step_prompt(task, step, now.strftime("%Y-%m-%d")), task.model, task.allowed_tools,
                                  denied, list(task.add_dirs), task.workdir, cfg.values["step_max_s"], runner)
        log_to(cfg, task.name, step, code, output)
        status, reason = statusline.read(output)
        if statusline.hit_limit(output) and status != "done":
            return TaskResult(task.name, task.title, done, task.steps, "partial", f"step {step}: usage limit reached, resume tomorrow night")
        if code != 0:
            return TaskResult(task.name, task.title, done, task.steps, "partial", f"step {step} ended with exit code {code} ({reason})")
        if status != "done":  # judge the result the agent reports, not the exit code
            return TaskResult(task.name, task.title, done, task.steps, "partial", f"step {step} not finished ({status}: {reason})")
        done = step
        (task.path / "steps_done").write_text(str(done))
    return TaskResult(task.name, task.title, done, task.steps, "finished", f"{task.steps}/{task.steps} steps done")


def run_queue(cfg: Settings, now_fn: Callable[[], datetime] = datetime.now, runner: Runner = subprocess.run,
              respect_clock: bool = True) -> List[TaskResult]:
    """Run every task of the queue in order, move finished ones to done/, write the report."""
    results: List[TaskResult] = []
    for path in tasks.discover(cfg):
        try:
            task = tasks.load_task(path, cfg)
        except ValueError as err:
            results.append(TaskResult(path.name, path.name, 0, 0, "blocked", str(err)))
            continue
        result = run_task(cfg, task, now_fn, runner, respect_clock)
        results.append(result)
        if result.state == "finished":
            cfg.done.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(cfg.done / f"{path.name}_{now_fn():%Y-%m-%d}"))
    report.write(cfg, results, now_fn())
    return results
