# security

Three layers of protection against the mistakes an autonomous assistant actually makes: reading a secret, sending one, or looping.

## What it does

| Hook | Script | Effect |
|------|--------|--------|
| PreToolUse (Bash, Read, Grep, Glob, Edit, Write) | `block_secret_reads.py` | Blocks reading shell profiles, environment files, secrets files (`SECRETS.md`, `secrets.json`, a `secrets/` folder; the bare word `secret` in a command such as `grep -r secret src/` is fine), SSH/AWS/GPG folders, key files, `~/.carlo-brain/keys`, and commands that dump the environment (`env`, `printenv`, `export`, `echo $API_KEY`). |
| PreToolUse (Bash, MCP tools) | `send_guard.py tool` | When a call sends content out (mail, chat message, post, comment, calendar invite, `curl` POST to an external URL, `gh ... comment/create`), blocks it if the content holds an API key, token, private key, password, valid IBAN or valid card number. |
| UserPromptSubmit | `send_guard.py prompt` | You typing `send anyway` opens a 5 minute override for exactly one send. Pasted content cannot open it. |
| PostToolUse (Bash, MCP tools) | `audit.py record` | Appends every send (and every blocked attempt) to `~/.carlo-brain/state/audit.jsonl`. |
| UserPromptSubmit, PostToolUse, Stop | `guardrails.py` | Long request: alignment reminder. Same file edited 5 times or same command run 3 times: loop reminder. Code changed and no test ran: blocks the stop once and asks for tests or a reason. |

## Why

- Masking a secret by hand fails the first time a token has an unexpected format, and then the secret is in the conversation. So these files are never opened at all. A key can still be used: pass its path to a program through `NAME_KEY_FILE=<path>`, and check it exists with `test -s <path>`.
- The send guard never prints the value it found, only its type and position.
- The audit log stores a SHA-256 fingerprint of each send, plus an 80 character preview of the subject or first text field with any detected secret redacted, never the full content, and each line carries the hash of the previous one. `python3 ~/.carlo-brain/security/audit.py verify` (also run by `carlo doctor`) reports the first broken link if someone edits or deletes a line.

## Setup

```bash
carlo add security
carlo doctor
python3 ~/.carlo-brain/security/audit.py show      # last sends
```

## Customize

All settings are JSON values set with `carlo config set <key> <value>`:

- `security.extra_patterns`: your own patterns for the send guard, label to regex. Example for an internal customer id format:
  `carlo config set security.extra_patterns '{"customer id": "CUST-[0-9]{8}"}'`
- `security.send_tools`: extra tool names to treat as sends (exact names), for MCP servers whose tool names the heuristic does not recognise:
  `carlo config set security.send_tools '["mcp__my_server__notify"]'`
- `security.fail_closed`: `true` to block a tool call when the hook input cannot be read (default: let it through with a warning).
- `security.guardrails_off`: any of `"alignment"`, `"loops"`, `"tests"`.

To protect an extra file name from reads, edit `SECRET_FILE` in `~/.carlo-brain/security/block_secret_reads.py` (it is overwritten by `carlo add security`, so keep your change in the repo copy).

## If tool calls start failing

A hook that errors can make every tool call fail. Fastest ways out, from quickest to cleanest:

1. Run `carlo remove security` in a normal terminal (outside Claude Code if it is stuck). It deletes only the hooks tagged `# carlo-brain:security` and takes a timestamped backup of `~/.claude/settings.json` first. `carlo add security` puts them back.
2. No `carlo` available: open `~/.claude/settings.json` and delete the hook entries whose `command` ends with `# carlo-brain:security`. The backup copies are next to it as `settings.json.bak-carlo-<timestamp>`.
3. Find the cause: `carlo doctor` and `~/.carlo-brain/state/errors.log`.

By default an unreadable hook input (empty or malformed stdin) lets the call through with a warning on stderr, so a broken hook does not freeze you. If you prefer to block in that case, run `carlo config set security.fail_closed true`; then the two guards exit 2 on unreadable input, and the escape routes above matter more.

## Limits (read this)

- This is a seat belt, not a sandbox. It matches tool calls by pattern. A determined or confused process can still find another way to read a file (for example through a script it writes and runs). Do not rely on it as your only protection for production credentials.
- Send detection for MCP tools is name based (`send`, `reply`, `post`, `share`, `draft`, `comment`, `invite`, `upload` and similar, excluding `get`/`list`/`search`...). A send tool with an unusual name needs `security.send_tools`.
- The IBAN and card detectors validate checksums, so random digits do not trigger them. Passwords are detected only in `password: value` form.
- The audit chain proves integrity of the middle of the log, not the tail: someone who deletes the last lines cannot be detected. Copy it elsewhere if you need that.
- Hook matching of `Bash|mcp__.*` means the guard runs for every MCP call; non-send calls return immediately.
