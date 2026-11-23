# Apple connectors (macOS only, read-only)

Small scripts that let the assistant find something in your Apple apps without asking you, using the
local databases. Python standard library only. Everything is read-only: the databases are opened with
`mode=ro` (if the live file is locked, a temporary copy is read and deleted). Nothing is ever written,
sent, completed or deleted.

| Script | What it does |
|---|---|
| `contacts.py "<name>"`, `contacts.py --phone <number>` | name, organisation, phones and mails; merges iCloud, Google and local sources |
| `messages.py search "<text>" [--days N]`, `messages.py thread "<name or number>"` | iMessage and SMS, with contact names resolved |
| `notes.py list`, `notes.py search "<text>"`, `notes.py read "<title>"` | Apple Notes; password-protected notes are reported, never read; "Recently Deleted" is skipped |
| `reminders.py list`, `count`, `export --out FILE` | open reminders through AppleScript; `export` writes the todo JSON the `proactive` module reads |
| `calendar_events.py [--days 7] [--calendar NAME] [--json]` | upcoming events (including recurring ones, cancelled ones skipped) from the Calendar database (beta) |
| Apple Mail | `python3 -I ~/.carlo-brain/proactive/run.py mail-recent 24` (the reader ships with the `proactive` module) |

Always run them with `python3 -I`, for example
`python3 -I ~/.carlo-brain/connectors/apple/contacts.py "Sam"`.

## Setup

1. **Full Disk Access.** System Settings, Privacy & Security, Full Disk Access: add the app that launches the scripts (Terminal, iTerm, your editor, or the Python used by a scheduled job). Without it you get a clear error, not an empty answer. Check with `python3 -I ~/.carlo-brain/connectors/connect.py doctor --no-mcp`.
2. **Reminders only:** the first run asks for permission to control Reminders (Automation). AppleScript opens the Reminders app; if it was closed, the script quits it again.
3. **Phone numbers:** numbers are matched on their last 9 digits, which handles `+CC` and national forms. If your contacts store national numbers starting with 0, set your country code once: `export CARLO_DEFAULT_COUNTRY_CODE=44` (use yours).

## Use cases

- "Who is this number?" while reading a chat: `contacts.py --phone`.
- "What did Sam say about the invoice?": `messages.py search "invoice" --days 30`, or `thread "Sam"`.
- "Where did I note the Wi-Fi code?": `notes.py search "wifi"`.
- Dictate tasks to Siri ("remind me to ..."), then `reminders.py export --out ~/.carlo-brain/state/todo_export.json` (schedule it) so the morning briefing shows what is due.
- "Am I free Thursday afternoon?": `calendar_events.py --days 4` (or the Google Calendar connector if your calendar lives there).

## Privacy rules we recommend

- Content you read stays in the session. It goes into the vault or the assistant's memory only when you ask.
- Do not point an unattended job at Messages or Notes unless you need it; those are your most private sources.
- The scripts print what they find to the terminal, so treat the session transcript as sensitive.

## Known limits (beta where noted)

- **Messages**: since macOS Ventura most message text is in `attributedBody`, a binary format decoded here with a heuristic. It is reverse engineered and may fail on some messages or after an update (the message is then skipped, not mangled).
- **Notes**: the body decoder (gzip + protobuf) is also reverse engineered. Checked on macOS 15; a future version can break it. Notes in iCloud folders that were never opened on this Mac may be empty.
- **Calendar** (beta): the table layout is private (checked on macOS 15). Times are shown in local time; all-day events show the date only. If it breaks, use the Google Calendar connector.
- **Reminders** goes through AppleScript, so it is slower (seconds) and needs the app to start.
- Linux and Windows: not supported (there are no such databases).
