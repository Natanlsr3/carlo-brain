#!/usr/bin/env bash
# Idempotent. The CLI has already copied src/ to $CARLO_MODULE_DIR and merged the hook.
# Here: create the state folders and a starter config if there is none (never overwrites).
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
CONF="$BRAIN/config.d/health.json"

mkdir -p "$BRAIN/config.d" "$BRAIN/state/health" "$BRAIN/state/boot.d"
if [ ! -f "$CONF" ]; then
  printf '{\n  "ignore": [],\n  "jobs": [],\n  "files": [],\n  "expect_mcp": [],\n  "catchup": true,\n  "catchup_retry_h": 6,\n  "repair": {"enabled": true, "max_log_mb": 10, "mcp_commands": {}}\n}\n' > "$CONF"
  chmod 600 "$CONF"
  echo "health: wrote $CONF"
else
  echo "health: kept existing $CONF"
fi
echo "health: see the status with: carlo health status   (carlo doctor shows the checks; carlo health repair --dry-run shows what would be fixed)"
