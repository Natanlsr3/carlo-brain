#!/usr/bin/env bash
# Removes the boot signal. Your config and the catch-up markers are kept on purpose.
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
if grep -q "carlo-brain:health" "$BRAIN/state/boot.d/health.md" 2>/dev/null; then
  rm -f "$BRAIN/state/boot.d/health.md"
fi
echo "health: removed boot signal; config.d/health.json and state/health kept"
