# self-improve

Your assistant gets better by itself without being able to hurt itself or you.
Two weekly jobs look for improvements (one outside, one in your own setup). They only **propose**.
Code, not the model, decides what happens to each proposal: apply it safely, queue it for your
review, or refuse it. Everything applied can be undone.

Status: **beta**. The loop (tiers, backup, checks, restore, undo), the bench, the scheduler and the
job post-processing are covered by tests using a fake `claude` (no model is ever called in tests). The
prompts and the way real `claude -p` handles the permission rules have not been exercised at scale.

## Why

Most setups measure a lot and change nothing: reports pile up unread, proposals wait for a human
who has no time. The opposite failure is worse: an unattended agent that rewrites its own rules, breaks
something and cannot go back. This module closes the loop with three guarantees:

1. **The table decides, not the model.** Every file belongs to a tier by its path: `auto`, `review` or `manual`. The most restrictive tier in a proposal applies to the whole proposal.
2. **Backup, check, real restore.** An automatic change is archived first, written, verified (syntax, front matter, links, the neighbouring tests, your test command), and put back byte for byte if a single check fails.
3. **Failures are visible.** A task that failed, a proposal waiting for review, an unread report: all appear in the first lines of your next session. Nothing fails silently.

## What is in it

| Piece | What it does |
|---|---|
| `main.py apply / undo / pending` | the loop: apply a proposal JSON by tier, undo it, process the queue |
| `main.py job scout` / `job improver` | the two weekly LLM jobs (prompts in `prompts/`), confined, report plus proposals |
| `main.py tick` | a small scheduler with catch-up: runs weekly tasks, including the ones missed while the machine slept |
| runner | lock per task, retries with a growing wait, state file, honest failure status |
| `main.py bench` | a personal bench: your rules as test cases, scored by regex checks and a different judge model |
| `main.py boot` | session start hook: catch up, apply pending proposals, write a short note (failures, reviews, reports) |
| `create_token.sh`, `auth_env.sh` | a long-lived login so scheduled jobs can use your subscription |

## Setup

```
carlo add self-improve
python3 -I ~/.carlo-brain/self-improve/main.py status
python3 -I ~/.carlo-brain/self-improve/main.py job scout --dry-run     # shows the command, spends nothing
```

Install creates `~/.carlo-brain/config.d/self-improve-tasks.json` (the two weekly jobs: the scout on
Saturday 09:00, the improver on Sunday 09:00, both catching up within 72 hours) and
`~/.carlo-brain/config.d/self-improve.json` (tiers and verification settings). It never overwrites
your files.

**Make unattended runs able to log in.** Scheduled jobs cannot open a browser, and an ordinary login can
expire overnight. Run `bash ~/.carlo-brain/self-improve/create_token.sh` once: it calls
`claude setup-token`, you paste the token, it is saved with mode 600. Facts from Claude Code's
documentation: the token authenticates with your subscription, lasts one year, and **can only make model
requests, so it cannot reach claude.ai connectors (Gmail, Calendar, Drive) nor start Remote Control**.
That is fine for these jobs (they read files and the web). Locally configured MCP servers still work.
Jobs strip every API key variable from their environment, because `claude -p` uses an
`ANTHROPIC_API_KEY` whenever one is present, which would bill an API account instead of your subscription.

## The tiers

| Tier | Default paths | What happens |
|---|---|---|
| `auto` | assistant memory and skills in the vault, `~/.claude/agents`, `~/.claude/skills`, JSON files in `~/.carlo-brain/config.d` | applied with backup and checks, restored on failure, journaled |
| `review` | `SYSTEM_PROMPT.md`, `MAP.md` and other top level files of `00_System`, `~/.claude/CLAUDE.md`, `settings.json`, anything whose name suggests sending (mail, whatsapp, slack, telegram, send) | nothing changes; a "current line / proposed line" diff is written to `00_System/improvement/to_review/<id>.md` |
| `manual` | keys, the `security` module, this module's own code and config, `~/.ssh`, core config, Telegram and vault MCP settings, any file whose name contains secret, token, password, `.env`, key, credential | refused and journaled |
| unknown path | everything else | treated as `review` |

Symlinks are resolved first, so a link cannot smuggle a protected file into a looser tier. The `manual`
list is built into the code: your config file can add rules to `auto` and `review`, but it cannot lower the
protected paths (a proposal that edits the config would otherwise be able to unlock itself). The bench
cases live under `manual` too: an automatic change must never be able to edit the judge.

Customize in `~/.carlo-brain/config.d/self-improve.json`:

```json
{"tiers": {"auto": ["{VAULT}/00_System/skills/**"], "review": ["{VAULT}/00_System/*.md"]},
 "verify": {"forbidden_in_markdown": ["\u2014"], "test_timeout_s": 60}}
```

`forbidden_in_markdown` lists characters that must not appear in lines a proposal adds to a `.md` file
(for example a typographic dash if your style forbids it). Empty by default.

## A proposal

```json
{"id": "2026-03-01-agent-rule", "title": "Add a rule to the researcher agent", "reason": "came up twice in corrections",
 "source": "reports/IMPROVER_2026-03-01.md",
 "changes": [
   {"file": "~/.claude/agents/researcher.md", "old": "exact text, present exactly once", "new": "replacement text"},
   {"file": "~/vault/00_System/skills/new-skill.md", "content": "whole file"}],
 "test_command": "python3 /path/to/check.py"}
```

