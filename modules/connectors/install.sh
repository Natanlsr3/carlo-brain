#!/usr/bin/env bash
# Idempotent. The CLI already copied src/ to $CARLO_MODULE_DIR. Here: make scripts executable and
# create the folders other parts expect. Nothing is registered or started: each connector has its own
# guide, and you decide which to turn on.
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
CODE="${CARLO_MODULE_DIR:-$BRAIN/connectors}"
mkdir -p "$BRAIN/data" "$BRAIN/config.d" "$BRAIN/keys" "$BRAIN/state"
chmod 700 "$BRAIN/keys"
find "$CODE" -name '*.sh' -exec chmod +x {} + 2>/dev/null || true
echo "connectors: installed. See what works here:  python3 $CODE/connect.py doctor --no-mcp"
echo "connectors: guides are in $CODE/<connector>/README.md (python3 $CODE/connect.py list)"
