# 3. Connect your sources

An assistant that cannot see your mail, calendar and chats can only answer questions. With read access it can notice things, and with careful write access it can prepare and, on your go, do things.

The rule behind every connector: **read freely, write only with your go, never write in unattended jobs.**

Install the module first, then follow the guide of each connector you want. Nothing is switched on by installing.

```bash
carlo add connectors
python3 -I ~/.carlo-brain/connectors/connect.py list            # connectors, platform, what each needs
python3 -I ~/.carlo-brain/connectors/connect.py doctor          # what works on this machine, read only
python3 -I ~/.carlo-brain/connectors/connect.py doctor --no-mcp # skip `claude mcp list` (it contacts every server)
```

Every guide is in `~/.carlo-brain/connectors/<folder>/README.md` and in `modules/connectors/src/<folder>/README.md` in the repo.

## At a glance

| Connector | Unlocks | Platform | Kind |
|---|---|---|---|
| `apple` | Contacts, Messages, Notes, Reminders, Calendar, read only | **macOS only** | code, tested |
| `whatsapp` | search and read chats, send on request, feeds the briefing | macOS, Linux | install script for an open source bridge |
| `google` | Gmail, Calendar, Drive, Docs, Sheets | any | guide (claude.ai connectors) |
| `notion` | a shared todo database and docs | any | guide (claude.ai connector) |
| `slack` | read, search, post with your go | any | guide (claude.ai connector) |
| `browser` | log in, fill forms, read JavaScript pages | any | guide |
| `web-research` | web search, library docs, the `researcher` agent | any | guide |
| `remote-control` | your session from your phone, or a Telegram bot | macOS, Linux | script, beta bridge |
| `server` | an always-on copy of your assistant | Linux with systemd | setup script, beta |
| `vault-mcp` | your vault as an authenticated MCP endpoint | macOS, Linux | code, beta |

Not a connector but a way to plug the brain into another assistant: `carlo connect codex` or `carlo connect gemini` (OpenAI Codex CLI, Google Gemini CLI), and `carlo context --copy` for any chat. See `modules/other-agents/README.md`.

Connector names and scopes controlled by Anthropic or Google can change. Trust `/mcp` in Claude Code over any text here.

## Apple apps (macOS only)

**Unlocks:** "who is this number?", "what did Sam say about the invoice?", "where did I note the Wi-Fi code?", "what is on my calendar Thursday?", and tasks you dictate to Siri showing up in your morning briefing.

**Setup:**

1. System Settings, Privacy and Security, Full Disk Access: add the app that launches the scripts (Terminal, your editor, or the Python a scheduled job uses). Without it you get a clear error, never an empty answer.
2. Reminders only: the first run asks for permission to control Reminders.
3. If your contacts store national numbers starting with 0, set `CARLO_DEFAULT_COUNTRY_CODE` once (for example `44`).

**Commands** (always with `python3 -I`):

```bash
python3 -I ~/.carlo-brain/connectors/apple/contacts.py "Sam"
python3 -I ~/.carlo-brain/connectors/apple/contacts.py --phone "+441234567890"
python3 -I ~/.carlo-brain/connectors/apple/messages.py search "invoice" --days 30
python3 -I ~/.carlo-brain/connectors/apple/messages.py thread "Sam"
python3 -I ~/.carlo-brain/connectors/apple/notes.py list
python3 -I ~/.carlo-brain/connectors/apple/notes.py search "wifi"
python3 -I ~/.carlo-brain/connectors/apple/notes.py read "Title"
python3 -I ~/.carlo-brain/connectors/apple/reminders.py export --out ~/.carlo-brain/state/todo_export.json
python3 -I ~/.carlo-brain/connectors/apple/calendar_events.py --days 7
```

Everything is read only: databases are opened with `mode=ro`. Password-protected notes are reported, never read. The message and notes decoders are reverse engineered and checked on macOS 15; a future macOS can break them, and they fail loudly with a reason.

## WhatsApp

**Unlocks:** read and search your chats from the assistant, send messages or files on request, and give the `proactive` module the signals for its briefing (questions waiting on you, replies that arrived, group action chatter).

