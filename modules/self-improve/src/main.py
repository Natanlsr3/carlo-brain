#!/usr/bin/env python3
"""Entry point of the self-improve module. Always run with python3 -I (this file sets its own path).

  main.py apply FILE [--dry-run]   apply one proposal JSON (tier decides: apply, queue for review, refuse)
  main.py undo ID [--force]        restore an applied proposal from its archive
  main.py pending                  process every file in <improvement>/proposals/ (moved to done/ afterwards)
  main.py tick                     start the tasks that are due, including missed ones (cron or launchd calls this)
  main.py run-task NAME            run one task with lock and retries (used by tick)
  main.py job scout|improver       run one LLM job now (use --dry-run to see the command)
  main.py bench [...]              run the personal bench (see `main.py bench --help`)
  main.py status                   print what needs your attention
  main.py boot                     SessionStart hook: catch up missed tasks, apply pending proposals, write the boot note
  main.py init                     create the starter task list and settings if you have none
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from selfimprove import apply as apply_mod  # noqa: E402
from selfimprove import bench, jobs, runner, scheduler, status, undo  # noqa: E402
from selfimprove.settings import Settings, load  # noqa: E402

HERE = Path(__file__).resolve().parent
MAX_PENDING = 10


def cmd_apply(cfg: Settings, args: list) -> int:
    files = [a for a in args if not a.startswith("--")]
    if len(files) != 1:
        print(__doc__)
        return 2
    try:
        proposal = json.loads(Path(files[0]).read_text(encoding="utf-8"))
        entry = apply_mod.process(proposal, cfg, dry_run="--dry-run" in args)
    except (OSError, ValueError) as err:
        print(f"refused: {err}")
        return 1
    print(f"{entry['verdict']} (tier {entry['tier']}): {entry['reason']}")
    return 0 if entry["verdict"] in ("applied", "to review", "dry run") else 1


def cmd_undo(cfg: Settings, args: list) -> int:
    ids = [a for a in args if not a.startswith("--")]
    if len(ids) != 1:
        print(__doc__)
        return 2
    ok, message = undo.undo(ids[0], cfg, force="--force" in args)
    print(message)
    return 0 if ok else 1


def process_pending(cfg: Settings) -> list:
    """Apply or queue each proposal file; processed files move to proposals/done/. Returns summary lines."""
    folder = cfg.proposals
    lines = []
    for path in sorted(folder.glob("*.json"))[:MAX_PENDING] if folder.is_dir() else []:
        try:
            entry = apply_mod.process(json.loads(path.read_text(encoding="utf-8")), cfg)
            lines.append(f"{path.name}: {entry['verdict']} ({entry['tier']})")
        except (OSError, ValueError) as err:
            lines.append(f"{path.name}: refused ({err})")
        done = folder / "done"
        done.mkdir(exist_ok=True)
        shutil.move(str(path), str(done / path.name))  # a proposal is processed once, whatever the verdict
    return lines


def cmd_tick(cfg: Settings) -> list:
    return scheduler.tick(cfg, scheduler.load_tasks(cfg), datetime.now())


def cmd_run_task(cfg: Settings, name: str) -> int:
    tasks = {t["name"]: t for t in scheduler.load_tasks(cfg)}
    if name not in tasks:
        print(f"unknown task: {name}")
        return 78
    task = tasks[name]
    return runner.execute(cfg, name, task["command"], retries=int(task.get("retries", 1)), wait_s=float(task.get("retry_wait_s", 60)))


def cmd_boot(cfg: Settings) -> int:
    """Never raises: a broken config must not break a session. Problems become lines in the boot note."""
    notes: list = []
    tasks: list = []
    try:
        tasks = scheduler.load_tasks(cfg)
        caught = scheduler.tick(cfg, tasks, datetime.now())
    except ValueError as err:
        caught = []
        notes.append(f"Self-improve: task list invalid ({err})")
    try:
        applied = process_pending(cfg)
        caught += [f"proposal {line}" for line in applied]
    except Exception as err:  # noqa: BLE001
        notes.append(f"Self-improve: could not process proposals ({err.__class__.__name__})")
    status.write_boot_file(cfg, notes + status.lines_for_boot(cfg, tasks, caught))
    return 0


def cmd_status(cfg: Settings) -> int:
    try:
        tasks = scheduler.load_tasks(cfg)
    except ValueError as err:
        print(f"task list invalid: {err}")
        tasks = []
    lines = status.lines_for_boot(cfg, tasks, [])
    print("\n".join(lines) if lines else "Nothing needs your attention.")
    for task in tasks:
        state = runner.read_state(cfg, task["name"])
        print(f"- {task['name']}: {state.get('status', 'never ran')}, last success {state.get('last_success', 'never')}")
    return 0


def cmd_init(cfg: Settings) -> int:
    target = cfg.brain_dir / "config.d"
    target.mkdir(parents=True, exist_ok=True)
    for source, name in (("tasks.example.json", "self-improve-tasks.json"), ("settings.example.json", "self-improve.json")):
        destination = target / name
        if destination.exists():
            print(f"kept {destination}")
        else:
            shutil.copyfile(HERE / source, destination)
            print(f"wrote {destination}")
    return 0


def main(argv: list) -> int:
    if not argv:
        print(__doc__)
        return 2
    command, rest = argv[0], argv[1:]
    cfg = load()
    try:
        if command == "apply":
            return cmd_apply(cfg, rest)
        if command == "undo":
            return cmd_undo(cfg, rest)
        if command == "pending":
            print("\n".join(process_pending(cfg)) or "no pending proposals")
            return 0
        if command == "tick":
            print("\n".join(cmd_tick(cfg)))
            return 0
        if command == "run-task" and len(rest) == 1:
            return cmd_run_task(cfg, rest[0])
        if command == "job" and rest and rest[0] in jobs.JOBS:
            return jobs.run_job(rest[0], cfg, os.environ.get("CLAUDE_BIN", "claude"), dry_run="--dry-run" in rest)
        if command == "bench":
            return bench.main(rest, cfg)
        if command == "status":
            return cmd_status(cfg)
        if command == "boot":
            return cmd_boot(cfg)
        if command == "init":
            return cmd_init(cfg)
    except Exception as err:  # noqa: BLE001
        print(f"self-improve {command}: {err}", file=sys.stderr)
        return 0 if command == "boot" else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
