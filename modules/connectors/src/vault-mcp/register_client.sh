#!/usr/bin/env bash
# Register (or re-register) the vault MCP server in Claude Code on a client machine.
#   register_client.sh <token-file> <url>
# The token is read from a file you copied over a safe channel (scp, a password manager export).
# Note: `claude mcp add` takes the header as an argument, so the token is visible in this
# process's argument list for a moment. Run it on a machine you trust.
set -eu
TOKEN_FILE="${1:?usage: register_client.sh <token-file> <url>}"
URL="${2:-${VAULT_MCP_URL:-}}"
[ -s "$TOKEN_FILE" ] || { echo "token file missing or empty: $TOKEN_FILE" >&2; exit 1; }
[ -n "$URL" ] || { echo "pass the server URL (https://your-host/mcp) or set VAULT_MCP_URL" >&2; exit 1; }
TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
claude mcp remove vault -s user >/dev/null 2>&1 || true
claude mcp add --transport http -s user vault "$URL" --header "Authorization: Bearer $TOKEN" >/dev/null
unset TOKEN
echo "vault MCP registered at $URL"
