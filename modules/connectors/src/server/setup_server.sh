#!/usr/bin/env bash
# Prepare a small Linux server (VPS or home server) to host your vault and an always-on assistant.
# Run it ON THE SERVER as a normal user (not root). It never uses sudo and never touches system files.
#
#   VAULT_REPO=git@github.com:you/vault.git bash setup_server.sh
#
# What it does (idempotent, safe to re-run):
#   1. checks git, python3, tmux and claude are installed (tells you how to install what is missing)
#   2. creates a deploy key for the vault repository and prints its PUBLIC half for you to add on your git host
#   3. clones the vault
#   4. writes a baseline ~/.claude/settings.json that denies reading secret files (only if you have none)
#   5. installs systemd USER units: vault MCP server (localhost only) and the Remote Control session
#   6. enables lingering so they keep running after you log out
#
# Env: VAULT_REPO (required)  VAULT_DIR (default ~/vault)  DRY_RUN=1 (print only)
#      CODE_DIR (default ~/.carlo-brain/connectors, where the connectors module was installed)
set -eu
VAULT_REPO="${VAULT_REPO:-}"
VAULT_DIR="${VAULT_DIR:-$HOME/vault}"
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
CODE_DIR="${CODE_DIR:-$BRAIN/connectors}"
KEY="$HOME/.ssh/carlo_vault_deploy"
UNITS="$HOME/.config/systemd/user"

run() { if [ "${DRY_RUN:-0}" = 1 ]; then echo "[dry run] $*"; else "$@"; fi; }
note() { echo "-> $*"; }

[ -n "$VAULT_REPO" ] || { echo "set VAULT_REPO (your private vault repository, ssh form)" >&2; exit 2; }
[ "$(id -u)" != 0 ] || { echo "do not run this as root; use a normal user" >&2; exit 2; }

# 1. prerequisites
missing=0
for tool in git python3 tmux; do
  command -v "$tool" >/dev/null 2>&1 || { echo "missing: $tool (install with your package manager, e.g. sudo apt install $tool)" >&2; missing=1; }
done
[ "$missing" = 0 ] || exit 1
command -v claude >/dev/null 2>&1 || note "claude CLI not found: install Claude Code (see its documentation), then log in with: claude"
[ -d "$CODE_DIR/vault-mcp" ] || note "connectors module not installed under $CODE_DIR: run 'carlo add connectors' first (units below point there)"

# 2. deploy key
if [ ! -f "$KEY" ]; then
  run mkdir -p "$HOME/.ssh"
  run chmod 700 "$HOME/.ssh"
  run ssh-keygen -q -t ed25519 -N "" -C "carlo-vault-deploy@$(hostname -s)" -f "$KEY"
fi
if [ -f "$KEY.pub" ]; then
  echo
  echo "Add this PUBLIC key as a deploy key WITH write access on your vault repository, then press Enter:"
  cat "$KEY.pub"
  [ "${DRY_RUN:-0}" = 1 ] || { [ -t 0 ] && read -r _ || true; }
fi

# 3. clone
if [ ! -d "$VAULT_DIR/.git" ]; then
  run env GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" git clone "$VAULT_REPO" "$VAULT_DIR"
  run git -C "$VAULT_DIR" config core.sshCommand "ssh -i $KEY -o IdentitiesOnly=yes"
else
  note "vault already cloned at $VAULT_DIR"
fi

# 4. baseline settings: never read secret files
SETTINGS="$HOME/.claude/settings.json"
if [ ! -f "$SETTINGS" ]; then
  run mkdir -p "$HOME/.claude"
  if [ "${DRY_RUN:-0}" = 1 ]; then
    echo "[dry run] would write $SETTINGS with deny rules"
  else
    cat > "$SETTINGS" <<'JSON'
{
  "permissions": {
    "deny": [
      "Read(**/.env)",
      "Read(**/.env.*)",
      "Read(**/SECRETS*)",
      "Read(~/.ssh/**)",
      "Read(~/.carlo-brain/keys/**)"
    ]
  }
}
JSON
    chmod 600 "$SETTINGS"
  fi
else
  note "$SETTINGS exists: not modified. Make sure it denies reading .env files, ~/.ssh and ~/.carlo-brain/keys"
fi

# 5. systemd user units
run mkdir -p "$UNITS"
if [ "${DRY_RUN:-0}" = 1 ]; then
  echo "[dry run] would install carlo-vault-mcp.service and carlo-remote.service in $UNITS"
else
  sed -e "s#%h/vault#$VAULT_DIR#g" -e "s#%h/.carlo-brain/connectors#$CODE_DIR#g" \
    "$CODE_DIR/vault-mcp/carlo-vault-mcp.service" > "$UNITS/carlo-vault-mcp.service"
  cat > "$UNITS/carlo-remote.service" <<UNIT
[Unit]
Description=Claude Code Remote Control session in tmux

[Service]
Type=oneshot
RemainAfterExit=yes
Environment=CARLO_REMOTE_DIR=$VAULT_DIR
ExecStart=/bin/bash $CODE_DIR/remote-control/start_remote.sh start
ExecStop=/bin/bash $CODE_DIR/remote-control/start_remote.sh stop

[Install]
WantedBy=default.target
UNIT
fi

# 6. start
if command -v systemctl >/dev/null 2>&1; then
  run systemctl --user daemon-reload
  run loginctl enable-linger "$USER"
  note "token for the vault MCP: run  bash $CODE_DIR/vault-mcp/rotate_token.sh  once, then:"
  note "systemctl --user enable --now carlo-vault-mcp carlo-remote"
else
  note "no systemd here: run $CODE_DIR/vault-mcp/server.py and start_remote.sh from cron @reboot or tmux"
fi
echo
echo "Next: log in once (run 'claude' interactively), put TLS in front of the MCP port (vault-mcp/Caddyfile.example),"
echo "and install the sync module on this server so the vault stays in step with your laptop."
