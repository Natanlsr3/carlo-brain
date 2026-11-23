#!/usr/bin/env bash
# Idempotent. The CLI has already copied src/ to $CARLO_MODULE_DIR and merged the hook.
# Here: create the starter config if there is none (never overwrites) and the boot drop-in folder.
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
CODE="${CARLO_MODULE_DIR:-$BRAIN/proactive}"
CONF="$BRAIN/config.d/proactive.json"

mkdir -p "$BRAIN/config.d" "$BRAIN/state/proactive" "$BRAIN/state/boot.d"
if [ ! -f "$CONF" ]; then
  cp "$CODE/config.example.json" "$CONF"
  chmod 600 "$CONF"
  echo "proactive: wrote $CONF (every source is OFF; edit identity, then enable what you want)"
else
  echo "proactive: kept existing $CONF"
fi
echo "proactive: check access with: python3 -I $CODE/run.py doctor"
