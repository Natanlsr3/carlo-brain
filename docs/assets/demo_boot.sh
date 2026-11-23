#!/usr/bin/env bash
# Demo for docs/assets/boot.tape: prints a FAKE boot briefing (generic names only). Calls nothing, reads nothing.
set -eu
dim=$'\033[2m'; ok=$'\033[32m'; amber=$'\033[33m'; bold=$'\033[1m'; off=$'\033[0m'
say() { printf '%s\n' "$1"; sleep "${2:-0.45}"; }

say "${dim}SessionStart hook: memory ran, 2 signals, 4 log entries, health ok${off}" 0.9
echo
say "${ok}Ready.${off} Yesterday you were on the pricing page, tests still red on checkout." 0.9
echo
say "1. Sam replied about the invoice. Draft ready."
say "2. You asked Alex for the contract 4 days ago. No answer. Nudge drafted."
say "3. Thursday 15:00 slot agreed in the team chat, not in your calendar."
say "4. Overnight: the weekly research digest finished (3 of 3 steps)."
say "5. 2 facts from last session wait for your yes or no." 0.8
echo
say "${bold}${amber}Send the reply to Sam? (go / let me look)${off}" 1
printf '%s' "> "
sleep 2
