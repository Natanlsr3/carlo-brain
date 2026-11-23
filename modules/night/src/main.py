#!/usr/bin/env python3
"""Entry point of the night module. Always run with python3 -I (this file sets its own path).

  main.py add NAME --prompt-file FILE [--steps N] [--model M]   put a task in the queue
  main.py list                                                 the queue and each task's progress
  main.py check [NAME]                                         pre-flight check (nothing is executed)
  main.py trigger [--force]                                    start the night if conditions are met (scheduler calls this)
  main.py marathon                                             run the marathon now (needs marathon.enabled)
  main.py report                                                print the last report
  main.py boot                                                 SessionStart hook: show an unread report once
Task folder: ~/.carlo-brain/data/night/queue/<NN_name>/{task.json, prompt.md}; see the README.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from night import report, marathon, tasks, trigger  # noqa: E402
from night.config import load  # noqa: E402


def arg(args: list, flag: str, default=None):
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else default


def main(argv: list) -> int:
    if not argv:
        print(__doc__)
        return 2
    command, rest = argv[0], argv[1:]
    try:
        cfg = load()
        if command == "add":
            name, prompt_file = (rest[0] if rest else ""), arg(rest, "--prompt-file")
            if not name or not prompt_file:
                print(__doc__)
                return 2
            path = tasks.create(cfg, name, Path(prompt_file).read_text(encoding="utf-8"), int(arg(rest, "--steps", 1)), arg(rest, "--model"))
            problems = tasks.check(path, cfg)
            print(f"created {path}" + (f"\nproblems to fix before tonight: {'; '.join(problems)}" if problems else "\npre-flight check passed"))
            return 0 if not problems else 1
        if command == "list":
            for path in tasks.discover(cfg):
                try:
                    task = tasks.load_task(path, cfg)
                    print(f"{task.name}: {task.steps_done}/{task.steps} steps, model {task.model}, {task.title}")
                except ValueError as err:
                    print(f"{path.name}: invalid ({err})")
            return 0
        if command == "check":
            paths = [cfg.queue / rest[0]] if rest else tasks.discover(cfg)
            bad = 0
            for path in paths:
                problems = tasks.check(path, cfg)
                bad += bool(problems)
                print(f"{path.name}: " + ("ok" if not problems else "; ".join(problems)))
            return 1 if bad else 0
        if command == "trigger":
            lines = trigger.trigger(cfg, force="--force" in rest)
            print("\n".join(lines))
            return 0
        if command == "marathon":
            if not cfg.values["marathon"]["enabled"]:
                print("marathon is disabled: set marathon.enabled in config.d/night.json")
                return 1
            outcome = marathon.run_marathon(cfg, respect_deadline=False)
            print(f"{outcome.passes} pass(es), {outcome.ok} done, {outcome.failed} not done. Stopped: {outcome.reason}")
            return 0
        if command == "report":
            path = cfg.state / "REPORT.md"
            print(path.read_text(encoding="utf-8") if path.exists() else "no report yet")
            return 0
        if command == "boot":
            report.boot_note(cfg)
            return 0
    except Exception as err:  # noqa: BLE001 - a broken config must never break a session
        print(f"night {command}: {err}", file=sys.stderr)
        return 0 if command == "boot" else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
