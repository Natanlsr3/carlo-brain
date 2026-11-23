#!/usr/bin/env bash
# Rotate the vault MCP bearer token (run on the machine that hosts server.py).
# Writes a new random token to the token file (chmod 600), keeps one dated backup of the old one,
# restarts the service if it is managed by systemd or launchd. The token is never printed.
#
# Env: VAULT_MCP_TOKEN_FILE  (default ~/.carlo-brain/keys/vault_mcp_token)
#      VAULT_MCP_SERVICE     systemd user unit name (default carlo-vault-mcp)
set -eu
FILE="${VAULT_MCP_TOKEN_FILE:-${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}/keys/vault_mcp_token}"
SERVICE="${VAULT_MCP_SERVICE:-carlo-vault-mcp}"
mkdir -p "$(dirname "$FILE")"
umask 077
if [ -s "$FILE" ]; then cp "$FILE" "$FILE.bak-$(date +%Y%m%d-%H%M)"; fi
python3 -c 'import secrets,sys; sys.stdout.write(secrets.token_urlsafe(32))' > "$FILE.new"
mv "$FILE.new" "$FILE"
chmod 600 "$FILE"
echo "new token written to $FILE (old one kept as .bak-*, delete it once clients work)"

if command -v systemctl >/dev/null 2>&1 && systemctl --user is-enabled "$SERVICE" >/dev/null 2>&1; then
  systemctl --user restart "$SERVICE" && echo "restarted systemd unit $SERVICE"
elif [ "$(uname)" = "Darwin" ] && launchctl list 2>/dev/null | grep -q "com.carlo-brain.vault-mcp"; then
  launchctl kickstart -k "gui/$(id -u)/com.carlo-brain.vault-mcp" && echo "restarted launchd job"
else
  echo "restart server.py yourself so it reads the new token"
fi
echo "now update each client: bash register_client.sh <path to a file holding the new token>"
