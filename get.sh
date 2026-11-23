#!/usr/bin/env bash
# Carlo Brain one-line installer:
#   curl -fsSL https://raw.githubusercontent.com/Natanlsr3/carlo-brain/main/get.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/Natanlsr3/carlo-brain/main/get.sh | bash -s -- --vault ~/notes
# Clones (or updates) the repo in ~/carlo-brain, then runs ./install.sh --yes. No sudo, never overwrites a folder that
# is not a git checkout. Overrides: CARLO_BRAIN_DIR (where to clone), CARLO_BRAIN_REPO (where to clone from).
set -euo pipefail

REPO="${CARLO_BRAIN_REPO:-https://github.com/Natanlsr3/carlo-brain}"
DIR="${CARLO_BRAIN_DIR:-$HOME/carlo-brain}"

fail() { echo "carlo-brain: $*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || fail "git is required. Install it (macOS: xcode-select --install; Debian/Ubuntu: sudo apt install git), then run this again."
command -v python3 >/dev/null 2>&1 || fail "python3 3.9 or newer is required. Install it from https://www.python.org/downloads/ then run this again."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || fail "python3 3.9 or newer is required (found $(python3 --version 2>&1))."
command -v claude >/dev/null 2>&1 \
  || echo "note: the 'claude' command was not found. Install Claude Code (https://docs.claude.com/en/docs/claude-code) and log in before the last step."

if [ -d "$DIR/.git" ]; then
  echo "Updating $DIR"
  git -C "$DIR" pull --ff-only || fail "could not update $DIR (local changes?). Fix it or set CARLO_BRAIN_DIR to another folder."
elif [ -e "$DIR" ]; then
  fail "$DIR exists and is not a git checkout. Move it, or set CARLO_BRAIN_DIR to another folder."
else
  echo "Cloning into $DIR"
  git clone --quiet "$REPO" "$DIR" || fail "git clone failed ($REPO)."
fi

cd "$DIR"
if [ "$#" -gt 0 ]; then
  ./install.sh --yes "$@"
else
  ./install.sh --yes --vault "$HOME/carlo-vault"
fi

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *)
    echo
    echo "Add carlo to your PATH (once), then open a new terminal (use ~/.bashrc instead of ~/.zshrc if you use bash):"
    echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
    ;;
esac

echo
echo "Next: run claude and type: setup (it maps your computer while it asks you a few questions)"
