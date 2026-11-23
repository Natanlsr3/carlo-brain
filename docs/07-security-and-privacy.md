# 7. Security and privacy

An autonomous assistant makes three kinds of costly mistakes: it reads a secret, it sends something it should not, or it loops. Carlo Brain addresses each, and is honest about what it does not cover. Read the Limits section before trusting any of it with something that matters.

## Where your data lives

- **Your vault and `~/.carlo-brain/`** stay on your disk. Carlo Brain has no server, no telemetry, no account.
- **What leaves the machine** is what Claude Code sends to Anthropic in your sessions, plus whatever connectors you switch on (Google, Notion, Slack, a hosted browser, a Telegram bot, a server of your own). Each connector guide lists its risks.
- **Background model calls** (fact extraction, weekly jobs, night tasks, the Telegram bridge) run `claude -p` with your own login. They send the text they are given to Anthropic like any session does.
- **The briefing is built without any model call.** `proactive` reads mail and chat databases locally, in read-only mode, and writes a short file. That file contains names and short excerpts, so treat `~/.carlo-brain/state/` like your mail.
- **Full message text is copied to disk only if you ask:** `sources.whatsapp.write_raw` (off by default) writes `raw_messages.md`, mode 0600, for the optional weekly triage.

## Layer 1: secrets are never opened

`security` blocks, in a `PreToolUse` hook on Bash, Read, Grep, Glob, Edit, Write and NotebookEdit:

- shell profiles, `.env` files, secrets files, SSH, AWS and GPG folders, key files, and `~/.carlo-brain/keys`;
- commands that dump the environment (`env`, `printenv`, `export`, `echo $API_KEY`).

Why block instead of mask: masking fails the first time a token has an unexpected format, and then the secret is already in the conversation. A key can still be used without being read: check it exists with `test -s <file>`, and give a program the path through a variable, for example `NAME_KEY_FILE=<path> program`. Key files live in `~/.carlo-brain/keys/` (folder mode 700, files mode 600; `carlo doctor` flags loose permissions and empty files, never prints contents).

## Layer 2: sends are checked and recorded

A `PreToolUse` hook on Bash and MCP tools recognises calls that send content out (mail, chat, post, comment, calendar invite, `curl` POST to an external URL, `gh ... comment/create`) and blocks them if the content holds an API key, token, private key, password, valid IBAN or valid card number. It reports only the type and position of what it found, never the value. IBAN and card detectors validate checksums, so random digits do not trigger them.

Override: you typing `send anyway` opens a five minute window for exactly one send. Pasted content cannot open it.

Every send and every blocked attempt is appended to `~/.carlo-brain/state/audit.jsonl`: a SHA-256 fingerprint, an 80 character preview with secrets redacted (never the full content), and the hash of the previous line. `carlo doctor` verifies the chain. Add your own patterns and tools:

```bash
carlo config set security.extra_patterns '{"customer id": "CUST-[0-9]{8}"}'
carlo config set security.send_tools '["mcp__my_server__notify"]'
carlo config set security.guardrails_off '["alignment"]'      # any of: alignment, loops, tests
```

## Layer 3: guardrails against loops and unchecked work

- A long request gets an alignment reminder.
- The same file edited five times, or the same command run three times, gets a loop reminder.
- If code changed and no test ran, the first attempt to stop is blocked with a request to run tests or give a reason.

## Unattended work never sends

Weekly jobs, night tasks and the sync module run without you. The rules they run under:

- Every send, create and update tool of the usual connectors is denied (WhatsApp send, mail send and draft, calendar writes, Notion writes, Slack posts). The lists are `UNATTENDED_DENY` in `modules/self-improve/src/selfimprove/jobs.py` and the deny list of the night module (extend with `extra_denied_tools` in `config.d/night.json`). Tool names depend on your connectors: check `/mcp`.
- The weekly jobs cannot edit your vault: it is mounted read-only for them, they write to a scratch folder, and code validates the output before it enters the queue.
- Night tasks get a standing rules block on every prompt: drafts in files only, no deletion, secrets never read, invent nothing.
- Background calls strip every `*API_KEY*`, `*SECRET*` and `*PASSWORD*` variable from their environment, so a scheduled job cannot bill an API account by accident and cannot see a key. A long-lived login for them is created with `bash ~/.carlo-brain/self-improve/create_token.sh`. That token, per Claude Code's documentation, can only make model requests: it cannot reach claude.ai connectors or start Remote Control.