**Setup:** needs `git`, `go` and [`uv`](https://docs.astral.sh/uv/).

```bash
bash ~/.carlo-brain/connectors/whatsapp/install_bridge.sh
```

It clones the open source [whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) bridge at a pinned commit, builds it and registers the MCP server. Then pair by running the bridge binary and scanning the QR code (WhatsApp, Settings, Linked devices). The link expires after about 20 days without the bridge running. Keep it alive with `bash install_bridge.sh --service` (macOS launchd; on Linux write a systemd user unit).

**Risks:** it can send as you, it is an unofficial client (accounts can be rate limited or banned, use a secondary number if that matters), and messages are stored in clear on disk. The `night` and `self-improve` modules deny the send tools. Read the risks section of the guide before pairing a main account.

## Google: Gmail, Calendar, Drive, Docs, Sheets

**Unlocks:** the assistant can search mail (Sent included), check your calendar, read Drive files, and with your go create drafts, events and documents.

**Setup:** no code. At claude.ai, Settings, Connectors, connect the ones you want. In Claude Code run `/mcp` to confirm they appear. Allow read tools permanently; keep send, create and update tools on "ask", and deny them in unattended jobs.

## Notion

**Unlocks:** a shared todo database (and docs for other people) next to your private vault.

**Setup:** claude.ai, Settings, Connectors, add Notion and pick the pages you allow. The guide describes a todo database layout that works well with the assistant and the briefing.

## Slack

**Unlocks:** read channels and threads, search, post with your go. The guide asks the assistant to read a channel's topic before posting and never to post from a night job.

**Setup:** claude.ai, Settings, Connectors, add Slack (some workspaces need an admin to approve the app).

## Browser

Three options from light to heavy: Claude in Chrome (your own signed-in browser, most convenient and most sensitive), the Playwright MCP (a separate profile, `claude mcp add playwright -s user -- npx @playwright/mcp@latest`), and hosted automation connectors (metered, your pages go to a provider). Use a dedicated profile, never the window you are typing in.

## Web research

Built-in WebSearch and WebFetch, library docs through context7 (`claude mcp add context7 -s user -- npx -y @upstash/context7-mcp`), and the `researcher` agent from the `agents-skills` module for sourced reports. Use the cheapest that answers the question.

## Phone: Remote Control or Telegram

- **Remote Control:** the same interactive session on your phone. `bash ~/.carlo-brain/connectors/remote-control/start_remote.sh start|status|attach` keeps one running in tmux.
- **Telegram bridge (beta):** a private bot that runs `claude -p` on your machine in your vault folder. Only the user ids you list are served, the token is read from a mode 600 file, and the default tools are read only. Setup: create a bot with BotFather, save the token with `install -m 600 /dev/null ~/.carlo-brain/keys/telegram_bot_token`, find your id with `python3 ~/.carlo-brain/connectors/remote-control/telegram_bridge.py discover`, write `~/.carlo-brain/config.d/telegram.json`, then `... telegram_bridge.py run`.

## Personal server (Linux, beta)

An always-on machine holding a copy of your vault, a Remote Control session and, if you want, unattended jobs. `VAULT_REPO=git@github.com:you/your-vault.git bash ~/.carlo-brain/connectors/server/setup_server.sh`, and try it first with `DRY_RUN=1`. Read the keep-it-safe section of the guide: one user, deploy key, no secrets in the vault.

## Self-hosted vault MCP (beta)

An authenticated endpoint exposing five tools (`vault_list`, `vault_read`, `vault_search`, `vault_write`, `vault_append`; no delete) over your vault, confined to the vault folder and hiding secret-looking file names. Stdlib Python, localhost only, put TLS in front. Treat the token like a password. Read the threat model in its README before exposing it.

## What the other modules do with these

- `proactive` reads Apple Mail and the WhatsApp database locally and writes the briefing.
- `night` and `self-improve` run unattended with read tools only and a deny list of every send, create and update tool.
- `security` blocks outgoing messages that contain keys or card numbers.

Next: [extend it](04-extend.md).
