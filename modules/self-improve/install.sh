#!/usr/bin/env bash
# Idempotent. The CLI already copied src/ to $CARLO_MODULE_DIR and merged the hook. Here: create the
# starter task list and settings in config.d if you have none (never overwrites), and the key folder.
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
CODE="${CARLO_MODULE_DIR:-$BRAIN/self-improve}"
mkdir -p "$BRAIN/config.d" "$BRAIN/keys" "$BRAIN/state/self-improve"
chmod 700 "$BRAIN/keys"
chmod +x "$CODE/create_token.sh" 2>/dev/null || true
CARLO_BRAIN_HOME="$BRAIN" python3 -I "$CODE/main.py" init
echo "self-improve: the weekly jobs are listed in $BRAIN/config.d/self-improve-tasks.json"
echo "self-improve: they need a login that works unattended: run $CODE/create_token.sh once (see the README)"
echo "self-improve: try without spending anything: python3 -I $CODE/main.py job scout --dry-run"
