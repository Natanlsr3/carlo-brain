#!/usr/bin/env bash
# Removes the find-it skill only if it is still the shipped one. Config is kept.
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
CODE="${CARLO_MODULE_DIR:-$BRAIN/search}"
CLAUDE="${CARLO_CLAUDE_DIR:-$HOME/.claude}"
DEST="$CLAUDE/skills/find-it"
if [ -f "$DEST/SKILL.md" ] && [ -f "$CODE/skills/find-it/SKILL.md" ] && cmp -s "$CODE/skills/find-it/SKILL.md" "$DEST/SKILL.md"; then
  rm -f "$DEST/SKILL.md"
  rmdir "$DEST" 2>/dev/null || true
fi
echo "search: removed the shipped skill; config.d/search.json kept"
