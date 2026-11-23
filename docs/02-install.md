# 2. Install

About ten minutes for the core, plus whatever connectors you decide to turn on.

## Prerequisites

| You need | Why | Check |
|---|---|---|
| macOS or Linux | Hooks and scripts target these. Windows is not supported (WSL is untested). | `uname` |
| Claude Code | The hooks run inside it. Log in once with `claude`. | `claude --version` |
| Python 3.9 or newer | Everything is Python standard library. | `python3 --version` |
| git | Only the `sync` module needs it, and it is useful anyway. | `git --version` |
| Obsidian | Your reading window on the vault. Optional for the assistant, recommended for you. | open the app |

Some modules have extra, optional tools: `tmux` (Remote Control), `go` and `uv` (WhatsApp bridge), `yt-dlp`, `ffmpeg` and `whisper-cli` (the `video-quiz` agent). `carlo doctor` tells you which are missing and what you lose without them.

## 1. Get the code

One line (clones into `~/carlo-brain`, runs the installer with defaults, vault in `~/carlo-vault`):

```bash
curl -fsSL https://raw.githubusercontent.com/Natanlsr3/carlo-brain/main/get.sh | bash
```

Extra arguments go to the installer: `... | bash -s -- --vault ~/notes`. The script never overwrites a `~/carlo-brain` folder that is not a git checkout (set `CARLO_BRAIN_DIR` to clone elsewhere), updates it with `git pull` if it is, and uses no sudo. If you used it, skip to step 3. By hand instead:

```bash
git clone https://github.com/Natanlsr3/carlo-brain
cd carlo-brain
```

The checkout stays where it is: `carlo` records its path and copies module code from it. Do not delete it after installing.

## 2. Run the installer

```bash
./install.sh
```

It checks Python and git, then runs `carlo init`, which asks three questions:

- **Vault folder** (default `~/carlo-vault`). Pick a folder outside `~/Desktop` and `~/Documents` if you plan to use `sync` with scheduled jobs on macOS, because launchd jobs cannot read those folders without extra permissions.
- **Assistant name** (default `Carlo`). Used in the system prompt.
- **Your first name** (optional; when left empty the templates say "the user").

Non-interactive form, handy for scripts and CI:

```bash
./install.sh --yes --vault ~/carlo-vault --name Carlo --user Alex --modules memory,security,sync
```

Flags: `--vault DIR`, `--name NAME`, `--user NAME`, `--modules a,b` (or `none`), `--yes` (no prompts), `--force` (install even if a required binary is missing).

## What the installer changes

- Creates the vault from the template (existing files are never overwritten).
- Creates `~/.carlo-brain/` with code, config, state and a `keys/` folder (mode 700).
- Adds a managed block to `~/.claude/CLAUDE.md`, between `<!-- carlo-brain:begin -->` and `<!-- carlo-brain:end -->`. The block imports the vault's `SYSTEM_PROMPT.md` and `MAP.md`. Your own content in that file is untouched.
- Merges hooks into `~/.claude/settings.json`, after taking a timestamped backup (`settings.json.bak-carlo-<time>`). Each hook command ends with a `# carlo-brain:<module>` tag, which is how removal knows what is ours.
- Links `~/.local/bin/carlo` to the launcher of your checkout (never replaces a real file there). If `~/.local/bin` is not on your PATH, add it.
- Installs the default modules: `memory` and `security`.

If `settings.json` exists but is not valid JSON, the installer stops before touching anything.

## 3. Check it

```bash
carlo doctor
```

Each line is `[ok]`, `[warn]` or `[FAIL]`. It checks Python, git and claude, that settings parse, that the vault files and the CLAUDE.md block exist, key file permissions, each module's hooks and scripts, the audit chain, and when each hook last ran. "No hook has run yet" is normal right now.

## 4. Fill in your MAP

The easy way: run `claude` and type `setup`. The assistant asks at most 6 short questions, shows the `MAP.md` and project files it will write, and writes them on your `yes`. The first session proposes it by itself while `MAP.md` is still the template. To set up Codex or Gemini the same way, run `carlo connect codex` or `carlo connect gemini`, then ask for the `carlo-setup` skill (or `/carlo:setup` in Gemini).

By hand: open the vault in Obsidian, delete the `map-template` comment line at the top, and edit `00_System/MAP.md`: who you are, your active projects with the entry file of each, where your todo list and contacts live, and any dictation shortcuts. Keep it short, it is read at every session start. This is the single most valuable five minutes of the setup.

## 5. Start a session

```bash
claude
```

The first message should confirm the assistant is ready, mention the context it has, and flag anything that needs attention. If you see nothing, check the [FAQ](09-faq.md#nothing-appears-at-session-start).

## Add more modules

```bash
carlo list                         # what exists and what is installed
carlo add sync                     # git sync of the vault (needs memory)
carlo add proactive                # briefing from messages and mail
carlo add connectors               # guides and scripts for your sources
carlo add health                   # watchdog: jobs on time, connectors alive (needs memory)
carlo add search                   # `carlo search`: read-only search of vault, folders, Notes, Messages, Mail
carlo add self-improve night agents-skills
carlo status                       # installed modules, hooks per module, notes
```

A module that needs another one pulls it in first (`sync` requires `memory`). A module that needs a missing binary refuses unless you pass `--force`. A module that supports one platform only refuses on the other.

Per-module setup (config files, permissions, tokens) is in each `modules/<name>/README.md`, and sources are covered in [03-connect-your-sources.md](03-connect-your-sources.md).

## Upgrade

```bash
cd carlo-brain && git pull
carlo add memory security          # re-running add replaces the module code and refreshes its hooks
```

State, keys, config and your tasks live outside the code folders and are kept.

## Uninstall

```bash
carlo remove proactive             # one module: hooks, scheduled jobs and code removed, state and keys kept
carlo uninstall                    # everything: modules, CLAUDE.md block, CLI link; keeps ~/.carlo-brain state
carlo uninstall --purge            # also deletes ~/.carlo-brain
```

Your vault is never deleted. Hooks tagged by Carlo Brain are removed from settings; entries you added yourself are kept.
