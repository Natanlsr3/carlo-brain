#!/usr/bin/env bash
# Idempotent. The CLI already copied src/ to $CARLO_MODULE_DIR. Here: copy the agents and skills into
# Claude Code's folders (~/.claude, or $CARLO_CLAUDE_DIR) without overwriting anything of yours.
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
CODE="${CARLO_MODULE_DIR:-$BRAIN/agents-skills}"
chmod +x "$CODE/scripts/"*.sh 2>/dev/null || true
CARLO_BRAIN_HOME="$BRAIN" python3 -I "$CODE/install_agents.py" install
echo "agents-skills: see what is installed with: python3 -I $CODE/install_agents.py status"
echo "agents-skills: video-quiz needs yt-dlp, ffmpeg, whisper-cli and a model file (see the README)"
