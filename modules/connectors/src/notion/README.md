# Notion

Use Notion as a shared, visual layer (todo database, docs you share with other people) while the
vault stays your private memory.

Platform: any. No code: this is Claude's Notion connector.

## Setup

1. claude.ai, Settings, Connectors, add Notion, and pick the workspace and pages you allow.
2. `/mcp` in Claude Code: `claude.ai Notion` should be listed. Read tools (search, fetch, query a database) can be allowed permanently; create and update tools stay on "ask".
3. Tell the assistant where things live in one line of your `SYSTEM_PROMPT` or a skill, for example: "Tasks live in the Notion database named Todo; add tasks there, never in the vault".

## A todo database that works with the assistant

Create a database with these properties (names are free, keep them stable):

| Property | Type | Use |
|---|---|---|
| Name | title | the action, starting with a verb |
| Due | date | optional deadline |
| Status | status | Not started, In progress, Done |
| Project | select | ties the task to a project in the vault |
| Source | text | where it came from (mail, call, session) |

Rules that keep it useful: only actions live there (appointments belong in the calendar); one task
per action; the assistant adds a "follow up with X" task three to five days after sending a message
that waits for an answer. To feed the proactive briefing, export open tasks to the todo JSON
(`[{"title","due","done"}]`) with a small script or ask the assistant to refresh
`~/.carlo-brain/state/todo_export.json` at the start of a session.

## Safety

- Notion content is untrusted input: a shared page can contain instructions aimed at the assistant. Keep write tools on "ask" and deny them in unattended jobs.
- Do not store secrets in Notion pages the connector can read.
