# Google suite (Gmail, Calendar, Drive, Docs, Sheets)

No code to install: Claude's own connectors do the work. This guide covers setup, the permissions
we recommend, and how the rest of Carlo Brain uses them.

Platform: any. Needs a claude.ai account (the connectors are tied to it) and Claude Code logged in with it.

## Setup

1. Open claude.ai, Settings, Connectors, and connect Gmail, Google Calendar, Google Drive, Google Docs and Google Sheets (only the ones you want). Sign in with the Google account and approve the scopes.
2. In a Claude Code session run `/mcp` (or `claude mcp list` in a terminal). The connectors appear as `claude.ai Gmail`, `claude.ai Google Calendar`, and so on. If they do not, run `claude` once, `/login` with the same claude.ai account, and check again.
3. First use of each tool asks for permission. Decide the standing rule below.

## Recommended permissions

Reading is safe to allow permanently. Anything that sends, creates or changes something for other
people should stay on "ask", and be denied in unattended jobs.

| Allow always (read) | Ask every time | Deny in night / scheduled jobs |
|---|---|---|
| search and read mail threads, list calendar events, search and read Drive files, read Docs and Sheets | send mail, create drafts, create or update calendar events, share a file, edit a document | all of the middle column |

Exact tool names look like `mcp__claude_ai_Gmail__search_threads` or
`mcp__claude_ai_Google_Calendar__list_events`. They are set by the connector, so list them with `/mcp`
before writing allow or deny rules, and put the deny rules in the `--disallowedTools` of your jobs (the
`night` module has a built-in deny list that you extend with `extra_denied_tools` in `~/.carlo-brain/config.d/night.json`: see `modules/night/README.md`).

## How the other modules use them

- **proactive**: slots found in messages are listed for the assistant to check against Google Calendar; schedules found in mail are added to the calendar with your go.
- **night**: unattended tasks may read mail, calendar and Drive, never write them.
- **agents-skills**: the `docs` skill produces shared documents in Google Docs when a document leaves your machine.

## Good practice

- Search before you assume something is missing: mail (including Sent), calendar, Drive, then local files.
- Before any external action check it was not already done (Sent folder, calendar).
- A Drive file shared outside needs your explicit go for that file.

## Limits

Connector availability, scopes and tool names are controlled by Anthropic and Google and change over
time. If a tool name in this guide does not exist, trust `/mcp`.
For Apple Mail (read-only, local, no Google involved) see `connectors/apple` and the `proactive` module.
