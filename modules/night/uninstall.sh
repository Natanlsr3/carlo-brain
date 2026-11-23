#!/usr/bin/env bash
# The CLI removes the code, the hook and the scheduler job. Your queue, finished tasks, logs and the report stay.
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
rm -f "$BRAIN/state/boot.d/night.md"
echo "night: removed the boot note. Kept: $BRAIN/data/night (queue, done, marathon), $BRAIN/state/night (logs, report)."
