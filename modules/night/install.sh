#!/usr/bin/env bash
# Idempotent. The CLI already copied src/ to $CARLO_MODULE_DIR and merged the hook and the scheduler job.
# Here: create the queue folders (outside the code folder, so upgrades never delete your tasks) and
# leave an example task you can copy.
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
CODE="${CARLO_MODULE_DIR:-$BRAIN/night}"
mkdir -p "$BRAIN/data/night/queue" "$BRAIN/data/night/done" "$BRAIN/state/night/logs" "$BRAIN/config.d"
chmod +x "$CODE/check_under_launchd.sh" 2>/dev/null || true
echo "night: queue is $BRAIN/data/night/queue (empty: nothing runs until you add a task)"
echo "night: example task to copy: $CODE/example_task/"
echo "night: add one with: python3 -I $CODE/main.py add 01_my_task --prompt-file my_prompt.md --steps 3"
echo "night: unattended runs need a login that does not expire overnight: see the self-improve module, create_token.sh"
