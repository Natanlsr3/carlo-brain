#!/usr/bin/env bash
# The CLI removes the module code. This only tells you what is left on purpose.
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
echo "connectors: code removed. Kept on purpose (delete by hand if you want them gone):"
echo "  $BRAIN/data         WhatsApp pairing and message history, if you installed the bridge"
echo "  $BRAIN/keys         key files (vault MCP token, Telegram bot token)"
echo "  $BRAIN/config.d     your settings"
echo "MCP servers registered with Claude Code stay registered: claude mcp remove <name> -s user"
echo "Background services you started (WhatsApp bridge, vault MCP, remote session) keep running until you stop them."
