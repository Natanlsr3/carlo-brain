# Carlo Brain

[![tests](https://github.com/Natanlsr3/carlo-brain/actions/workflows/tests.yml/badge.svg)](https://github.com/Natanlsr3/carlo-brain/actions/workflows/tests.yml)
![status](https://img.shields.io/badge/status-beta%200.1-orange)
![license](https://img.shields.io/badge/license-MIT-blue)

**A Jarvis for Claude Code: a second brain made of Markdown notes you own. It remembers your projects between sessions, opens each day with a short briefing, and never sends anything without your "go".**

![A Claude Code session opening with the Carlo Brain boot briefing](docs/assets/boot.gif)

Works with Claude Code (the most complete), OpenAI Codex CLI, Google Gemini CLI and any other LLM. Open source, no server, no account. Français : [démarrage rapide](docs/FR-demarrage.md).

```bash
curl -fsSL https://raw.githubusercontent.com/Natanlsr3/carlo-brain/main/get.sh | bash
```

You need macOS or Linux, Python 3.9+, git, and [Claude Code](https://docs.claude.com/en/docs/claude-code) installed and logged in. The script clones into `~/carlo-brain`, installs with defaults (vault in `~/carlo-vault`) and tells you what to type next. Read it first if you like: [get.sh](get.sh). Prefer to do it by hand?

```bash
git clone https://github.com/Natanlsr3/carlo-brain && cd carlo-brain && ./install.sh
```

## Your first 10 minutes

**1. Run `claude` and type `setup` (5 minutes).** The assistant asks you at most 6 short questions, one at a time: who you are, how you like answers, your 1 to 3 active projects and where their files are, where your todo, calendar and contacts live, and what you want help with first. It then shows you the `MAP.md` and the project files it will write, and writes them when you say `yes`. No file to edit by hand. (On a fresh install the assistant offers it on its own.)

**2. Start a new session and read the first message.** The assistant opens with a one-sentence "Ready" that recalls what it knows. On day one it has no history, so it is short. Nothing there? Run `carlo doctor`, then see the [FAQ](docs/09-faq.md#nothing-appears-at-session-start).

**3. Try three things.**

- Do one small task, quit (`/exit`), start `claude` again and type: `What did we do last session?` The answer comes from `SESSION_LOG.md`.
- Correct it once: `Answer in two lines maximum from now on. Remember this.` It shows the change as a diff, you say `yes`, and a line lands in `00_System/CORRECTIONS.md`.
- In a terminal: `carlo search "pricing"` (a word from your map, needs `carlo add search`).

**4. Add the next two modules.** `setup` suggests them from your answers. What each one needs first: [reference](docs/11-reference.md#what-each-module-needs-first).

## What it does

- **Remembers.** A short map of who you are and what you work on is loaded every session, plus the last sessions. The rest is read on demand.
- **Briefs you.** Opens the day with a ranked briefing of mail, chats and todo (module `proactive`).
- **Delegates.** Specialist subagents (researcher, reviewer, cto, reader) and skills (writer, docs, explainer).
- **Connects.** Apple apps, WhatsApp, Google, Notion, Slack, a browser, web research.
- **Improves itself.** Weekly jobs audit your setup and propose changes, with backup and undo.
- **Works at night.** A queue of multi-step tasks, a one-line report in the morning.
- **Protects.** Drafts first, "go" to send, secrets never read, every send audited.
- **Travels.** The same rules and memory in Codex, Gemini or any LLM (`carlo connect codex`).

Everything, with how to trigger each feature: [docs/00-features.md](docs/00-features.md). More detail (module table, comparison with CLAUDE.md, a day with it): [docs/11-reference.md](docs/11-reference.md).

## Privacy and safety

- Everything stays local: no server, no telemetry, no account. What leaves your machine is what Claude Code sends in your sessions, plus the connectors you switch on.
- Nothing is sent without your "go", and a send that contains a key, password, IBAN or card number is blocked.
- Prompt injection is not solved: the guards are a seat belt, not a sandbox. Full version: [docs/07-security-and-privacy.md](docs/07-security-and-privacy.md).

## Documentation

0. [Everything Carlo Brain can do](docs/00-features.md)
1. [What it is and why](docs/01-what-and-why.md)
2. [Install](docs/02-install.md)
3. [Connect your sources](docs/03-connect-your-sources.md)
4. [Extend it: skills, agents, hooks, jobs, modules](docs/04-extend.md)
5. [Architecture](docs/05-architecture.md)
6. [Day to day: the rituals](docs/06-day-to-day.md)
7. [Security and privacy](docs/07-security-and-privacy.md)
8. [Costs and limits](docs/08-costs-and-limits.md)
9. [FAQ](docs/09-faq.md)
10. [What exists today, and what is missing](docs/10-what-exists-today.md)
11. [Reference: modules, commands, words, status](docs/11-reference.md)

Français : [démarrage rapide](docs/FR-demarrage.md). Each module also has its own README in `modules/<name>/README.md`.

## Contributing

Issues and pull requests are welcome. Python 3.9+, standard library only, no personal data or keys in code, tests or docs. A module is a folder with `module.toml`, `README.md`, `install.sh`, `uninstall.sh`, `src/` and `tests/` ([how](docs/04-extend.md)). Run `python -m pytest -q` before you push; new behaviour comes with a test. To make the tests reject your own terms (name, company), set `CARLO_BRAIN_BANNED` to a comma separated list.

## License

MIT, see [LICENSE](LICENSE). Your vault, keys and data stay on your machine.
