#!/usr/bin/env bash
# macOS only. Check a night task in the SAME conditions as the real night: as a launchd job.
#
# Why: a task that works from your terminal can fail at night because launchd jobs do not get the
# permissions your terminal has (Desktop, Documents, Downloads, other protected folders; a login that
# expired). This script runs the pre-flight check as a one-shot launchd job and reports its result.
#
#   check_under_launchd.sh NAME            pre-flight check of the task, run by launchd
#   check_under_launchd.sh NAME --claude   also ask claude (cheapest model) to write one file in the task's working folder
#
# Status: syntax checked; it drives launchctl, so run it yourself once on your Mac.
set -u
[ "$(uname)" = "Darwin" ] || { echo "macOS only" >&2; exit 2; }
NAME="${1:?usage: check_under_launchd.sh NAME [--claude]}"
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
CODE="$(cd "$(dirname "$0")" && pwd)"
OUT="$BRAIN/state/night/launchd_check_$NAME.txt"
LABEL="com.carlo-brain.night-check"
PLIST="$BRAIN/state/night/$LABEL.plist"
mkdir -p "$BRAIN/state/night"
rm -f "$OUT"

WANT_CLAUDE=0; [ "${2:-}" = "--claude" ] && WANT_CLAUDE=1
CMD="CARLO_BRAIN_HOME='$BRAIN' python3 -I '$CODE/main.py' check '$NAME' > '$OUT' 2>&1"
if [ "$WANT_CLAUDE" = 1 ]; then
  CMD="$CMD; cd '$BRAIN/data/night/queue/$NAME/work' 2>/dev/null && claude -p --model haiku --permission-mode acceptEdits --allowedTools Write <<< 'Write a file named .night_claude_test containing ok, then reply OK.' >> '$OUT' 2>&1; [ -s .night_claude_test ] && echo 'claude write test: ok' >> '$OUT' || echo 'claude write test: FAILED' >> '$OUT'; rm -f .night_claude_test"
fi

python3 - "$PLIST" "$LABEL" "$CMD" <<'PY'
import plistlib, sys
path, label, command = sys.argv[1:4]
with open(path, "wb") as handle:
    plistlib.dump({"Label": label, "ProgramArguments": ["/bin/bash", "-c", command], "RunAtLoad": True}, handle)
PY

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null
launchctl bootstrap "gui/$(id -u)" "$PLIST" || { echo "launchctl bootstrap failed" >&2; exit 1; }
for _ in $(seq 1 60); do [ -s "$OUT" ] && grep -q . "$OUT" && sleep 3 && break; sleep 2; done
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null
rm -f "$PLIST"
if [ -s "$OUT" ]; then cat "$OUT"; else echo "no result after 2 minutes (the job did not run or could not write $OUT)"; exit 1; fi