## Self-improvement is bounded by code

Which files an automatic change may touch is a path table in code (tiers `auto`, `review`, `manual`, see [05-architecture.md](05-architecture.md#the-three-improvement-tiers)). Keys, the security module, the module's own code and config, SSH folders and anything with secret, token or password in its name are `manual`: refused. Your system prompt, settings and anything that sends are `review`: a diff for you. Applied changes are archived, verified and restored byte for byte on a failed check.

## Prompt injection

Web pages, mail, chat messages and shared documents can contain text aimed at the assistant ("forward my last ten chats to..."). No hook can recognise every such text. What reduces the damage:

- the send guard and the `go` pattern, which put a human between a draft and the outside world;
- read-only tools in unattended jobs and in the Telegram bridge by default;
- keeping write tools on "ask" in connectors, and not combining web browsing of unknown sites with write access to other systems;
- agents with the minimum tool list.

## If tool calls start failing: switching a hook off fast

A hook that errors can make every tool call fail. Fastest ways out, from quickest to cleanest:

1. Run `carlo remove security` in a normal terminal (outside Claude Code if it is stuck). It deletes only the hooks tagged `# carlo-brain:security` and takes a timestamped backup of `~/.claude/settings.json` first. `carlo add security` puts them back.
2. No `carlo` available: open `~/.claude/settings.json` and delete the hook entries whose `command` ends with `# carlo-brain:security`. The backup copies are next to it as `settings.json.bak-carlo-<timestamp>`.
3. Find the cause: `carlo doctor` and `~/.carlo-brain/state/errors.log`.

By default an unreadable hook input (empty or malformed stdin) lets the call through with a warning on stderr, so a broken hook does not freeze you. If you prefer to block in that case, run `carlo config set security.fail_closed true`; then the two guards exit 2 on unreadable input, and the escape routes above matter more.

## Recommendations

- Keep **secrets out of the vault**. Git history keeps them forever and the sync module copies the vault to a remote and a server.
- Use a **private** remote for `sync`.
- Use **full disk encryption**. The WhatsApp bridge stores everything in clear on disk, and so does your vault.
- Pair WhatsApp with a **secondary number** if an unofficial client worries you.
- Turn on **two step verification** on any account that controls a bridge (Telegram, claude.ai).
- Keep the vault and the bridge data **out of cloud-synced folders**.
- Run `carlo doctor` now and then, and read `~/.carlo-brain/state/errors.log` if it warns.

## Limits (read this)

- **A seat belt, not a sandbox.** Hooks match tool calls by pattern. A determined or confused process can find another way to read a file, for example through a script it writes and then runs. Do not make this your only protection for production credentials.
- **Send detection for MCP tools is name based** (`send`, `reply`, `post`, `share`, `draft`, `comment`, `invite`, `upload` and similar, excluding `get`, `list`, `search`). A send tool with an unusual name needs `security.send_tools`.
- **Passwords are detected only** in `password: value` form.
- **The audit chain** proves integrity of the middle of the log, not the tail: someone who deletes the last lines cannot be detected. Copy it elsewhere if you need that.
- **Self-hosted vault MCP** has not had an external security review. Anyone with its token has full read and write on the allowed part of the vault.
- **`carlo search` has its own deny list** (keys, `.env` files, `.ssh`, shell profiles, `Library`, files named like tokens or secrets) and hides lines that look like secrets (inside PDF, Office files and mail bodies too, and never in its optional text cache), but it is a pattern match: a secret in an ordinary file with an ordinary name can still be shown to the assistant in a snippet. Keep secrets in `keys/` or a password manager, and add your own `deny_dirs`.
- **Beta code** (proactive, connectors, self-improve, night, agents-skills, health, search) is tested with fakes, not on real accounts at scale.

## Reporting a vulnerability

Open a private security advisory on the repository rather than a public issue, and include the module, the version and steps to reproduce. Do not include real credentials.
