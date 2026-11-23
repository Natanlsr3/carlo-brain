# OpenRouter and other model providers (beta)

Send a task to a model that is not Claude, through any OpenAI-compatible endpoint: OpenRouter by default,
or another provider, or a local server. Use it when you want a cheaper model for a bulk job, a second
opinion from a different model family, or a fallback when Claude is unavailable.

Status: **beta**. One small script, tested with the HTTP call mocked; never tested against a real provider by this project.

## Setup

```bash
printf '%s' 'YOUR_KEY' > ~/.carlo-brain/keys/openrouter && chmod 600 ~/.carlo-brain/keys/openrouter
python3 -I ~/.carlo-brain/connectors/openrouter/openrouter_ask.py --model <model id> "Summarise: ..."
echo "long text" | python3 -I ~/.carlo-brain/connectors/openrouter/openrouter_ask.py --model <model id> --system "Answer in 3 lines"
```

- The key is read from `$OPENROUTER_KEY_FILE`, else `~/.carlo-brain/keys/openrouter`. It is never an argument, never printed, and the script refuses a file readable by others. Do not paste the key in a chat with the assistant: create the file yourself.
- Another provider or a local server: `--base-url https://other.example/v1` (or `OPENAI_COMPAT_BASE_URL`). Plain `http` is accepted only for localhost.
- Model ids are the provider's own (see their model list). Pin the one you tested.

## Routing a subagent to it

Claude Code subagents run on Claude models. To hand a task to another model, give a subagent the one command above and nothing else that can write. A minimal agent in `~/.claude/agents/second-opinion.md`:

```markdown
---
name: second-opinion
description: "Use when the user asks for a second opinion or a bulk summary from a non-Claude model. Sends only the text you pass it."
tools: Bash
model: haiku
---
Write the text to send to a temporary file, then run
`python3 -I ~/.carlo-brain/connectors/openrouter/openrouter_ask.py --model <model id> < <file>`
and return the answer. Never include secrets, mail or chat content the user did not ask you to send.
```

## Automatic routing (beta)

`route.py` picks the model for you from a small config and falls back to Claude when the other provider fails. Create `~/.carlo-brain/config.d/routing.json`:

```json
{"default": "claude",
 "agents": {"bulk-worker": "openrouter:<model id>"},
 "kinds": {"summarise": "openrouter:<model id>", "classify": "openrouter:<model id>", "translate": "openrouter:<model id>"},
 "fallback": "claude"}
```

Lookup order: agent name, then task kind, then `default`. A target is `claude` or `openrouter:<model id>`; anything else is ignored. No file means everything stays on Claude.

```bash
python3 -I ~/.carlo-brain/connectors/openrouter/route.py resolve --kind summarise      # prints the target
python3 -I ~/.carlo-brain/connectors/openrouter/route.py ask --kind summarise --system "3 lines" < text.txt
```

On a missing key, an HTTP error or a bad answer, the same prompt runs on Claude (`claude -p` with every key-like variable stripped, so your login is used) and a `route:` line on stderr says so. Set `"fallback": "none"` to fail instead.

**How an agent opts in.** Copy `agent_routed.example.md` to `~/.claude/agents/<name>.md` (`tools: Bash` only) and put your agent name or task kinds in the config. The agent writes the text to a file and calls `route.py ask --agent <name> --kind <kind>`. Agents that do not call it are unchanged: they run on Claude. Bulk or cheap jobs only: the text leaves your machine for the routed provider.

Limits: see the next section for what Claude Code allows, the answer is text only, and a fallback to Claude spends your Claude usage.

## Applying routing.json inside Claude Code (`carlo route`, beta)

Claude Code subagent files accept a `model:` field (`sonnet`, `opus`, `haiku`, `inherit` or a full model id). `carlo route sync` writes it for you and generates wrappers for other providers:

```json
{"agents": {"researcher": "claude:haiku", "reader": "openrouter:<model id>"},
 "kinds": {"summarise": "openrouter:<model id>"}}
```

```bash
carlo route status          # each agent, its target, synced or not
carlo route sync            # apply (idempotent)
carlo route sync --undo     # restore the original model fields, remove wrappers and the routing skill
```

- `claude:<tier>`: the `model:` line of `~/.claude/agents/<name>.md` is set, nothing else in the file changes. The first original is saved in `~/.carlo-brain/state/route-sync/backup/`, and undo puts the previous value back (or removes the line if there was none). An entry removed from `routing.json` is reverted at the next sync.
- `openrouter:<model>`: `<name>-routed.md` is generated with `tools: Bash` only. It runs `route.py ask --agent <name> --system-file <role>` where the role file is the body of the original agent (or a generic line if it is not installed). The original agent is untouched.
- A skill `carlo-routing` (generated, removed by undo) tells the assistant to prefer the `-routed` agent for text work, and `route.py ask --kind <kind>` for the kinds sent to another model.
- Only agents named in `routing.json` are touched. Files of yours with the same name as a wrapper or the skill are never overwritten. `carlo doctor` warns when `routing.json` and the installed agents disagree.

Limits: Claude Code cannot swap a model by itself, so a non-Claude model runs only when the assistant picks the routed agent (the skill nudges it, nothing forces it). A wrapper is text in, text out: none of the original agent's tools. `CLAUDE_CODE_SUBAGENT_MODEL` or a per-call model parameter can override the `model:` field (precedence in the Claude Code docs). After a sync, the `agents-skills` installer sees the edited file as yours and keeps it (its version goes to `.new`): re-run `carlo route sync` after changing agents or `routing.json`.

## Rules and risks

- Everything you send goes to that provider, under its terms. The `security` send guard only recognises mail, chat and `curl` POST calls, so it does not scan what this script sends: keep personal data out.
- Unattended jobs (night, self-improve) do not use it. Their calls are `claude -p` with a stripped environment.
- It returns text only. It cannot use your tools, read your vault or act on your behalf.