- `old` must occur exactly once in the file, otherwise nothing is written. `content` replaces or creates the whole file.
- `test_command` is optional: run without a shell, without API keys, 60 second default timeout.
- Checks by type: `.md` front matter, broken links added to a `MEMORY.md` index, your forbidden characters; `.py` compile plus the `test_*.py` next to it; `.sh` `bash -n`; `.json` and `.toml` parse.
- An id can be used once: reusing it is refused, so the archive of an id always matches one change.

```
python3 -I ~/.carlo-brain/self-improve/main.py apply proposal.json --dry-run   # writes nothing, not even the journal
python3 -I ~/.carlo-brain/self-improve/main.py apply proposal.json
python3 -I ~/.carlo-brain/self-improve/main.py undo <id> [--force]
```

`undo` refuses if you edited the file since the change (use `--force` to override). The journal is
`state/self-improve/journal.jsonl`, with a readable newest-first view in `00_System/improvement/CHANGELOG.md`
of your vault (or the state folder if you have no vault). Backups are in `state/self-improve/archives/<id>/`.

## The weekly jobs

- **scout** (outside): reads your map, system prompt, recent session log and previous reports, then sweeps forums, code hosting, practitioners' write-ups and the official documentation with parallel sub-agents, and keeps three to six findings with evidence.
- **improver** (inside): audits your session log, corrections, memory, change log, bench results and the module state; checks for mechanisms nobody uses any more; **tests ideas on a copy before proposing them**; writes at most three housekeeping proposals.

How they are confined:

- The model's working folder is a private output folder; it may only edit inside it. Your vault is mounted read-only (a deny rule on edits under the vault path). A post-step **in code** copies `REPORT.md` into `00_System/improvement/reports/` (with `status: unread` front matter) and validates every proposal JSON before it enters the queue; invalid ones are reported and dropped.
- Every send, create and update tool of the usual connectors is denied (WhatsApp send, mail send and draft, calendar writes, Notion writes, Slack posts). The list is `UNATTENDED_DENY` in `src/selfimprove/jobs.py`; tool names depend on your connectors (check `/mcp`), extend the list for yours.
- Success is judged on the result: no report means failure, whatever the exit code.
- At the next session start (`boot`), queued proposals are processed: `auto` ones are applied, `review` ones become diffs for you, `manual` ones are refused. Each file moves to `proposals/done/` once processed.

Run a job by hand: `python3 -I ~/.carlo-brain/self-improve/main.py job improver`. Change the schedule or add your own jobs in `self-improve-tasks.json` (`days`, `time`, `window_h`, `catch_up`, `retries`).

## The scheduler (catch-up)

`tick` runs every 30 minutes (launchd on macOS; the CLI prints a cron line on Linux). For each task it
compares the latest scheduled slot with the last slot already launched. A laptop that slept through
Sunday 09:00 runs the task when it wakes, within `window_h`. The slot is marked launched **before** the task
starts, so it can never run twice; a lock stops two copies; failures are retried a bounded number of
times with a growing wait, except definitive ones (exit 126, 127, 78). Outcome per task is in
`state/self-improve/tasks/<name>.json` and a failure shows up at the next session start.

## The bench

Your rules as test cases. `main.py bench` runs each case through `claude -p` with tools disabled, using your
normal configuration (your CLAUDE.md and rules: the point is to measure the assistant you really use), then
scores:

- **mechanical checks** (regex): the ones in `_common.json` apply to every case (no tables, no emoji by default), plus each case's `forbidden` and `required` patterns;
- **yes/no criteria** answered by a judge model that is **different** from the tested one (the case is an error if they are the same). A judge that fails gives "not judged", never a default score.

```
python3 -I ~/.carlo-brain/self-improve/main.py bench --reference   # all cases, records the baseline
python3 -I ~/.carlo-brain/self-improve/main.py bench --quick       # cases marked quick; exit 0 no drop, 1 drop, 2 undecidable
python3 -I ~/.carlo-brain/self-improve/main.py bench --compare old.json new.json
```

`--quick` is meant as a proposal's `test_command` when a change touches an agent or a skill: it takes
three cases in parallel and refuses by caution when the result cannot be compared (no reference, a case in
error). Six example cases ship in `bench/cases/` (short answers, no invented facts in outgoing text, show then
send on go, never print secret files, end with one action, ask before an ambiguous irreversible action),
written to match the default system prompt. **Replace them with cases from your own corrections**: that is
what makes the bench yours. Results are in `state/self-improve/bench/`. A full run is a handful of short
conversations plus one judge call per case; with a subscription it counts against your usage.

## Customize

- Tiers and checks: `config.d/self-improve.json`. Jobs and schedules: `config.d/self-improve-tasks.json`. Prompts: `prompts/scout.md`, `prompts/improver.md` (edit them to your interests; they are copied from the module on upgrade, so keep your edits in a copy and point a task at it).
- Bench cases: JSON files in `bench/cases/` (`id`, `quick`, `prompt`, `rules`, `mechanical.forbidden/required`, `llm_criteria`).

## Known limits

- The deny rule for the vault and the allow rule for the output folder use Claude Code's permission rule syntax (`Edit(//absolute/path/**)`, `Edit(./**)`), documented by Anthropic; `Write` rules are expressed as `Edit` rules. If a future release changes the syntax the job fails visibly (no report), it does not fail open. Check with a dry run and one real run before you leave it unattended.
- The model can still read anything Claude Code lets it read; the secret-file guards of the `security` module and `UNATTENDED_DENY` are your protection, not this module.
- The scheduler runs while you are logged in (launchd user agent). It does not wake a sleeping machine.
- `auto` tier edits are only as safe as their checks. Keep the tests of your scripts next to them and the bench references fresh.
- Design notes and what was deliberately not copied from other projects: `DESIGN.md`.
