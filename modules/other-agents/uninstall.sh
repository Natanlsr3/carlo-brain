#!/usr/bin/env bash
# Take our block, hooks and exported prompts out of Codex and Gemini before the module code is removed.
# Backups of every file touched stay next to it (<name>.bak-carlo-<time>). Never fails the removal.
CODE="${CARLO_MODULE_DIR:-${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}/other-agents}"
python3 -I "$CODE/agents_connect.py" remove-all || true
exit 0
