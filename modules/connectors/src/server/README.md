## A personal server for your assistant (beta)

An always-on machine that holds a copy of your vault and keeps your assistant reachable when your
laptop is closed. A 1 vCPU / 2 GB Linux VPS is enough (any provider), or a spare computer at home.

Platform: Linux with systemd (the script targets Debian/Ubuntu style systems, no sudo needed after the
packages are installed). Status: beta. `setup_server.sh` is tested in dry-run mode only; the real run
touches a server, so read it first (it is about 100 lines, no sudo, no system files).

## What you get

- the vault cloned from your private git repository, kept in step by the `sync` module (install it on the server too);
- a Claude Code **Remote Control** session in tmux, started at boot, that you open from your phone (`connectors/remote-control`);
- optional: the **vault MCP server** (`connectors/vault-mcp`) behind TLS, so other machines can read and write the vault through one authenticated URL;
- optional: unattended jobs (weekly scout, self-improvement, night tasks) that run while you sleep without your laptop being on.

## Setup

1. Create the server, add your SSH key, update packages. Create a normal user (do not work as root). Install `git`, `python3`, `tmux`.
2. Install Claude Code on it (see its documentation) and log in once, interactively (`claude`).
3. On the server: `carlo add connectors` (copy this repository there first, or install from it), then:

```
VAULT_REPO=git@github.com:you/your-vault.git bash ~/.carlo-brain/connectors/server/setup_server.sh
```

   The script prints a **deploy key** (public half): add it on your git host as a deploy key with write
   access to the vault repository only. It then clones the vault, writes a baseline `~/.claude/settings.json`
   that denies reading `.env` files, `~/.ssh` and `~/.carlo-brain/keys` (only if you have no settings yet),
   installs two systemd user units and enables lingering.
4. `bash ~/.carlo-brain/connectors/vault-mcp/rotate_token.sh` once (creates the MCP token file), then
   `systemctl --user enable --now carlo-vault-mcp carlo-remote`.
5. Put TLS in front of the MCP port (`vault-mcp/Caddyfile.example`) if you use it from other machines.

Try `DRY_RUN=1 VAULT_REPO=... bash setup_server.sh` first to see every step without changing anything.

## Keep it safe

- **One purpose, one user.** No other services under that user. Firewall: only SSH (and 443 if you use the MCP behind Caddy). Disable SSH password login.
- **Deploy key, not your personal key**, scoped to the vault repository.
- **No secrets in the vault.** The server has a full copy of it. Keep API keys in `~/.carlo-brain/keys/` (mode 600) on the machine that needs them, and out of git.
- **Unattended jobs never send anything.** Give them read tools and file writes only; deny mail, chat and calendar writes in their `--disallowedTools`.
- **Back up** by having the vault in git (the sync module); the server itself holds nothing you cannot rebuild.
- **Updates**: `sudo apt upgrade` regularly, and re-run `rotate_token.sh` when someone who had the token leaves your life or your laptop is lost.

## Limits

- No GUI automation or Apple-only connectors on a Linux server (Apple Mail, Messages, Notes, Reminders). The WhatsApp bridge, the web connectors and the vault run fine.
- Remote Control and claude.ai connectors need you to be logged in on the server with your account; session expiry applies, so check it now and then (`claude` then `/status`).
