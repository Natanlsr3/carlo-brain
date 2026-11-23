#!/usr/bin/env bash
# Idempotent. The CLI already copied src/ to $CARLO_MODULE_DIR. Nothing is wired into Codex or Gemini here:
# that is `carlo connect codex` / `carlo connect gemini`, which you run when you want it.
set -eu
CODE="${CARLO_MODULE_DIR:-${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}/other-agents}"
chmod +x "$CODE"/*.py 2>/dev/null || true
echo "other-agents: installed. Next:  carlo connect codex   or   carlo connect gemini   (any other LLM: carlo context --copy)"
