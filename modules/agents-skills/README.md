# agents-skills

A starter set of Claude Code **agents** (specialists the main assistant delegates to) and **skills**
(recipes loaded when their description matches), written to be generic and safe to adopt as they are or to
edit. Installed into `~/.claude/agents` and `~/.claude/skills` **without ever overwriting a file of yours**.

Status: **beta**. Installer and file formats are covered by tests; the quality of the agents' answers is
yours to judge, which is what the `self-improve` bench is for.

## What is in it

| Name | Kind | What it does | Notes |
|---|---|---|---|
| `researcher` | agent (sonnet) | sourced web research: one URL per fact, each claim tagged measured, estimated or hypothesis, ends with a "so what" | read and web tools only |
| `cto` | agent (inherits) | code work in a repo: reads the project's conventions first, tests before logic, minimal solution, guardrails against destructive git commands, final report with exact test counts | edits files and runs commands |
| `reviewer` | agent (sonnet) | independent second look before something is called done or sent: findings ranked blocker, should fix, nit, each with `path:line` and the smallest fix | strictly read only |
| `reader` | agent (haiku) | wide read and search that returns paths and line numbers, not contents | strictly read only |
| `listener` | agent (haiku) | reads the session log, corrections and parking list for repeated blockers, stalled tasks and ideas ready to promote; at most three proposals | read only, plan mode |
| `improver` | agent (opus) | interactive version of the weekly improver: audits your setup, tests ideas on a copy, proposes changes through the `self-improve` loop | needs the `self-improve` module |
| `video-quiz` | agent (sonnet) | transcribes a video locally with whisper, writes a summary with timecodes, answers quiz questions quoting the transcript, answers `absent` when the video does not say it | needs yt-dlp, ffmpeg, whisper-cli |
| `writer` | skill | mail and message drafting in your voice from a style file; facts sourced or marked [to verify]; shown first, sent only on your go | style file `00_System/STYLE.md` |
| `docs` | skill | documents worth sending: align with you before writing, substance validated or sourced, shareable format, short review when it matters | |
| `explainer` | skill | a study sheet and flashcards that follow learning-science rules: key idea first, vocabulary, misconceptions refuted, citations, recall questions, review plan | Markdown only, no audio or video rendering |
| `browse` | skill | open a page with the browser tools, read it, act only in its own tab; never submits a form, pays, logs in or enters a secret without your go | needs `carlo connect browser` (or Claude in Chrome) |

Left out on purpose: the author's agents tied to one person's own projects and interests. The pattern to copy for your own is in any file here: a front matter
with a precise `description` (that is what triggers it), a minimal `tools` list, and rules that end with a
self-check before delivering.

## Setup

```
carlo add agents-skills
python3 -I ~/.carlo-brain/agents-skills/install_agents.py status
```

Claude Code picks agents and skills up at the start of a session. Skip some:
`python3 -I ~/.carlo-brain/agents-skills/install_agents.py install --skip cto,docs`.

How the installer treats your files (it keeps a hash of what it installed in
`~/.carlo-brain/state/agents-skills/manifest.json`):

- a file that does not exist is copied;
- a file that is exactly what we installed earlier is updated to the new version (module upgrade);
- a file that differs (you edited it, or it is your own with the same name) is left alone, and our version is saved beside it as `<name>.new` so you can compare;
- uninstall removes only files that still match what we installed, and prunes empty skill folders.

To use another Claude folder (for tests or a second profile): `CARLO_CLAUDE_DIR=/path`.

## Customize

- **Edit them freely**: your edits are protected. Better still, copy an agent under a new name and change the copy.
- **Make `writer` yours**: fill `00_System/STYLE.md` in your vault (languages, formality per kind of person, openings, sign-offs, forbidden phrases). The skill asks three questions and writes it if it is missing.
- **Tool lists**: each agent lists the minimum tools it needs. Add a tool only when you can say why; the read-only agents (`reader`, `listener`, `researcher`, `reviewer`) have no write, edit or shell tool, and a test keeps it that way.
- **video-quiz setup**: install `ffmpeg`, `yt-dlp` and whisper.cpp (`whisper-cli`) with a model file (`brew install ffmpeg yt-dlp whisper-cpp` on macOS, then download a ggml model); point `WHISPER_MODEL` at it and, optionally, `TRANSCRIBE_OUT` at a folder for transcripts. Everything is local: no audio leaves your machine. A video behind a login needs exported cookies or a screen recording; the agent says so after two failed attempts.

## Known limits

- Descriptions decide when an agent or skill triggers. If one fires too often or never, adjust its `description` first.
- `explainer` here is the light version (sheet and cards). The author's richer version renders HTML sheets, podcasts and videos with local tooling; it is not shipped because it is large and tied to specific local tools.
- Agents cannot protect you from prompt injection by themselves: keep unattended jobs on read tools (see `night` and `self-improve`).
