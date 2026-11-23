#!/usr/bin/env bash
# Runs after the module code is copied. Idempotent.
set -euo pipefail
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
mkdir -p "$BRAIN/state/logs" "$BRAIN/keys"
chmod 700 "$BRAIN/keys"
