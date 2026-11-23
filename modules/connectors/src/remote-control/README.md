# Phone and remote control

Two ways to reach your assistant when you are away from the keyboard. Pick one; they are independent.

| | Claude Code Remote Control | Telegram bridge |
|---|---|---|
| What you get | the same interactive session on your phone (Claude app, claude.ai/code) | one message in, one answer out |
| Setup | one command, tmux | a bot from @BotFather, a config file |
| Strength | full session, approvals from the phone, same context | works from any Telegram client, very light |
| Risk | whoever controls your claude.ai account controls the session | whoever controls your Telegram account controls the bot (mitigated by the allow-list and read-only tools) |
| Status | official feature, check your plan | beta, written here, covered by tests with a fake Telegram |

Platform: both run on macOS and Linux. The machine must be on and online.

## Option 1: Remote Control in tmux

`claude --remote-control [name]` starts an interactive session that you can also open from the Claude
mobile app or claude.ai/code. `start_remote.sh` keeps one running in tmux so it survives closing a
terminal.

```
bash ~/.carlo-brain/connectors/remote-control/start_remote.sh start
bash ~/.carlo-brain/connectors/remote-control/start_remote.sh status
bash ~/.carlo-brain/connectors/remote-control/start_remote.sh attach     # look at it from a terminal
```

Defaults: works in your vault folder (read from `~/.carlo-brain/config.json`, else `$HOME`), session
named `carlo-<hostname>`. Change with `CARLO_REMOTE_DIR`, `CARLO_REMOTE_NAME`, `CARLO_REMOTE_TMUX`.

Start it at boot:

- **Linux server**: add a user systemd unit (`ExecStart=/bin/bash <path>/start_remote.sh start`, `Type=oneshot`, `RemainAfterExit=yes`) and `loginctl enable-linger $USER`, or a cron line `@reboot bash <path>/start_remote.sh start`.
- **macOS**: a launchd job with `RunAtLoad` running the same command.

Details of the feature (plans, limits, how pairing works) change with Claude Code releases:
check `claude --help` and the Claude Code documentation for `--remote-control`.

Rules we recommend: run it on a machine you trust, keep permission prompts on (you answer them from
the phone), and do not give it a folder with secrets.

## Option 2: Telegram bridge (beta)

A message you send to your own private bot runs `claude -p` on your machine in your vault folder and
sends the answer back. Good for "what is on my plate today", "add this to my inbox note", "what did
we decide about X".

Setup:

1. In Telegram talk to @BotFather, `/newbot`, copy the bot credential it gives you.
2. Save it where only you can read it:
   `install -m 600 /dev/null ~/.carlo-brain/keys/telegram_bot_token` then paste it into that file with your editor.
3. Find your own Telegram user id: write one message to the bot, then run
   `python3 ~/.carlo-brain/connectors/remote-control/telegram_bridge.py discover` (prints ids, answers nobody).
4. Create `~/.carlo-brain/config.d/telegram.json`:

```json
{"allowed_user_ids": [123456789], "workdir": "~/vault",
 "allowed_tools": "Read,Grep,Glob,WebSearch,WebFetch", "model": "sonnet"}
```

5. Run it: `python3 ~/.carlo-brain/connectors/remote-control/telegram_bridge.py run` (put that command in tmux, systemd or launchd to keep it alive).

In the chat: any text is a question. `/new` starts a fresh conversation, `/status` shows the settings.

Safety design (all enforced in code and tested):

- Only the ids in `allowed_user_ids`, in private chats. Everyone else is ignored without a reply. An empty list refuses to start.
- The credential is read from a file with mode 600, never from an argument or environment variable, and never appears in error messages.
- `claude -p` runs in a cleaned environment (API key style variables removed, so it uses your subscription login and cannot spend a billed key by accident).
- Default tools are read only (`Read,Grep,Glob,WebSearch,WebFetch`), no shell, no file writes. Add `Write` (and nothing more) if you want it to save notes. Adding `Bash` turns your phone into a shell: do not, unless you accept that risk.
- The audit log (`~/.carlo-brain/state/telegram_bridge.log`) holds time, user id, length and outcome, never the message text.
- The polling offset is saved before a message is handled, so a crash never replays a command.

Risks you accept: Telegram sees your messages (bot chats are not end to end encrypted); anyone who
takes over your Telegram account can talk to your assistant (turn on two step verification); web
pages the assistant reads can contain injected instructions, which is why the default has no write
or shell tools.

## Which one?

Remote Control if you want to really work from the phone. The Telegram bridge if you mostly want to
ask and capture, or your plan does not include Remote Control.
