#!/usr/bin/env bash
# The CLI removes hooks and code. State is kept on purpose.
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
echo "review-loop: hooks removed. Kept: $BRAIN/state/review-loop (per session notes, safe to delete) and the review_loop.* config keys."
