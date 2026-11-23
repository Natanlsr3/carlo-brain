#!/usr/bin/env bash
# Weekly LLM triage pass over the raw message dump (optional, uses your Claude subscription).
# Reads  $STATE/raw_messages.md (set sources.whatsapp.write_raw = true) and $STATE/digest.md
# Writes $STATE/triage/TRIAGE_<date>.md. Never sends anything: the prompt forbids it and the
# allowed tools are read/write files only.
# Env: CARLO_BRAIN_HOME, CLAUDE_BIN (default claude), CARLO_KEEP_API_KEYS=1 to keep API keys in the env.
set -u
BRAIN="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}"
STATE="$BRAIN/state/proactive"
CODE="$(cd "$(dirname "$0")" && pwd)"
CLAUDE="${CLAUDE_BIN:-claude}"
DATE="$(date +%F)"
OUT="$STATE/triage/TRIAGE_$DATE.md"
LOG="$STATE/triage.log"
mkdir -p "$STATE/triage"

log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

# Background jobs use the subscription, never a billed API key by accident.
strip_args=()
if [ -z "${CARLO_KEEP_API_KEYS:-}" ]; then
  for v in $(compgen -e); do
    if [[ "$v" =~ (API_KEY|_KEY$|SECRET|PASSWORD|PASSWD) && "$v" != CLAUDE_CODE_OAUTH_TOKEN ]]; then
      strip_args+=(-u "$v")
    fi
  done
fi

[ -s "$STATE/raw_messages.md" ] || { log "no raw_messages.md (enable sources.whatsapp.write_raw and run a scan)"; echo "no raw dump to triage" >&2; exit 78; }
command -v "$CLAUDE" >/dev/null || { log "claude not found"; exit 127; }

PROMPT="$(sed -e "s#{DATE}#$DATE#g" -e "s#{STATE}#$STATE#g" -e "s#{OUT}#$OUT#g" "$CODE/prompt_triage.md")"
[ "${DRY_RUN:-0}" = 1 ] && { echo "DRY_RUN: prompt ${#PROMPT} chars, output $OUT"; exit 0; }

cd "$STATE" || exit 1
env ${strip_args[@]+"${strip_args[@]}"} "$CLAUDE" -p "$PROMPT" --model sonnet --permission-mode acceptEdits \
  --add-dir "$STATE" --allowedTools "Read,Grep,Glob,Write" >> "$LOG" 2>&1
code=$?
# Judge the result, not the exit code: the report must exist.
if [ -s "$OUT" ]; then log "ok $OUT"; exit 0; fi
log "failed: no report (claude exit $code)"; exit 1
