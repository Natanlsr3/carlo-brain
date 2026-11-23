# 8. Costs and limits

## What costs nothing

These run locally, with no model call and no key:

- **memory** boot injection, log entry, compaction summary, health line, quality score. (Fact extraction is the exception, see below.)
- **security**: all hooks are pattern matching.
- **sync**: git.
- **proactive**: the scan, the scoring and the briefing. By design it uses no LLM. Voice uses the system's own `say`, `spd-say` or `espeak`.
- **connectors**: the Apple readers, vault MCP and the guides.

The cost of the hooks themselves is a few milliseconds per event plus the injected context: the boot context is hard capped at 9,000 characters, and your `SYSTEM_PROMPT.md` plus `MAP.md` are loaded in full every session. Keep both lean: every line is paid for at every session start.

## What uses your Claude subscription

All background model calls run `claude -p` with API key variables removed from the environment, so they count against your subscription's usage, not an API account. (If a key variable were present, `claude -p` would use it and bill that account, which is exactly why they are stripped. `triage_pass.sh` has an explicit opt-out, `CARLO_KEEP_API_KEYS=1`; leave it unset unless you want to be billed.)

| Feature | When | Size, qualitatively |
|---|---|---|
| Fact extraction (memory) | end of each session, background, `--model haiku` | one short call per session; turn off with `carlo config set memory.extract_facts false` |
| Weekly scout | Saturday 09:00 | many parallel sub-agents sweeping the web: the heaviest regular job |
| Weekly improver | Sunday 09:00 | audits your setup, tests ideas on a copy: medium |
| Bench | by hand, or as a proposal's test | a handful of short conversations plus one judge call per case |
| Night task step | each night step | one `claude -p` per step, up to `step_max_s` (default 10800 seconds) |
| Marathon (optional) | all night | can use a large share of your weekly quota; set `max_passes` with that in mind |
| Weekly triage (optional, proactive) | twice a week if you schedule it | one pass over the full message dump |
| Telegram bridge | each message you send | one `claude -p` per message |

Advice that keeps it cheap:

- The night default model is `opus` (`default_model` in `config.d/night.json`). Create tasks with `--model sonnet` and two or three steps at first, or change the default: an opus night can be expensive.
- Run `job scout --dry-run` first: it prints the command and spends nothing.
- Leave the marathon off until you have seen a normal night.
- The scheduled jobs are weekly. Do not add a daily LLM job without a reason.
- There is no budget cap in the code. The usage limit of your plan is the cap; a night marathon that hits it pauses ten minutes and retries instead of failing.

## Limits of the system

**Platform**
- macOS and Linux only. Windows is not supported.
- Scheduled jobs use launchd on macOS. On Linux the CLI prints a cron line you add yourself.
- Apple connectors (Contacts, Messages, Notes, Reminders, Calendar, Mail) are macOS only, and need Full Disk Access.
- launchd jobs cannot read `~/Desktop` or `~/Documents` without extra permissions. Keep the vault, the night work folders and anything a scheduled job needs elsewhere, for example in your home folder.
- The scheduler runs while you are logged in. It does not wake a sleeping machine. `caffeinate` keeps a Mac awake during a night step, but closing the lid still sleeps it unless you use clamshell mode.
- The night trigger wants mains power; when it cannot tell, it does not block.

**Context**
- The boot injection is capped at 9,000 characters (Claude Code truncates around 10,000); each log entry is cut at 1,500 and each signal at 1,500. When the cap bites, a line says how many sections were omitted.
- Compaction loses detail by nature. The PreCompact hook saves a mechanical summary (last messages, changed files, git commands, decisions); the next boot points to it.

**Quality**
- The automatic log entry is deliberately minimal. A real entry written by the assistant is better.
- The session quality score is a heuristic on English phrasing: a trend, not a grade.
- Keyword defaults in `proactive` are English. Add your language through `extra_keywords` and `keywords`.
- Fact extraction quality depends on the model, which is why nothing is trusted before you validate it.
- Apple's private database layouts (Mail index, Messages, Notes, Calendar) can change with any macOS release. The tools fail loudly with a reason; they do not return an empty result.
- The WhatsApp bridge is unofficial and the link expires after about 20 days without the bridge running.

**Autonomy**
- `auto` tier edits are only as safe as their checks. Keep tests next to your scripts and keep the bench references fresh.
- Unattended editing is only as safe as the tools you grant. Prefer read tools plus writes in the task's own folder.

## Beta status, per module

All modules are version 0.1. The READMEs say beta for `proactive`, `connectors` (as a whole), `self-improve`, `night`, `agents-skills`, `health` and `search`; the server setup, the Telegram bridge and the vault MCP are called out as beta inside `connectors`. `memory`, `security` and `sync` are tested end to end in a temporary HOME but are young: back up `~/.claude/settings.json` before your first install (the installer also does, with a timestamp).
