#!/usr/bin/env bash
# The CLI removes the code, the hook and the scheduler job. Left on purpose: your task list and settings
# (config.d), the change journal and archives (state/self-improve), reports in your vault, the token file.
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
rm -f "$BRAIN/state/boot.d/self-improve.md"
echo "self-improve: removed the boot note. Kept: $BRAIN/config.d, $BRAIN/state/self-improve (journal, backups, bench results), reports in your vault."
echo "Backups of every automatic change are in $BRAIN/state/self-improve/archives; delete them yourself when you no longer need them."
