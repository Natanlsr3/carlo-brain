# connectors

Ways for your assistant to reach your information and your tools: your Apple apps, WhatsApp, the
Google suite, Notion, Slack, a browser, the web, your phone, and a server of your own.
One folder per connector, each with a setup guide; where code exists it ships with tests.

Status: **beta** as a whole. Connectors that wrap Anthropic's own features (Google, Notion, Slack,
browser) are guides only. The code in `apple/`, `remote-control/` and `vault-mcp/` is tested on
simulated databases and fake servers, never on real personal data.

## Why

An assistant that cannot see your mail, calendar, chats and notes can only answer questions. With
read access it can notice things (see the `proactive` module), and with careful write access it can
prepare and, on your go, do things. The design rule for every connector here: **read freely, write
only with your go, and never write in unattended jobs.**

## The connectors

| Folder | What | Platform | Kind |
|---|---|---|---|
| `apple/` | Contacts, Messages, Notes, Reminders, Calendar (read-only), Apple Mail pointer | macOS | code, tested |
| `whatsapp/` | read and search your chats, send on request; feeds `proactive` | macOS, Linux | install script for the open source bridge |
| `google/` | Gmail, Calendar, Drive, Docs, Sheets through claude.ai connectors | any | guide |
| `notion/` | a shared todo database and docs | any | guide |
| `slack/` | read, search, post with your go | any | guide |
| `browser/` | Claude in Chrome, Playwright MCP, hosted automation; `carlo connect browser` registers the Playwright server | any | setup script, tested with mocked subprocess (beta) + guide |
| `openrouter/` | ask a non-Claude model through an OpenAI-compatible endpoint, key from a file; `route.py` routes tasks by agent or kind with a fallback to Claude | any | scripts, tested with mocked HTTP (beta) |
| `web-research/` | WebSearch, context7 docs, the `researcher` agent | any | guide |
| `remote-control/` | continue a session from your phone; or talk to a Telegram bot | macOS, Linux | script + beta bridge, tested |
| `server/` | a small always-on server holding your vault and assistant | Linux | setup script (dry-run tested), guide |
| `vault-mcp/` | your vault as an authenticated MCP endpoint | macOS, Linux | code, tested (beta) |

## Setup

```
carlo add connectors
python3 -I ~/.carlo-brain/connectors/connect.py list
python3 -I ~/.carlo-brain/connectors/connect.py doctor      # what works on this machine (read-only)
```

Nothing is switched on by installing the module: open the guide of the connector you want
(`~/.carlo-brain/connectors/<folder>/README.md`) and follow it. Install only what you will use.

## How the pieces fit

- `proactive` reads Apple Mail and the WhatsApp database locally and writes the morning briefing.
- `night` and `self-improve` run unattended with an allow-list of read tools and a deny-list of every send, create and update tool (WhatsApp send, mail send and draft, calendar writes, Notion writes, Slack posts).
- `security` (if installed) blocks outgoing messages containing keys or card numbers and guards secret files.
- Key files live in `~/.carlo-brain/keys/` (mode 600) and are read through `*_FILE` variables, never put in arguments or the environment of other programs.

## Customize

- Add a connector: a folder under `src/` with a `README.md` (setup, rules, risks, limits) and, if there is code, `tests/test_connectors_<name>.py` against a simulated source. `connect.py` lists folders from its `CATALOG`, a test keeps catalog and folders in step.
- Different country phone formats: `CARLO_DEFAULT_COUNTRY_CODE`.
- Vault MCP deny list and write rules: `VAULT_MCP_DENY`, `VAULT_MCP_WRITE_EXT`, `VAULT_MCP_READONLY` (see `vault-mcp/README.md`).

## Known limits

- The Apple readers depend on private database layouts (checked on macOS 15). They fail loudly with a reason, never silently with an empty result.
- The WhatsApp bridge is an unofficial client of WhatsApp: see the risks in its guide before pairing a main account.
- Connector names and scopes controlled by Anthropic or Google can change; trust `/mcp` over this text.
