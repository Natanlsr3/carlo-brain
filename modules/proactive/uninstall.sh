#!/usr/bin/env bash
# Removes the boot drop-in. Your config and state (follow-up memory, briefings) are kept on purpose:
# delete ~/.carlo-brain/config.d/proactive.json and ~/.carlo-brain/state/proactive yourself to wipe them.
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
rm -f "$BRAIN/state/boot.d/proactive.md"
echo "proactive: removed boot signal; config and state kept"
