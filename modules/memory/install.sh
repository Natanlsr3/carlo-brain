#!/usr/bin/env bash
# Runs after the module code is copied to $CARLO_MODULE_DIR. Idempotent.
set -euo pipefail
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
mkdir -p "$BRAIN/state/boot.d" "$BRAIN/state/runs" "$BRAIN/state/logs" "$BRAIN/state/compactions"
