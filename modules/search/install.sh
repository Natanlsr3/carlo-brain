#!/usr/bin/env bash
# Idempotent. The CLI has already copied src/ to $CARLO_MODULE_DIR.
# Here: copy the find-it skill into Claude Code's skills folder without overwriting yours, and write a starter config.
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
CODE="${CARLO_MODULE_DIR:-$BRAIN/search}"
CLAUDE="${CARLO_CLAUDE_DIR:-$HOME/.claude}"
CONF="$BRAIN/config.d/search.json"
DEST="$CLAUDE/skills/find-it"

mkdir -p "$BRAIN/config.d" "$DEST"
if [ ! -f "$CONF" ]; then
  printf '{\n  "folders": ["~/Documents", "~/Desktop", "~/Downloads"],\n  "deny_dirs": [],\n  "deny_files": [],\n  "max_results": 30,\n  "max_per_file": 3,\n  "max_file_kb": 1024,\n  "max_doc_mb": 20,\n  "max_mail_kb": 4096,\n  "deep": true,\n  "cache": false,\n  "time_budget_s": 20\n}\n' > "$CONF"
  chmod 600 "$CONF"
  echo "search: wrote $CONF"
fi
if [ ! -f "$DEST/SKILL.md" ]; then
  cp "$CODE/skills/find-it/SKILL.md" "$DEST/SKILL.md"
  echo "search: installed skill find-it"
elif ! cmp -s "$CODE/skills/find-it/SKILL.md" "$DEST/SKILL.md"; then
  cp "$CODE/skills/find-it/SKILL.md" "$DEST/SKILL.md.new"
  echo "search: kept your find-it skill, ours is saved as SKILL.md.new"
fi
echo "search: try it with: carlo search \"some words\""
