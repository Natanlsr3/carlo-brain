#!/usr/bin/env bash
# Install the whatsapp-mcp bridge (https://github.com/lharries/whatsapp-mcp) next to Carlo Brain.
#
#   install_bridge.sh            clone at a pinned commit, build the Go bridge, register the MCP server
#   install_bridge.sh --service  also write the background service file (after you scanned the QR code)
#
# Installs under ~/.carlo-brain/data/whatsapp-mcp, NOT under the connectors code folder, because
# `carlo add connectors` replaces that folder on upgrade and would delete your paired session
# and message history.
#
# Env: WHATSAPP_MCP_REF  commit or tag to use (default: the pinned commit below, review before bumping)
#      DRY_RUN=1         print what would happen, change nothing
set -eu
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
DEST="$BRAIN/data/whatsapp-mcp"
REF="${WHATSAPP_MCP_REF:-7d6a06dcdce1f01dfb24f60e1030d5efba9f3b88}"
REPO="https://github.com/lharries/whatsapp-mcp.git"
LOGS="$BRAIN/state/logs"

run() { if [ "${DRY_RUN:-0}" = 1 ]; then echo "[dry run] $*"; else "$@"; fi; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1 ($2)" >&2; MISSING=1; }; }

MISSING=0
need git "xcode-select --install"
need go "brew install go, or https://go.dev/dl/"
need uv "curl -LsSf https://astral.sh/uv/install.sh | sh"
[ "$MISSING" = 0 ] || exit 1

if [ ! -d "$DEST/.git" ]; then
  run mkdir -p "$BRAIN/data"
  run git clone "$REPO" "$DEST"
fi
run git -C "$DEST" fetch --quiet origin
run git -C "$DEST" checkout --quiet "$REF"
echo "bridge source at commit $REF"

# CGO is required by the sqlite driver.
if [ "${DRY_RUN:-0}" = 1 ]; then
  echo "[dry run] (cd $DEST/whatsapp-bridge && CGO_ENABLED=1 go build -o whatsapp-bridge .)"
else
  (cd "$DEST/whatsapp-bridge" && CGO_ENABLED=1 go build -o whatsapp-bridge .)
fi

UV="$(command -v uv)"
if command -v claude >/dev/null 2>&1; then
  run claude mcp add whatsapp -s user -- "$UV" --directory "$DEST/whatsapp-mcp-server" run main.py \
    || echo "could not register the MCP server automatically; see README.md"
else
  echo "claude CLI not found: register later with the command in README.md"
fi

cat <<EOF

Next steps
1. Pair your phone: run the bridge in a terminal, scan the QR code with WhatsApp
   (Settings > Linked devices), wait for "Connected", then Ctrl-C.
     $DEST/whatsapp-bridge/whatsapp-bridge
2. Keep it running in the background: $0 --service
EOF

if [ "${1:-}" = "--service" ]; then
  run mkdir -p "$LOGS"
  if [ "$(uname)" = "Darwin" ]; then
    PLIST="$HOME/Library/LaunchAgents/com.carlo-brain.whatsapp-bridge.plist"
    if [ "${DRY_RUN:-0}" = 1 ]; then
      echo "[dry run] would write $PLIST and load it"
    else
      python3 - "$PLIST" "$DEST/whatsapp-bridge" "$LOGS" <<'PY'
import plistlib, sys
plist, workdir, logs = sys.argv[1:4]
data = {
    "Label": "com.carlo-brain.whatsapp-bridge",
    "ProgramArguments": [workdir + "/whatsapp-bridge"],
    "WorkingDirectory": workdir,
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 30,
    "StandardOutPath": logs + "/whatsapp-bridge.out.log",
    "StandardErrorPath": logs + "/whatsapp-bridge.err.log",
}
with open(plist, "wb") as handle:
    plistlib.dump(data, handle)
PY
      launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
      launchctl bootstrap "gui/$(id -u)" "$PLIST"
      echo "service loaded: com.carlo-brain.whatsapp-bridge"
    fi
  else
    echo "Linux: create a systemd user unit that runs $DEST/whatsapp-bridge/whatsapp-bridge with"
    echo "WorkingDirectory=$DEST/whatsapp-bridge and Restart=always (see README.md)."
  fi
fi
