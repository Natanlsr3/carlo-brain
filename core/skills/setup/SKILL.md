---
name: setup
description: Deep setup of Carlo Brain. Use when the user says "setup", "set me up", "configure Carlo", "onboard me", "continue the setup", or when the boot context says MAP.md is still the template, a setup session is planned today, or a setup was left unfinished. Maps the computer with a read-only scan while interviewing the user, then writes MAP.md and the project entry files.
---

# Deep setup

Goal: replace the template in `MAP.md` with the user's real map, without anyone editing a file by hand, by combining a read-only scan of the computer with a short interview. About 10 minutes for the quick path; the full scan can run in the background and the setup can continue in a planned session.

## Find the files

- Vault folder: run `carlo config get vault` (or read the `@.../00_System/SYSTEM_PROMPT.md` line in `~/.claude/CLAUDE.md`).
- Map: `<vault>/00_System/MAP.md`. Projects: `<vault>/10_Projects/`.
- Read `MAP.md` first. Keep its structure: the same headings and the same order (Who, Active projects, Upcoming deadlines, Where to look for more, Dictation shortcuts). Remove the line `<!-- map-template ... -->` when you write it.
- Scan results: `~/.carlo-brain/state/scan/scan.md` (summary) and `scan.json` (details).

## Resume first

Run `carlo setup status`. If a setup is in progress, say in one line where it stopped ("We stopped at step X, you already told me Y") and continue from that step; do not ask again what is saved. If a session was planned for today, say so, then run `carlo setup plan --clear` once it starts. Save progress after every step: `carlo setup save <step> --done --answer key=value` (steps: consent, scan, interview, map, write, connectors, plan, done). Never put a secret in an answer.

## Rules

- ONE question per message, short. Wait for the answer. Accept "skip" on any of them.
- Never invent anything. A fact that was not said or not seen in the scan goes in as "(to fill)" or is left out.
- Answer in the language the user writes in.
- Never write a file before showing it and getting a yes.

## The flow, in order

**a. Explain and ask for consent.** Three lines: (1) a read-only scan of the computer runs on this machine, (2) it reads names, dates and the first lines of README and Markdown files, never mail, messages, keys, .env files, .ssh, Library or shell profiles, (3) nothing leaves the computer. Then list the folders: run `carlo scan --quick` without `--yes` and it prints them, or read `scan.roots` (`carlo config get scan.roots`; the defaults are the usual work folders that exist). Ask: "Scan these folders? (yes / no / change the list)". On "change the list": `carlo config set scan.roots '["~/Work"]'`. On "no": skip to the interview (step c) and map from answers only.

**b. Start the scan.** After a yes: `carlo scan --quick --yes` (under 30 seconds), then `carlo scan --full --yes --background`. Follow it with `carlo scan --status`. Do not wait for it.

**c. Interview while it scans**, one question at a time, saving each answer:
1. Who are you? First name, role, city if they want, constraints (dictates by voice, works in the evening).
2. How do you like answers? Short or long, which language, anything to avoid. This becomes the "Who" line and, if it is a firm rule, one line in `00_System/memory/`.
3. What are your current priorities?
4. What do you want help with first? (morning briefing, mail or chat triage, drafting, research, code)
5. Optional: words your dictation gets wrong (only if they dictate).

**d. Propose the map from the scan.** Read `scan.md`. Say: "I found N projects; which are active, and what is each about?" List at most 10 (name, last activity, one README line if any), most recent first. The user confirms or edits in a few answers: keep, drop, rename, one line on what it is. Mention the folders with many recent files and any Obsidian vault or Notion export as candidates too. If the full scan is still running, use the quick results and say the full one will add detail.

**e. Write.** Draft the full new `MAP.md` and one entry file per active project at `<vault>/10_Projects/<name>/<name>.md` (3 lines: goal, current state, path of the files). Lowercase names without spaces for folders. Show the map in a code block and the entry files with their 3 lines. Ask: "Write it? (yes / change X)". On yes, write. Never overwrite an existing entry file: show what you would add and ask. Tell them in one line which files you wrote.

**f. Propose connectors, one at a time**, based on `sources` in the scan (presence only), each with its exact next step from `~/carlo-brain/docs/03-connect-your-sources.md` (or https://github.com/Natanlsr3/carlo-brain/blob/main/docs/03-connect-your-sources.md):
- Mail, Messages, Contacts or Calendar `readable`: `carlo add connectors`, then Full Disk Access for the terminal (System Settings, Privacy and Security).
- `denied` on one of them: the terminal has no Full Disk Access yet; give that step first.
- `whatsapp_bridge` present: it is already installed, check it with `carlo doctor`.
- Google or Notion MCP not configured and the user mentioned them: claude.ai Settings, Connectors.
- Code projects found: `carlo add review-loop agents-skills`. Obsidian vault or many notes: `carlo add search`. Codex or Gemini installed: `carlo add other-agents`, then `carlo connect codex` or `carlo connect gemini`.
Offer ONE, wait for yes or no, then the next. After a no, do not offer it again.

**g. Long setup? Plan a session.** If the full scan is not finished, or the interview or map is only half done, or the user is running out of time, propose a dedicated session of 1 to 2 hours this week: "When do you want to do the full setup? Give me a day and time." Store the slot: `carlo setup plan --date YYYY-MM-DD --time HH:MM`. The next sessions remind them on that day. Save progress so the setup resumes where it stopped.

**h. Close.** `carlo setup finish` when everything is written. Remind in two lines that a weekly refresh will suggest new or inactive projects and new sources (one question at a time, never editing the map without a yes). End with ONE concrete action for today, under 5 minutes (for example: type "what did we do last session?" in the next session).

## Weekly refresh suggestions

When the boot context has a "Map refresh" section, ask its suggestions ONE closed question at a time (yes or no), at a natural pause. On yes, show the exact change to `MAP.md` or the entry file, ask "Write it?" and write only after that yes. On no, run `carlo scan --dismiss <id>` with the id given in the section.
