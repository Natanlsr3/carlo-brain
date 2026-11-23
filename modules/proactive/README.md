# proactive

Your assistant looks at your messages, mail and todo for you, then opens the session with
a short ranked briefing (5 points, under 200 words, one closed question) instead of a report.

Status: **beta**. The logic is unit tested on simulated databases. The macOS readers (Apple Mail
index, WhatsApp bridge database) depend on private file layouts that Apple and the bridge can change.

## Why

Most "AI assistant" setups wait to be asked. The things that hurt are the ones nobody asks about:
a reply you owe, a schedule that arrived as an attachment and never reached your calendar, a
meeting slot agreed in a chat that is not in the diary. This module finds them without an LLM
(zero tokens, zero keys) and hands the assistant a ranked list.

The behaviour rule it injects at session start:

- an item the assistant can act on (a reply, a nudge, a calendar entry): prepare the draft first, then ask "ready, send it? (go / let me look)";
- plain information: one line, no question;
- a decision only you can take: one small closed question (yes / later);
- no long reports, and nothing leaves your machine without your go.

## What it reads (all read-only, all opt-in)

| Source | What it finds | Needs |
|---|---|---|
| `followups` | who replied to you, who you are still waiting on (days, last question) | WhatsApp bridge and/or Apple Mail |
| `whatsapp` | groups discussing an action, messages that mention you, private chats whose last message is not yours | [whatsapp-mcp bridge](../connectors/src/whatsapp/README.md) |
| `apple_mail` | unread mail from real people addressed to you directly | macOS Mail, Full Disk Access |
| `schedules` | mail with a timetable, rota or shift plan (subject or attachment), with a preview of the xlsx rows that mention you | Apple Mail |
| `slots` | meeting slots mentioned in chats and mail ("Thursday at 3pm"), to compare with your calendar | WhatsApp and/or Apple Mail |
| `todo` | tasks overdue, due today or tomorrow, from a JSON export | any exporter, see below |

Nothing is ever written to Mail or WhatsApp, read status is untouched (databases are opened with
`mode=ro`), and nothing is sent.

A source that cannot be read is reported at the top of the briefing as `Sources in outage: ...`.
It is never silently replaced by an empty section.

## Setup

```
carlo add proactive
python3 -I ~/.carlo-brain/proactive/run.py doctor
```

1. Edit `~/.carlo-brain/config.d/proactive.json`. Set `identity.names` (how people address you in group chats) and `identity.addresses` (your own mail addresses, used to tell sent from received).
2. Enable the sources you want (`"enabled": true`). Everything starts disabled.
3. macOS: grant **Full Disk Access** to the app that runs the scan (Terminal for hooks; the Python used by the scheduler for the hourly job). Without it Apple Mail and Messages are unreadable and the briefing says so. Test with `python3 -I ~/.carlo-brain/proactive/run.py mail-recent 24`.
4. `run.py doctor` prints which sources work. `run.py run` scans and writes the briefing.

The session start hook (`run.py boot`) is cheap and never blocks: if the last scan is older than
`refresh_minutes` it refreshes in the background, so the next session sees it. A scheduled job
(launchd on macOS, hourly) keeps it fresh. On Linux, add `python3 -I ~/.carlo-brain/proactive/run.py run` to cron; the WhatsApp and todo sources work there, Apple Mail does not.

Outputs, all under `~/.carlo-brain/state/`:

- `boot.d/proactive.md`: the short text the core boot injector adds to the session start.
- `proactive/briefing.md`, `digest.md` (all signals by kind), `signals.json` (machine readable), `followups.json` (the follow-up memory).

## Customize

Everything is in `~/.carlo-brain/config.d/proactive.json` (see `config.example.json`).

- **Scoring**: `scoring.kinds.<kind>.weight` decides the order, `.cap` limits how many of a kind can appear. Kinds: `reply`, `deadline`, `schedule`, `followup`, `direct_unanswered`, `direct_unread`, `group_activity`, `slot`, `mention`. Set a weight to 0 to mute a kind. `important_names` plus `important_bonus` lifts replies from people who matter.
- **Briefing size**: `briefing.max_points`, `max_words`, `words_per_point`. The last points are dropped first, never the first.
- **Keywords**: `sources.whatsapp.extra_keywords` and `sources.schedules.keywords` add your own words (the defaults are English).
- **Follow-ups**: `min_wait_days` (too early to nudge), `max_wait_days` (the thread is dead), `ignore` (names, numbers or addresses never followed). Mail sent to 4 people or more, links alone, "thanks" and "noted" replies are never treated as waits.
- **Names**: `contacts.csv` points to a CSV with columns `name,email` so mail senders get names.
- **Todo export**: `sources.todo.file` is a JSON list of `{"title": "...", "due": "YYYY-MM-DD", "done": false}`. The Apple Reminders connector writes it (`reminders.py export`); any script can.
- **Handled schedules**: once a schedule is in your calendar, add a fragment of its subject to `~/.carlo-brain/state/proactive/handled.txt` (one per line) so it stops coming back.

### Voice (optional, off by default)

`"voice": {"enabled": true}` reads the briefing aloud once a day, on the first session between
`hours` (default 6 to 13). macOS `say` (picks the first installed voice from `prefer`, or set
`voice.voice`), Linux `spd-say` or `espeak`, or any command that reads stdin: `voice.command`.
Mute without editing the config: `touch ~/.carlo-brain/state/proactive/voice_off`.
If the voice fails, the next briefing says "Voice failed on ..." until it works again.

### Weekly LLM triage (optional)

Keyword filters miss everything without a keyword. `triage_pass.sh` runs your Claude
subscription twice a week over the full message dump and writes `state/proactive/triage/TRIAGE_<date>.md`:
what needs you (with draft replies), what moves, and which keywords the filter missed.

1. Set `sources.whatsapp.write_raw` to `true` (writes `raw_messages.md`, mode 0600, local only).
2. Run it by hand first: `DRY_RUN=1 ~/.carlo-brain/proactive/triage_pass.sh`, then without `DRY_RUN`.
3. Schedule it (the self-improve module's task wrapper adds retries and catch-up of missed runs).

It strips API key variables from the environment so a background job uses your subscription and
never a billed key by accident (`CARLO_KEEP_API_KEYS=1` opts out). Its tools are limited to reading
and writing files; the prompt forbids sending anything.

## Privacy

Message content stays on your machine. The briefing is built without any model call. The boot file
contains names and short excerpts, so treat the state folder like your mail. `write_raw` is the only
option that copies full message text to disk; it is off by default.

## Known limits

- Apple Mail's index layout is private. It was checked on macOS 15 (Mail `V10`); the newest `V*` folder is auto-detected, but a future macOS can break it. The doctor command tells you.
- Mail bodies are read from downloaded `.emlx` files only. Mail that was never downloaded gives no body (the follow-up and slot detection then use subjects).
- iCloud/Exchange mailboxes with unusual folder names may need `IGNORED_MAILBOX` adjusted in `src/proactive/sources/mail_apple.py`.
- Keyword defaults are English. Add your language with the keyword options.
- No calendar read here: slots are listed, the assistant compares them using a calendar connector.
