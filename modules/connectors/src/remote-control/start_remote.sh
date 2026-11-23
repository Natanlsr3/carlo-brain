#!/usr/bin/env bash
# Keep a Claude Code session with Remote Control running in tmux, so you can continue it from
# your phone (Claude app or claude.ai/code).
#
#   start_remote.sh start    create the tmux session if it is not running
#   start_remote.sh stop     end it
#   start_remote.sh status   running or not
#   start_remote.sh attach   look at it from a terminal
#
# Env: CARLO_REMOTE_DIR   folder the session works in (default: your vault, or $HOME)
#      CARLO_REMOTE_NAME  session name shown in the app (default: carlo-<hostname>)
#      CARLO_REMOTE_TMUX  tmux session name (default: carlo)
#      CLAUDE_BIN         claude command (default: claude)
# Background sessions use your subscription login: API key variables are removed from the environment
# (set CARLO_KEEP_API_KEYS=1 to keep them).
set -eu
SESSION="${CARLO_REMOTE_TMUX:-carlo}"
NAME="${CARLO_REMOTE_NAME:-carlo-$(hostname -s)}"
CLAUDE="${CLAUDE_BIN:-claude}"
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
DIR="${CARLO_REMOTE_DIR:-}"
if [ -z "$DIR" ]; then
  DIR="$(python3 -c 'import json,os,sys
p=os.path.join(sys.argv[1],"config.json")
try: print(os.path.expanduser(json.load(open(p)).get("vault","")))
except Exception: pass' "$BRAIN" 2>/dev/null)"
  [ -n "$DIR" ] && [ -d "$DIR" ] || DIR="$HOME"
fi

strip=()
if [ -z "${CARLO_KEEP_API_KEYS:-}" ]; then
  for v in $(compgen -e); do
    if [[ "$v" =~ (API_KEY|_KEY$|SECRET|PASSWORD|PASSWD) && "$v" != CLAUDE_CODE_OAUTH_TOKEN ]]; then strip+=(-u "$v"); fi
  done
fi

running() { tmux has-session -t "$SESSION" 2>/dev/null; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1" >&2; exit 1; }; }

case "${1:-status}" in
  start)
    need tmux; need "$CLAUDE"
    if running; then echo "already running (tmux session $SESSION)"; exit 0; fi
    tmux new-session -d -s "$SESSION" -c "$DIR" "env ${strip[*]:-} $CLAUDE --remote-control '$NAME'"
    echo "started in $DIR as '$NAME'. Open the Claude app or claude.ai/code and look for that session."
    ;;
  stop)
    running && tmux kill-session -t "$SESSION" && echo "stopped" || echo "not running"
    ;;
  status)
    if running; then echo "running (tmux session $SESSION)"; else echo "not running"; exit 1; fi
    ;;
  attach)
    need tmux; exec tmux attach -t "$SESSION"
    ;;
  *)
    echo "usage: start_remote.sh start|stop|status|attach" >&2; exit 2
    ;;
esac
