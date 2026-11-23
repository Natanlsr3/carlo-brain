# health

A watchdog for the things that run without you. It checks that each scheduled job ran within its expected
interval and that each connector still works, tells your next session **only when something is broken**, and
relaunches a missed job once (like anacron), and repairs what it safely can (a playbook of known failures and
their fixes). What only you can do arrives as one line in your next session. `carlo doctor` shows the same status.

Status: **beta**. Every check and every repair is covered by tests with a temporary home, fake clocks, fake launchers and a
fake `claude`. It has not been run against a long-lived real setup, and the MCP check parses the text output of
`claude mcp list`, which may change between Claude Code versions.

## Why

Scheduled work fails quietly: a laptop asleep at the slot, an expired login, a database that lost its
permission. Nobody notices until the briefing or the report has been missing for two weeks. The note says
"scout: last run 11 days ago, threshold 8 days", in the first lines of the next session, and disappears when the job is back.

## Setup

```bash
carlo add health        # needs the memory module (the note travels through state/boot.d/)
carlo doctor            # now includes the jobs and connectors
carlo health status     # repair switch, recent repairs, what waits on you (changes nothing)
carlo health repair --dry-run   # what the playbook would do now
carlo health repair     # run it now (the hook and the 6 hourly job run it for you)
carlo health check      # same status as doctor, without the rest of doctor
carlo health catchup --dry-run
```

A SessionStart hook runs a fast check (no `claude mcp list`, which is slow) and a scheduled job runs the full
check every 6 hours (launchd on macOS; on Linux the CLI prints a cron line). Both write or remove
`~/.carlo-brain/state/boot.d/health.md`, capped at 900 characters. Headless runs (`CARLO_HEADLESS=1`) do nothing.

## What it checks

Jobs, from the state the other modules already leave (nothing to configure):

- `self-improve`: one job per task of `config.d/self-improve-tasks.json`, proof is the task state file, threshold is the longest gap between slots plus its `window_h`.
- `proactive`: the scan (`state/proactive/signals.json`, 12 hours), only if a source is enabled.
- `night`: the trigger (`state/night/launched_*`, 48 hours), only while a task is queued, because an empty queue legitimately never runs.
- Your own, in `config.d/health.json`.

A job with no proof file is "no run yet" until it has been installed longer than its threshold, then it fails.

Connectors, cheap and read only:

- `claude-auth`: `keys/claude_oauth_token` present, not empty, mode 600, younger than 335 days. Only when `night` or `self-improve` is installed. The content is never read.
- `whatsapp`: the database exists and opens read-only (when the file exists or the proactive source is enabled).
- `apple-notes`, `apple-messages` (macOS): the database opens read-only (Full Disk Access).
- `telegram`: bot token file present and private, when `config.d/telegram.json` exists.
- `mcp:<name>`: for each name in `expect_mcp`, listed by `claude mcp list` and not reported failed (full check only).

## Catch-up

A stale job that has a `command` is relaunched once, detached, with a clean environment (no API keys,
`CARLO_HEADLESS=1`), then not again for `catchup_retry_h` hours (default 6). The attempt is marked before the
launch. `self-improve` tasks declared with `catch_up: true` use their own command; `proactive` reruns its scan;
`night` has none on purpose (its trigger has conditions: window, power). Set `"catchup": false` to only report.

## Self-repair

`repair.py` holds the playbook: a list of known failures, each with a detector and a fix. It runs after every
check (the SessionStart hook and the 6 hourly job), then the checks run again so the note shows the real state.

Safe fixes run on their own, **at most once per failure per 24 hours**, and every attempt is a line in
`state/health/repair.log` (fixed or failed, with the reason). The attempt is marked before the fix runs, so a
crash cannot loop.

| Failure | Fix |
|---|---|
| a `com.carlo-brain.*` launchd job whose plist exists but is not loaded (macOS) | `launchctl bootstrap gui/<uid> <plist>` |
| an `expect_mcp` server missing from `claude mcp list` (full check only) | the `claude mcp add ...` command stored in `repair.mcp_commands` (anything else is refused) |
| the WhatsApp bridge configured but not running | start it detached, log in `state/logs/whatsapp-bridge.log` (not when a launchd service owns it) |
| a log under `state/` (or listed in `repair.logs`) over `max_log_mb` | copy to `<name>.1`, truncate in place |
| a missing state folder (`state/boot.d`, `state/health`, `state/logs`, `config.d`, module folders) | create it |

These never run on their own. The exact one-line command or settings path goes into `state/boot.d/health.md`,
so the next session hands you a single action:

| Failure | What you get |
|---|---|
| expired or missing login token | `claude setup-token` and where to save the token (a `chmod 600` line when only the permissions are wrong) |
| lost Full Disk Access (Notes, Messages, WhatsApp database) | `open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"` |
| missing Telegram bot token | the path to put it at (key files are never created, read or printed) |
| any fix that failed, was tried less than 24 hours ago and is still broken, or has no stored command | the command to run by hand |

Switch it off with `"repair": false` (or `"repair": {"enabled": false}`): nothing is changed, the commands still
reach your session. The ignore list of the watchdog also applies (`"ignore": ["proactive.scan"]` for a launchd job).

## Customize

`~/.carlo-brain/config.d/health.json`:

```json
{
  "ignore": ["night"],
  "jobs": [{"name": "digest", "proof": "~/reports/digest_*.md", "max_age_h": 30, "command": "python3 ~/bin/digest.py"}],
  "files": [{"name": "chats", "path": "~/data/chats.db", "sqlite": true}],
  "expect_mcp": ["vault"],
  "catchup": true,
  "catchup_retry_h": 6,
  "repair": {
    "enabled": true,
    "max_log_mb": 10,
    "logs": ["~/logs/digest.log"],
    "mcp_commands": {"vault": "claude mcp add vault -s user -- npx my-vault-mcp"},
    "whatsapp_bridge": {"command": "~/bin/whatsapp-bridge", "cwd": "~/bin"}
  }
}
```

## Limits

- It repairs only the five safe cases above. A lost permission, an expired login or a missing key is for you (one line, not a fix).
- Repairs are tested with a mocked `launchctl`, `claude` and `pgrep` and a fake home, not on a long-lived real setup. A launchd job you unloaded on purpose is loaded again after a day unless you list it in `ignore`.
- Retry is once per 24 hours per failure: if a fix does not hold, you hear about it after the first try, not a second silent one.
- Age is the file modification time, so a job that touches its proof without succeeding looks healthy.
- It checks that a connector is set up and readable, not that its remote service answers.
- No Windows support (launchd and cron only).
