#!/usr/bin/env bash
# Idempotent. The CLI already copied src/ and merged the hooks. Only checks that the reviewer agent exists.
set -eu
CLAUDE_DIR="${CARLO_CLAUDE_DIR:-$HOME/.claude}"
if [ ! -f "$CLAUDE_DIR/agents/reviewer.md" ]; then
  echo "review-loop: the reviewer agent is not installed. Run:  carlo add agents-skills"
fi
echo "review-loop: on. Turn it off any time:  carlo config set review_loop.enabled false"
