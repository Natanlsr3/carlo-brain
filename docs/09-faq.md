# 9. FAQ

## Nothing appears at session start

1. `carlo doctor`. Look for `[FAIL]` on the hooks line of `memory` or on the CLAUDE.md block.
2. Start a **new** session. Hooks and CLAUDE.md are read at start; `/resume` skips the boot injection on purpose.
3. Check the hook is registered: `carlo status` prints the number of hooks per module. Open `~/.claude/settings.json` and look for commands ending in `# carlo-brain:memory`.
4. Run the hook by hand: `echo '{}' | python3 -I ~/.carlo-brain/memory/boot.py`. It should print a JSON object with `additionalContext`.
5. Read `~/.carlo-brain/state/errors.log`. Hooks never raise, they log one line instead.
6. If the system prompt itself seems ignored, check that `~/.claude/CLAUDE.md` has the block and that the vault path in it exists.

If the hook is silent, the template tells the assistant to read the last four entries of `SESSION_LOG.md` itself and say so.

## Will it break my existing Claude Code settings?

It merges, it does not replace. Before every change to `settings.json` it takes a timestamped backup, and it refuses to touch a file that is not valid JSON. Every hook it adds is tagged, so `carlo remove` and `carlo uninstall` delete only those. Your own hooks and your own `CLAUDE.md` content stay.

## How do I remove it?

`carlo uninstall` removes every module and the CLAUDE.md block and keeps `~/.carlo-brain/` (state, keys, config). Add `--purge` to delete that folder too. The vault is never deleted. Details in [02-install.md](02-install.md#uninstall).

## Does it send my data anywhere?

Not by itself. See [07-security-and-privacy.md](07-security-and-privacy.md#where-your-data-lives): sessions and background `claude -p` calls go to Anthropic as usual, and each connector you turn on has its own data flow, described in its guide.

## Will it use my API key?

No, on purpose. Background calls remove every key-like variable from their environment, so `claude -p` falls back to your own login and counts against your subscription. See [08-costs-and-limits.md](08-costs-and-limits.md).

## Do I need Obsidian?

No. The vault is plain Markdown in a folder, and the assistant reads it directly. Obsidian is a comfortable window for you: links, search, graph. Any editor works.

## Can I use only one module?

Yes. `./install.sh --modules security` gives you the secret and send guards and nothing else; the core vault and the CLAUDE.md block are always installed. `sync` requires `memory`. Everything else stands alone, though `proactive`, `self-improve` and `night` show their results through the memory boot injector.

## Does it work on Linux? On Windows?

Linux: yes for the core, memory, security, sync, self-improve, night, agents-skills and the non-Apple connectors. Scheduled jobs print a cron line instead of using launchd, and the Apple readers do not exist. Windows: not supported; WSL is untested.

## Can I change the assistant's name, language or tone?

Name and your first name are asked at install and stored in `~/.carlo-brain/config.json`; edit the vault's `SYSTEM_PROMPT.md` freely, it is yours. The template is in English. To work in another language, say so in the prompt and in `MAP.md`, and add your words to the `proactive` keyword options (`extra_keywords`, `keywords`), whose defaults are English. The quality score heuristic also reads English phrasing.

## How big can MAP and SYSTEM_PROMPT get?

They are loaded in full at every session, so every line costs context every time. Keep MAP under a page. Put detail in project files and let the assistant read them on demand. The self-improve scout may propose trims; changes to these two files always arrive as a diff for you.

## Where do my rules go: system prompt, memory, or a skill?

- A rule that applies to everything: `SYSTEM_PROMPT.md`.
- A rule learned from one correction: a file in `00_System/memory/`, indexed in `MEMORY.md`.
- A recipe for a recurring situation: a skill in `00_System/skills/`.
- Facts about a project: that project's folder in `10_Projects/`.

## Two machines, same vault?

Install `sync` on both with the same private remote. Each session start commits and pulls; each end commits and pushes. Two machines editing the same note between syncs will conflict: the merge is aborted, nothing is lost, and the next session tells you. Never put secrets in the vault.

## What does `carlo doctor` say "audit chain" about?

The security module's send log is hash chained. `CHAIN BROKEN at record N` means a line was edited or removed. If you edited it yourself, copy the file aside and start a new one; if you did not, treat it as a signal worth investigating.

## A hook is slow or errors

Read `~/.carlo-brain/state/errors.log` and `~/.carlo-brain/state/logs/`. Hooks have timeouts (5 to 10 seconds) and swallow their own errors, so a problem shows as a missing feature plus a log line, not a crash. `carlo doctor` shows when each hook last ran.

## The weekly jobs did not run

`python3 -I ~/.carlo-brain/self-improve/main.py status` shows each task's last outcome. The scheduler runs while you are logged in and catches up within the window (72 hours by default). Scheduled jobs need a login that works unattended: run `bash ~/.carlo-brain/self-improve/create_token.sh` once. On Linux check that you added the cron line.

## How do I add my own agent, skill or job?

[04-extend.md](04-extend.md).

## Why are some modules called beta?

Because they depend on things that change (Apple's private databases, an unofficial WhatsApp protocol, Claude Code's permission rule syntax) or on behaviour that automated tests cannot prove (real models in unattended runs). Each README has a Known limits section. Run unattended jobs by hand first, with dry runs, before you leave them alone.

## How do I contribute or report a problem?

See Contributing in the main README. For security issues, use a private advisory and include no real credentials.
