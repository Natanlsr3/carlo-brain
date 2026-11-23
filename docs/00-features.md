# Everything Carlo Brain can do

One page, plain words. Each line says what a feature does, how you trigger it, and what you type or see. **[beta]** marks modules that are tested on simulated data only (see [Status in the README](../README.md#status)). Everything else is stable. Install a module with `carlo add <name>`; the module that holds each feature is in brackets.

New here? Start with [Your first 10 minutes](../README.md#your-first-10-minutes).

## Memory

- **Memory map** [core]. A short file, `00_System/MAP.md`, says who you are, your projects and where their files are. It is loaded at every session start. Trigger: automatic. Example: you fill MAP.md once, and the assistant knows your projects without being told.
- **Boot briefing** [memory]. At session start the assistant gets the last log entries and anything that needs attention, capped at 9,000 characters. Trigger: type `claude`. Example: "Ready. Yesterday you were on the pricing page."
- **Session log** [memory]. Every session ends with an entry in `SESSION_LOG.md`; if the assistant forgets, a hook writes a short one. Trigger: automatic. Example: ask "what did we do last session?".
- **Corrections** [core]. When you correct the assistant, it proposes the change to a rule, you approve, and it logs it in `CORRECTIONS.md`. Trigger: say "no, not like that, remember this". Example: "never use a table in the terminal".
- **Facts to validate** [memory]. Facts extracted from your sessions wait in `FACTS_TO_VALIDATE.md` until you say yes or no. Trigger: automatic (needs the `claude` CLI). Example: the briefing says "2 facts wait for your yes or no".
- **Compaction safety** [memory]. Before Claude Code shrinks a long conversation, a summary is saved and the next boot points to it. Trigger: automatic.
- **Session score** [memory]. A mechanical 0 to 10 trend from your corrections and interruptions. Trigger: `python3 ~/.carlo-brain/memory/quality.py summary`.
- **Vault in git** [sync]. The vault is committed at session start and end, with an optional private remote. Trigger: automatic after `carlo add sync`. Example: `git -C ~/carlo-vault log`.

## Briefing and proactive

- **Ranked morning briefing** [proactive, beta]. Reads WhatsApp, Apple Mail and a todo export, with no model call, and opens the day with five points and one question. Needs a source connected first ([docs/03](03-connect-your-sources.md)). Trigger: `carlo add proactive`, enable a source, then `claude`. Example: "Sam replied about the invoice. Draft ready."
- **Follow-ups** [proactive, beta]. Notices who you are still waiting on, and nudges after a few days. Trigger: automatic once a source is on.
- **Voice** [proactive, beta]. Reads the briefing aloud once a day. Off by default. Trigger: `"voice": {"enabled": true}` in `config.d/proactive.json`.
- **Source check** [proactive, beta]. Shows which sources work. Trigger: `python3 -I ~/.carlo-brain/proactive/run.py doctor`.

## Agents and review

- **Subagents** [agents-skills, beta]. `researcher`, `cto`, `reviewer`, `reader`, `listener`, `improver`, `video-quiz`, each with its own role and tools. Trigger: ask for the job. Example: "have the researcher find three sources on X".
- **Skills** [agents-skills, beta]. `writer` (drafts in your voice), `docs`, `explainer` (study sheet and flashcards), `browse`. Trigger: say what you want. Example: "explain how DNS works, make me a study sheet".
- **Review loop** [review-loop, beta]. After a session changes code in a git repo, the assistant is asked to run the `reviewer` before saying done. Trigger: automatic. Example: after an edit, it says it is calling the reviewer. Switch off with `carlo config set review_loop.enabled false`.
- **Test reminder** [security]. If code changed and no test ran, the first stop is blocked once. Trigger: automatic.

## Safeguards

- **Draft, then go** [core]. Anything that leaves your machine is shown first and sent on your `go`. Trigger: a rule in the system prompt. Example: "Send the reply to Sam? (go / let me look)".
- **Secret read block** [security]. Shell profiles, `.env` files, key files and commands that dump the environment are refused. Trigger: automatic. Example: `cat .env` is blocked.
- **Secret send block** [security]. A send holding a key, token, password, valid IBAN or card number is refused. Trigger: automatic; type `send anyway` to open a 5 minute override for one send.
- **Audit log** [security]. Every send and blocked attempt is kept in a hash-chained file. Trigger: `python3 ~/.carlo-brain/security/audit.py show`.
- **Loop and alignment reminders** [security]. A nudge after the same edit five times, or on a very long request. Trigger: automatic.
- **Health check of the install**. Trigger: `carlo doctor`. Example: lines marked `[ok]`, `[warn]`, `[FAIL]`.

## Connectors

- **Apple apps** [connectors, beta, macOS]. Read-only Contacts, Messages, Notes, Reminders and Calendar. Needs Full Disk Access. Trigger: ask the assistant. Example: "who is this number?".
- **WhatsApp** [connectors, beta]. Read and search chats through an open source bridge, send only on `go`. Trigger: run `install_bridge.sh`, then ask. Example: "what did Alex say about Friday?".
- **Google, Notion, Slack** [connectors, beta]. Guides for the claude.ai connectors. Trigger: follow the guide, then ask.
- **Browser** [connectors, beta]. Registers the Playwright MCP server; the `browse` skill keeps it to its own tab. Trigger: `carlo connect browser`. Example: "open this page and summarise it".
- **Other models through OpenRouter** [connectors, beta]. Send a task to a non-Claude model, with Claude as fallback. Trigger: edit `config.d/routing.json`, then `carlo route sync` (`carlo route status` shows drift).
- **Phone** [connectors, beta]. Claude Code Remote Control in tmux, or a read-only Telegram bot. Trigger: `start_remote.sh start`. See `modules/connectors/src/remote-control/README.md`.
- **Vault over MCP, personal server** [connectors, beta]. A self-hosted endpoint for your vault, and a server setup script. For advanced use.

## Search

- **`carlo search`** [search, beta]. Read-only search of your vault, folders (text, PDF, Word, PowerPoint, Excel), Notes, Messages and Mail, with a deny list for secrets. Trigger: `carlo add search`. Example: `carlo search "invoice march"` prints `path:line: snippet`.
- **find-it skill** [search, beta]. The assistant searches before it asks you. Trigger: say "where did I put the lease?".

## Self-improvement

- **Weekly scout and improver** [self-improve, beta]. One job reads the outside world, one audits your setup. They only propose. Trigger: scheduled (Saturday and Sunday 09:00). Needs a long-lived login, see the module README.
- **Tiered apply with undo** [self-improve, beta]. Code decides: safe edits are applied with a backup, system prompt edits wait as a diff, anything near secrets is refused. Trigger: `python3 -I ~/.carlo-brain/self-improve/main.py pending`, then `undo <id>` to revert.
- **Personal bench** [self-improve, beta]. Your rules as test cases. Trigger: `main.py bench --quick`.

## Night work

- **Task queue** [night, beta]. Multi-step tasks run one step at a time while you sleep, with every send tool denied. Trigger: `python3 -I ~/.carlo-brain/night/main.py add 01_digest --prompt-file p.md --steps 3`. Example: next morning, one line per task: done, to finish, or not started.
- **Marathon mode** [night, beta]. A long backlog worked pass after pass until 09:15. Off by default and heavy on quota. Trigger: `{"marathon": {"enabled": true}}` in `config.d/night.json`.

## Health

- **Watchdog** [health, beta]. Checks that scheduled jobs ran and connectors still work, and tells your next session only when something broke. Trigger: `carlo health status`.
- **Self-repair** [health, beta]. Relaunches a missed job once and fixes known safe failures, each logged. Trigger: `carlo health repair --dry-run`, then without `--dry-run`.

## Other agents and models

- **Codex CLI and Gemini CLI** [other-agents, beta]. The same rules, boot context, guards and agents. Trigger: `carlo connect codex` or `carlo connect gemini` (`--status`, `--remove`). Example: `/carlo:cto <task>` in Gemini.
- **Any other LLM** [other-agents, beta]. One paste-ready prompt with your rules, map and recent sessions. Trigger: `carlo context --copy`, then paste it into the first message. No hooks or guards there.

## Manage the install

`carlo list` shows modules and what is installed, `carlo status` lists hooks, `carlo config get|set <key>` changes settings, `carlo remove <module>` takes one out cleanly, `carlo uninstall` puts everything back.
