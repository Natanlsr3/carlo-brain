# review-loop

Makes the review systematic: when a session changed code, Claude is asked to run the `reviewer` agent on it before it says the work is done.

Status: **beta**. The hooks are tested against a real temporary git repository; whether the reviewer finds anything useful is up to the reviewer.

## Why

The `reviewer` agent only runs when you or the main assistant remember to call it. This module remembers for you, with no model call of its own: it is a few milliseconds of git at the end of a turn.

## How it works

- `SessionStart` records the code diff that already exists, so uncommitted work from before the session does not count.
- `Stop` compares the current diff (code files only, against `HEAD`, new untracked code files included) with that baseline. If it changed, is at least `min_lines` lines, and this exact diff was not asked about yet, the stop is blocked once with a short message listing the files. Claude then runs the reviewer and answers.
- It cannot loop: `stop_hook_active` is honoured, each diff hash is asked about once, and a session gets at most `max_per_session` reminders. State is in `~/.carlo-brain/state/review-loop/<session>.json`.
- The reviewer is read only and cannot run git, so the reminder gives Claude the paths to pass on.
- Skipped in background jobs (`CARLO_HEADLESS=1`) and outside a git repository.

## Setup

```bash
carlo add agents-skills review-loop      # the reviewer agent, then the hooks
carlo config set review_loop.enabled false      # turn it off, back on with true
carlo config set review_loop.max_per_session 3  # default 2
carlo config set review_loop.min_lines 20       # default 5 changed lines of code
```

## Limits

- Git only: no repo, no review reminder. Files outside git or ignored by it are not seen.
- It reminds, it does not force: Claude can still answer "trivial change" in one line.
- It sits next to the `security` Stop guard (tests after code changes); both can fire on the same stop, one reminder each.
