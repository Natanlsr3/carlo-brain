---
name: setup
description: Guided first setup of Carlo Brain. Use when the user says "setup", "set me up", "configure Carlo", "onboard me", or when the boot context says MAP.md is still the template. Interviews the user in at most 6 short questions, then writes MAP.md and the project entry files.
---

# Setup interview

Goal: replace the template in `MAP.md` with the user's real map, so nobody has to edit it by hand. Total time: about 5 minutes.

## Find the files

- Vault folder: run `carlo config get vault` (or read the `@.../00_System/SYSTEM_PROMPT.md` line in `~/.claude/CLAUDE.md`).
- Map: `<vault>/00_System/MAP.md`. Projects: `<vault>/10_Projects/`.
- Read `MAP.md` first. Keep its structure: the same headings and the same order (Who, Active projects, Upcoming deadlines, Where to look for more, Dictation shortcuts). Remove the line `<!-- map-template ... -->` when you write it.

## Interview rules

- At most 6 questions, ONE per message, short. Wait for the answer before asking the next. Accept "skip" on any of them.
- Never invent anything. A fact that was not said goes in as "(to fill)" or is left out.
- Answer in the language the user writes in.

## The questions

1. **Who are you?** First name, role, city if they want to say it, constraints (dictates by voice, works in the evening).
2. **How do you like answers?** Short or long, which language, anything to avoid. This becomes the "Who" line and, if it is a firm rule, one line in `00_System/memory/`.
3. **Your 1 to 3 active projects.** For each: a name, one line on the goal and the current state, and where its files live (a folder path, a repo, a Drive link).
4. **Where do your todo, calendar and contacts live?** For example Apple Reminders, Notion, Google Calendar, the Contacts app.
5. **What do you want help with first?** For example a morning briefing, mail or WhatsApp triage, drafting, research, code.
6. Optional, only if the answers hint at it: **words your dictation gets wrong** (skip if they do not dictate).

## Write

1. Draft the full new `MAP.md` and one entry file per project at `<vault>/10_Projects/<name>/<name>.md` (3 lines each: goal, current state, where the files are). Use lowercase names without spaces for folders.
2. Show the user the draft in one message: the map in a code block, then the list of entry files with their 3 lines.
3. Ask: "Write it? (yes / change X)". On `yes`, write the files. Never overwrite an existing project entry file: if one exists, show what you would add instead and ask.
4. After writing, tell them in one line which files you wrote. Add one session log entry only if the system prompt asks for it.

The facts about the user (the "Who" block) are exactly the lines that must be approved before writing: the confirmation above is that approval.

## Suggest the next 2 modules

Based on the answers, name exactly two, each with its one command and a doc link. Use this table (in your head, do not print it):

- Mail, WhatsApp or a todo export mentioned: `carlo add proactive` (morning briefing), and read `docs/03-connect-your-sources.md` first because it needs a source.
- Code projects: `carlo add review-loop agents-skills`.
- Lots of documents or notes to find: `carlo add search`.
- Notes that must be backed up: `carlo add sync`.
- Codex or Gemini used too: `carlo add other-agents`, then `carlo connect codex` or `carlo connect gemini`.
- Nothing specific: `carlo add agents-skills search`.

End with ONE concrete action for today, under 5 minutes (for example "type: what did we do last session?" in your next session).
