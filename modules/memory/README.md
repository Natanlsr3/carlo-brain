# memory

Gives the assistant a memory that survives sessions, without loading the whole vault every time.

## What it does

| Hook | Script | Effect |
|------|--------|--------|
| SessionStart | `boot.py` | Injects a short context: health problems, signals dropped by other modules, pending facts, the last session log entries. Hard cap of 9,000 characters (Claude Code truncates around 10,000). |
| SessionEnd | `session_end.py` | If the session wrote no `SESSION_LOG.md` entry, adds a mechanical one (`[auto]`) under the marker. Scores the session. Starts fact extraction in the background. |
| PreCompact | `precompact.py` | Saves last messages, changed files, git commands and decisions to `state/compactions/` before context is lost; the next boot points to it. |

Extra scripts you can run by hand (installed in `~/.carlo-brain/memory/`):

- `health.py`: one line per problem (recent hook errors, session-end hook silent for a week, vault missing). Empty when fine. Shown at boot.
- `quality.py <transcript>` / `quality.py summary`: session score 0-10 from corrections, repeated requests, interruptions, hook blocks and "go"/"ok" messages. Stored in `state/quality.jsonl`. Mechanical: you rate nothing. Automatic sessions score `null`.
- `facts.py <transcript>`: extraction into `00_System/FACTS_TO_VALIDATE.md`.

## Why

Loading everything at boot is slow and expensive; loading nothing makes the assistant amnesiac. The boot hook injects only the recent past and what needs attention, and the system prompt tells the assistant to read the rest on demand.

## Signals from other modules (drop-in directory)

Any module or script can add a section to the next boot by writing a markdown file in `~/.carlo-brain/state/boot.d/`:

```bash
printf '%s\n' '<!-- once -->' 'The nightly report is ready: 00_System/REPORT.md' > ~/.carlo-brain/state/boot.d/report.md
```

A first line `<!-- once -->` means the file is deleted after being shown. Without it the signal stays until you remove the file. Each file is cut at 1,500 characters.

## Setup

```bash
carlo add memory
carlo doctor
```

Fact extraction needs the `claude` CLI. Without it the module works, the queue just stays empty. The call runs `claude -p --model haiku` with every `*API_KEY*`, `*SECRET*` and `*PASSWORD*` variable removed from the environment, so it uses your own Claude login and cannot spend an API key by accident.

## Customize

`carlo config set <key> <value>` (values are JSON):

- `memory.extract_facts` (default `true`): `carlo config set memory.extract_facts false` turns extraction off.
- `memory.exclude_patterns`: list of regexes. Messages matching one are never copied to the log, summaries or fact extraction (private channels, topics you want kept out of memory). Example: `carlo config set memory.exclude_patterns '["private-chat", "my-private-topic"]'`.
- `memory.projects`: map a working-directory folder name to a project, so a session started there sees the related log entries first:
  `carlo config set memory.projects '{"my-app": {"entry": "10_Projects/my-app/my-app.md", "tags": ["my-app"]}}'`.

## Limits

- The automatic log entry is deliberately minimal (first user messages, changed files). The system prompt asks the assistant to write a real entry; the auto one is the safety net.
- The quality score is a heuristic on English phrasing. Treat it as a trend, not a grade.
- Fact extraction quality depends on the model; that is why nothing is trusted before you validate it.
