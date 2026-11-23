#!/usr/bin/env bash
# Create the long-lived token for scheduled jobs. Run it yourself in a terminal (it needs your browser).
#   1. `claude setup-token` opens the browser; approve, and copy the token it prints.
#   2. Paste it here (nothing is echoed). It is saved with mode 600, only you can read it.
# Renew every year; `claude auth status --text` shows when a stored login ends.
set -eu
FILE="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}/keys/claude_oauth_token"
command -v claude >/dev/null 2>&1 || { echo "claude CLI not found" >&2; exit 1; }
echo "1) Approve in the browser, then copy the token that is printed."
claude setup-token
echo
printf "2) Paste the token and press Enter (hidden): "
read -rs TOKEN
echo
case "$TOKEN" in
  sk-ant-*) ;;
  *) echo "That does not look like a Claude token, nothing was written." >&2; exit 1 ;;
esac
mkdir -p "$(dirname "$FILE")"
umask 077
printf '%s' "$TOKEN" > "$FILE"
unset TOKEN
chmod 600 "$FILE"
echo "Saved to $FILE (mode 600). Scheduled jobs pick it up through auth_env.sh."
