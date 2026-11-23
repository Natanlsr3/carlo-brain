#!/usr/bin/env bash
# Runs after the module code is copied. Idempotent. Creates the vault repository if there is none.
set -euo pipefail
VAULT="${CARLO_VAULT:-}"
if [ -n "$VAULT" ] && [ -d "$VAULT" ] && [ ! -d "$VAULT/.git" ]; then
  git -C "$VAULT" init -b main >/dev/null
  [ -f "$VAULT/.gitignore" ] || printf '.DS_Store\n.obsidian/workspace*\n.obsidian/cache\n.trash/\n' > "$VAULT/.gitignore"
  echo "git repository created in the vault"
fi
