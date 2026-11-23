# Self-hosted vault MCP server (beta)

One small authenticated endpoint that gives Claude Code (or any MCP client that accepts a header)
read and write access to your Obsidian vault from another machine or a server.
Python standard library only, one file (`server.py`), no database.

Platform: macOS and Linux. Status: beta. It is covered by tests (path confinement, token check,
protocol), but it has not had an external security review. Read "Threat model" before exposing it.

## Why

Your vault is a folder on one laptop. As soon as you want the same memory on a server or a second
machine, you need something to serve it. Git sync (the `sync` module) keeps copies; this server gives
live access to one copy, with a tool interface Claude understands.

## Tools

| Tool | What it does |
|---|---|
| `vault_list(path)` | files and folders of one folder |
| `vault_read(path)` | read a text file (up to 200 KB) |
| `vault_search(query, max_results)` | case-insensitive search in `.md .txt .csv .json`, one hit per file |
| `vault_write(path, content)` | create or overwrite a text file, atomically (temp file then rename) |
| `vault_append(path, text)` | append, creating the file if needed |

There is no delete tool and no rename tool, on purpose. `VAULT_MCP_READONLY=1` removes the write tools.

## Setup

On the machine that holds the vault (your server, or your laptop):

```
python3 -c 'import secrets;print(secrets.token_urlsafe(32))' > ~/.carlo-brain/keys/vault_mcp_token
chmod 600 ~/.carlo-brain/keys/vault_mcp_token
VAULT_MCP_VAULT=~/vault VAULT_MCP_TOKEN_FILE=~/.carlo-brain/keys/vault_mcp_token \
  python3 ~/.carlo-brain/connectors/vault-mcp/server.py
```

The server refuses to start if the token file is readable by others or shorter than 24 characters.
It listens on `127.0.0.1:8765` only.

Keep it running: on Linux copy `carlo-vault-mcp.service` to `~/.config/systemd/user/` (the file
explains the three commands); on macOS use a launchd job running the same command.

Reach it from other devices through a TLS reverse proxy, never the plain port:

- a server with a domain name: `Caddyfile.example` (Caddy fetches the certificate itself);
- no domain: Tailscale (`tailscale serve`) or a Cloudflare Tunnel, both give HTTPS without opening a port.

Register it in Claude Code on each client:

```
bash register_client.sh /path/to/file-with-the-token https://your-host/mcp
```

Then `/mcp` should list `vault` with five tools. This works with Claude Code (and other MCP clients that
let you set a header). The claude.ai website and phone app, as far as we know, expect custom
connectors to use OAuth rather than a static bearer token, so this server is not a drop-in for them
(untested here). For the phone, use Claude Code remote control instead, see `connectors/remote-control`.

Rotate the token any time (on the server): `bash rotate_token.sh`, then run `register_client.sh` again
on each client with the new token.

## Threat model

What it protects against:

- **Path escape.** Every path is resolved with symlinks and must end up inside the vault. `..`, absolute paths, and symlinks pointing outside are refused (also during search).
- **Secrets by name.** Hidden folders (`.git`, `.obsidian`) and file names matching `secret*`, `*secret*`, `.env*`, `*.pem`, `*_key*`, `*.key`, `id_rsa*`, `*password*`, `*token*` are invisible and unreadable. Change the list with `VAULT_MCP_DENY` (comma separated, matched on file names, case-insensitive).
- **Wrong writers.** Writes are limited to `.md .txt .csv .json` (`VAULT_MCP_WRITE_EXT`) and 500 KB.
- **Unauthenticated access.** Bearer token compared in constant time; health check answers `ok` without any data.

What it does not protect against:

- Anyone who has the token has full read/write on the allowed part of the vault. Treat it like a password; rotate on any doubt.
- Secrets whose file name does not match the deny list, or secrets pasted inside normal notes. Do not keep secrets in the vault at all.
- Prompt injection: a note or a web page the assistant reads can try to make it write something. Keep the server read-only for sessions that browse the web or read untrusted mail, and review what was written (`git diff` on the vault, see the `sync` module).
- Network exposure mistakes: keep it bound to localhost behind TLS.

## Limits

- JSON responses only (no streaming, no server-initiated messages), which is enough for tool calls.
- Search is a plain scan: fine for thousands of notes, slow for hundreds of thousands.
- One vault per server instance.
