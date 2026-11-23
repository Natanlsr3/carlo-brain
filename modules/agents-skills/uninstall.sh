#!/usr/bin/env bash
# Called before the code folder is deleted: remove the agents and skills we installed, keep the ones you edited.
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
CODE="${CARLO_MODULE_DIR:-$BRAIN/agents-skills}"
if [ -f "$CODE/install_agents.py" ]; then
  CARLO_BRAIN_HOME="$BRAIN" python3 -I "$CODE/install_agents.py" uninstall
else
  echo "agents-skills: installer not found, nothing removed from the Claude folders"
fi
