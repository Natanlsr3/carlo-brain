#!/usr/bin/env bash
# Carlo Brain installer. Checks dependencies, then runs `carlo init`.
# Usage: ./install.sh [--vault DIR] [--name NAME] [--user NAME] [--modules a,b|none] [--yes] [--force]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required (3.9 or newer)." >&2
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "python3 3.9 or newer is required (found $(python3 --version))." >&2
  exit 1
fi
command -v git >/dev/null 2>&1 || echo "note: git not found (only the sync module needs it)."
command -v claude >/dev/null 2>&1 || echo "note: the 'claude' CLI was not found; install Claude Code to use the hooks."

exec python3 "$HERE/carlo" init "$@"
