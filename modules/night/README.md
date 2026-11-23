# night

Work that happens while you sleep, with a report when you wake up. You put multi-step tasks in a
queue; when it is dark, you are home and the laptop is plugged in, the assistant works through
them one step at a time, and your next session opens with what was done, what was not, and where to resume.

Status: **beta**. The queue, step logic, STATUS judging, trigger conditions, marathon and report are covered
by tests with a fake `claude`. A real night with a real model has not been run by the automated tests, and
`check_under_launchd.sh` (which reproduces the launchd conditions) only had its syntax checked.

## Why

Overnight is free capacity, but unattended runs fail in quiet ways. This module is built around the lessons:

- **Judge the result, not the exit code.** A step is done only when the agent's last line says `STATUS: done - reason`. Exit code 0 without that line is "not finished" (a step once counted as done without being done).
- **The morning must say what happened.** One line per task: done, to finish (and at which step), or not started with the reason. Never an empty silence.
- **Do not start what you cannot finish properly**: no new step after a morning limit; one step has a time cap.
- **Be home first.** The night starts only inside a time window, once per evening, on mains power (a laptop that dies at 3 am helps nobody).
- **Test in the conditions of the night.** A task that works in your terminal can fail under launchd (protected folders, expired login). The pre-flight check refuses protected folders on macOS, and `check_under_launchd.sh` runs the check as a real launchd job.
- **Nothing leaves your machine.** Every send, create and update tool of the usual connectors is denied; a standing rules block is appended to every prompt (drafts in files only, nothing deleted, secrets never read, invent nothing).

## Setup

```
carlo add night
python3 -I ~/.carlo-brain/night/main.py add 01_digest --prompt-file my_prompt.md --steps 3 --model sonnet   # --model is optional (default: sonnet)
python3 -I ~/.carlo-brain/night/main.py check
```

Install creates `~/.carlo-brain/data/night/queue/` (outside the code folder: upgrading the module never
touches your tasks), starts nothing, and leaves an example in `~/.carlo-brain/night/example_task/`.
A scheduler job runs `main.py trigger` every 10 minutes (launchd; the CLI prints a cron line on Linux).
The SessionStart hook shows an unread report once.

Unattended runs need a login that does not expire overnight: run `self-improve/create_token.sh` once
(the `self-improve` module explains it, including a limit that matters here: that token cannot use
claude.ai connectors such as Gmail or Calendar; locally configured MCP servers still work, so a night task that must
read mail needs the normal login to be valid, or a local mail reader such as the Apple Mail reader of the
`proactive` module).

## A task

A folder in the queue: `<NN_name>/task.json` and `prompt.md`. Folders run in name order.

```json
{"title": "Weekly research digest", "steps": 3, "model": "sonnet",
 "allowed_tools": "Read,Grep,Glob,Edit,Write,WebSearch,WebFetch",
 "add_dirs": [], "denied_tools": [], "workdir": "~/night-work/digest"}
```

- `steps` (1 to 50): each step is a separate `claude -p` process, so a long task fits in several sessions and hands over through notes the task keeps in its working folder. Your prompt uses `{STEP}`, `{STEPS}`, `{DATE}`, `{WORKDIR}`.
- `workdir` (default `<task>/work`): the folder the task works in. `add_dirs`: extra folders it may read.
- `allowed_tools`: bare `Bash` is refused; list commands, for example `Bash(git status:*)`.
- `denied_tools`: added to the built-in deny list (sends, deletions, pushes, installs).
- Progress is stored in `steps_done`; a task that stops resumes at the next step the following night. A finished task moves to `done/<name>_<date>`.

The example prompt shows the pattern (`example_task/`): read the notes first, do only this step, leave a line in
the notes. `main.py list` shows progress; `main.py check` runs the pre-flight on all tasks.

## The nightly trigger

`main.py trigger` starts the night when all of these hold: something is queued (or the marathon has open items),
now is inside the window (default 20:30 to 06:00, wrapping midnight), tonight has not run yet, and the machine is on
mains power (when it cannot tell, it does not block). The "launched tonight" marker is written **before** the run, so a
crash cannot loop. A battery wait is logged in `state/night/logs/trigger.log` and retried on the next tick.
`main.py trigger --force` ignores window, marker, power and the morning limit (for a manual run).

## The marathon (optional, heavy)

For a night-long stream of tasks: you keep a checklist `data/night/marathon/BACKLOG.md` (order = priority), the
agent works pass after pass, ticks items, and logs its reasoning in `JOURNAL.md`, including why it put one task
before another. Each pass is a fresh process that starts by reading both files. It stops at the deadline
(default 09:15), after `max_passes` (40), when the backlog is empty, or after 5 failed passes in a row; hitting the usage
limit pauses 10 minutes instead of failing. The prompt (`marathon/prompt.md`, created on first run, yours to edit)
asks it to weigh value against cost and to review its own output with a sub-agent before ticking.
Enable it in `config.d/night.json`: `{"marathon": {"enabled": true}}`. It can use a large share of your weekly
quota: set `max_passes` with that in mind. `main.py marathon` runs it now.

## Customize

`~/.carlo-brain/config.d/night.json`:

```json
{"window": {"start": "22:00", "end": "07:00"}, "last_step_before": "08:30", "require_ac": true,
 "step_max_s": 10800, "default_model": "sonnet", "keep_awake": true,
 "extra_denied_tools": ["mcp__my_server__delete_thing"],
 "marathon": {"enabled": false, "end": "09:15", "max_passes": 40, "model": "opus"}}
```

The deny list names tools by connector (`mcp__whatsapp__send_message`, `mcp__claude_ai_Gmail__send_message`, ...); tool
names come from your connectors, so check `/mcp` and add yours to `extra_denied_tools`. The standing rules every prompt gets are in
`prompts/rules.md`.

## Check a task under launchd (macOS)

```
bash ~/.carlo-brain/night/check_under_launchd.sh 01_digest            # pre-flight, run by launchd
bash ~/.carlo-brain/night/check_under_launchd.sh 01_digest --claude   # also a tiny real claude write test
```

## Known limits

- Time zones and daylight saving: the window uses local time and is evaluated on each tick.
- `caffeinate` keeps a Mac awake during a step; closing the lid still sleeps it unless you use clamshell mode.
- Quota: a `--model opus` night can be expensive on a subscription. The default is `sonnet`; start with 2 or 3 steps.
- Linux: works (cron instead of launchd, mains detection through `/sys/class/power_supply`); the protected-folder check applies only to macOS.
- Unattended editing is only as safe as the allowed tools you grant. Prefer read tools plus writes in the task's own folder.
