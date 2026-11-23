# 1. What it is and why

## The problem

Claude Code is a strong worker with no past. Each session starts from zero: it does not know what you did yesterday, who you are waiting on, which rules you gave it last week, or that you hate tables in a terminal. Most people patch this with one big `CLAUDE.md` that grows until it is slow, expensive and half stale.

Three failures follow:

- **Amnesia.** You re-explain the same context every morning.
- **Passivity.** The assistant waits to be asked, while the things that hurt are the ones nobody asks about: a reply you owe, a schedule that never reached your calendar.
- **Fragility.** Autonomy without guard rails ends with a secret printed in a transcript, a message sent that you never read, or a self-modifying agent that broke its own rules and cannot go back.

## The idea

Carlo Brain turns Claude Code into a personal Chief of Staff, using only things you already have: Claude Code hooks, a folder of Markdown, and your operating system's scheduler.

- **A vault is the memory.** An Obsidian vault holds the system prompt, a short map of who you are and what you work on, a session log, a corrections log, skills and behaviour rules. Plain files, in git if you like, readable by you in Obsidian and by the assistant.
- **Load little, load the right thing.** At session start only the recent past and what needs attention are injected, hard capped. Everything else is read on demand, when the task needs it.
- **Hooks do the housekeeping.** Writing the log entry, saving a summary before compaction, blocking a secret read, committing the vault: none of it depends on the model remembering to do it.
- **Modules, not a monolith.** Each capability is a module you add or remove with `carlo add` and `carlo remove`. Removing one restores your settings exactly.
- **Code decides what is risky.** Whether a self-improvement is applied, reviewed or refused is a path table evaluated by code, not a judgement the model makes about itself.

## What it is not

- Not a hosted service. Nothing leaves your machine except what Claude Code itself sends to Anthropic, and the connectors you choose to turn on.
- Not a sandbox. The security module is a seat belt that catches the mistakes an autonomous assistant actually makes. Read [07-security-and-privacy.md](07-security-and-privacy.md).
- Not a replacement for Claude Code. It is a set of files and hooks around it. Uninstall it and Claude Code works as before.
- Not finished. Version 0.1, beta, see the status section of the README.

## Design principles

1. **Read freely, write only on your go.** The default for anything that reaches another person is: prepare, show, wait for `go`.
2. **Judge the result, not the exit code.** A night step is done only when it says so on a `STATUS:` line. A weekly job that produced no report failed, whatever its exit code.
3. **Failures are loud.** Every failure becomes a line in your next session. A source that cannot be read is reported, never replaced by an empty section.
4. **No secrets in the model's reach.** Key files live in `~/.carlo-brain/keys/`, are read through `*_FILE` variables, and the model is blocked from opening them.
5. **Subscription, not accidental billing.** Background `claude -p` calls strip every API key variable from their environment, so they use your own login.
6. **Reversible by default.** Settings edits take a timestamped backup, are tagged, and are removed by tag. Automatic improvements are archived and undoable.
7. **Small and boring.** Python standard library, Markdown, JSON, shell. You can read all of it in an afternoon.

## Who it is for

People who already live in Claude Code and want it to be continuous: founders, students, consultants, anyone with several projects, a busy inbox and a habit of dictating tasks in bursts. If you use Claude Code once a week for a single repository, the plain `CLAUDE.md` is enough.

Next: [install it](02-install.md).
