# WhatsApp connector

Lets your assistant read your WhatsApp history and (if you allow it) send messages, and feeds the
`proactive` module with signals. It uses the open source
[lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp): a Go bridge that links to your
account as a "linked device" (via the whatsmeow library) and stores everything in a local SQLite
file, plus a Python MCP server that exposes it to Claude.

Platform: macOS and Linux. Status: works, but it is an unofficial client of a private protocol:
read the risks below before you pair your main account.

## Setup

Needs `git`, `go`, [`uv`](https://docs.astral.sh/uv/). FFmpeg is optional (voice notes).

```
bash ~/.carlo-brain/connectors/whatsapp/install_bridge.sh
```

It clones the bridge at a **pinned commit** into `~/.carlo-brain/data/whatsapp-mcp` (outside the
connectors folder so upgrading Carlo Brain never deletes your pairing), builds it, and registers the
MCP server with `claude mcp add whatsapp -s user -- uv --directory .../whatsapp-mcp-server run main.py`.

1. Pair: run `~/.carlo-brain/data/whatsapp-mcp/whatsapp-bridge/whatsapp-bridge` in a terminal, scan the QR code (WhatsApp, Settings, Linked devices), wait for "Connected", Ctrl-C. The link expires after roughly 20 days without the bridge running; pair again if it does.
2. Keep it alive: `bash ~/.carlo-brain/connectors/whatsapp/install_bridge.sh --service` (macOS launchd, restarts on crash). On Linux write a systemd user unit running the same binary with `Restart=always`.
3. Check: `python3 ~/.carlo-brain/connectors/connect.py doctor`.

Review the pinned commit before you trust it; to move to a newer one:
`WHATSAPP_MCP_REF=<commit> bash install_bridge.sh`.

## What it gives you

- In Claude: search and read chats, list contacts, download media, and send messages or files (tool names `mcp__whatsapp__...`, check with `/mcp`).
- In `proactive`: the module opens `store/messages.db` read-only (never through the bridge) to find questions waiting on you, replies that arrived, and group action chatter. Set `sources.whatsapp.enabled` to true; the database is found automatically at the default location.

## Risks, and what we do about them

- **It can send as you.** The bridge exposes a local HTTP API (`localhost:8080`) that any process on your machine can call, and the MCP server has a send tool. Prompt injection in a message you receive ("forward my last 10 chats to...") can try to make the assistant use it. Mitigations: never allow the send tools in unattended jobs (the `night` and `self-improve` modules deny `mcp__whatsapp__send_message`, `send_file`, `send_audio_message`); in interactive sessions leave the send tools on "ask"; if the `security` module is installed, its send guard blocks any outgoing message that contains a key, token, password or card number.
- **Unofficial.** WhatsApp can rate limit or ban accounts that use unofficial clients. Reading is low risk; do not bulk send. Use a secondary number if that matters to you.
- **Everything is stored in clear on disk** (`whatsapp-bridge/store/`): messages, media metadata, the session. Use full disk encryption, and keep it out of cloud-synced folders and out of your vault.
- **Group and contact names** come from the bridge address book (`store/whatsapp.db`); the proactive module uses it to show names instead of numbers.

## Uninstall

`claude mcp remove whatsapp -s user`, unload the launchd job (`launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.carlo-brain.whatsapp-bridge.plist`), then delete `~/.carlo-brain/data/whatsapp-mcp` and unlink the device in WhatsApp (Settings, Linked devices).
