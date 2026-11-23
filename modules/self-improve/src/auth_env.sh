# Source this from scheduled scripts that run `claude -p`.
# Why: a background job cannot open a browser, and the normal login can expire overnight. A long-lived
# token made by `claude setup-token` (create_token.sh) lets scheduled runs use your subscription.
# Limits (from Claude Code's documentation): that token can only make model requests. It cannot start
# Remote Control sessions and cannot reach claude.ai connectors (Gmail, Calendar, ...); connectors you
# configured locally (for example the WhatsApp MCP) still work. It lasts one year: renew it.
# The token is never printed.
_carlo_token_file="${CARLO_BRAIN_HOME:-$HOME/.carlo-brain}/keys/claude_oauth_token"
if [ -s "$_carlo_token_file" ]; then
  CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '[:space:]' < "$_carlo_token_file")"
  export CLAUDE_CODE_OAUTH_TOKEN
fi
unset _carlo_token_file
