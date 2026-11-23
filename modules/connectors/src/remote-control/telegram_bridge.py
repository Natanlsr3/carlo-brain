#!/usr/bin/env python3
"""Talk to your assistant from Telegram (beta). Python stdlib only.

A message from YOU to YOUR private bot runs `claude -p` on your machine in your vault folder and
the answer comes back as a message. Meant for quick questions and notes from the phone.

Safety design (read the README before enabling):
- Only the Telegram user ids listed in allowed_user_ids are served, private chats only. Everyone else is ignored silently.
  An empty list refuses to start.
- The bot token is read from a file (TELEGRAM_BOT_TOKEN_FILE), never from an argument or the environment.
- `claude -p` runs with a short allow-list of tools (default: read only, no shell) and a clean environment (API key variables removed).
- Message contents are never written to the log: only time, user id, length and outcome.

Config: ~/.carlo-brain/config.d/telegram.json
  {"allowed_user_ids": [123456789], "workdir": "~/vault", "allowed_tools": "Read,Grep,Glob,WebSearch,WebFetch",
   "model": "sonnet", "timeout": 300, "max_reply_chars": 3500, "keep_session": true}

Usage:
  telegram_bridge.py discover   print the user ids that wrote to the bot (to fill allowed_user_ids), then exit
  telegram_bridge.py run        serve forever (Ctrl-C to stop)
Chat commands: /new starts a fresh conversation, /status shows the settings in use.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

API = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")
SENSITIVE_ENV = re.compile(r"(API_KEY|_KEY$|SECRET|PASSWORD|PASSWD|BOT_TOKEN)", re.I)
KEEP_ENV = {"CLAUDE_CODE_OAUTH_TOKEN"}
DEFAULTS: Dict[str, Any] = {
    "allowed_user_ids": [],
    "workdir": "~",
    "allowed_tools": "Read,Grep,Glob,WebSearch,WebFetch",
    "model": "sonnet",
    "timeout": 300,
    "max_reply_chars": 3500,
    "keep_session": True,
    "claude_bin": "claude",
}


def brain_home() -> Path:
    return Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain")


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Config file over defaults. Raises ValueError for a missing allow-list or wrong types."""
    path = path or brain_home() / "config.d" / "telegram.json"
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as err:
        raise ValueError(f"cannot read {path}: {err}") from err
    ids = cfg["allowed_user_ids"]
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise ValueError("allowed_user_ids must be a list of integers")
    if not isinstance(cfg["timeout"], int) or cfg["timeout"] < 10:
        raise ValueError("timeout must be an integer >= 10")
    return cfg


def read_token(env: Optional[Dict[str, str]] = None) -> str:
    """Bot token from the file named by TELEGRAM_BOT_TOKEN_FILE (default keys/telegram_bot_token)."""
    env = os.environ if env is None else env
    file = Path(env.get("TELEGRAM_BOT_TOKEN_FILE") or brain_home() / "keys" / "telegram_bot_token").expanduser()
    if not file.is_file():
        raise SystemExit(f"bot token file not found: {file} (create the bot with @BotFather, save the token there, chmod 600)")
    if file.stat().st_mode & 0o077:
        raise SystemExit(f"{file} must not be readable by others (chmod 600)")
    token = file.read_text(encoding="utf-8").strip()
    if ":" not in token:
        raise SystemExit("that does not look like a Telegram bot token")
    return token


def clean_env(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Environment for `claude -p`: without API key style variables, so the subscription is used."""
    source = os.environ if base is None else base
    return {k: v for k, v in source.items() if k in KEEP_ENV or not SENSITIVE_ENV.search(k)}


class Telegram:
    """Minimal Bot API client."""

    def __init__(self, token: str, base: str = API) -> None:
        self.url = f"{base}/bot{token}"

    def call(self, method: str, params: Dict[str, Any], timeout: int = 40) -> Any:
        data = urllib.parse.urlencode({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in params.items()}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{self.url}/{method}", data=data), timeout=timeout) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as err:
            raise RuntimeError(f"Telegram {method}: HTTP {err.code}") from None  # never include the URL: it holds the token
        except (urllib.error.URLError, OSError, ValueError) as err:
            raise RuntimeError(f"Telegram {method}: {err.__class__.__name__}") from None
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method}: {body.get('description', 'error')}")
        return body["result"]

    def updates(self, offset: int, wait: int = 30) -> List[Dict[str, Any]]:
        return self.call("getUpdates", {"offset": offset, "timeout": wait, "allowed_updates": ["message"]}, timeout=wait + 10)

    def send(self, chat_id: int, text: str, limit: int = 3500) -> None:
        for chunk in split_message(text, limit):
            self.call("sendMessage", {"chat_id": chat_id, "text": chunk})


def split_message(text: str, limit: int) -> List[str]:
    """Cut a long answer into chunks under `limit`, preferring paragraph then line breaks."""
    text = text.strip() or "(empty answer)"
    chunks: List[str] = []
    while len(text) > limit:
        cut = max(text.rfind("\n\n", 0, limit), text.rfind("\n", 0, limit), text.rfind(" ", 0, limit))
        cut = cut if cut > limit // 2 else limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return chunks + [text]


def accepted(update: Dict[str, Any], allowed: List[int]) -> Optional[Dict[str, Any]]:
    """The message if it is a text message from an allowed user in a private chat, else None."""
    msg = update.get("message") or {}
    sender = (msg.get("from") or {}).get("id")
    if (msg.get("chat") or {}).get("type") != "private" or sender not in allowed or not isinstance(msg.get("text"), str):
        return None
    return msg


def ask_claude(prompt: str, cfg: Dict[str, Any], resume: bool, runner: Callable[..., Any] = subprocess.run) -> str:
    """Run `claude -p` in the workdir with limited tools. Returns the answer text or a short error."""
    cmd = [cfg["claude_bin"], "-p", "--model", cfg["model"], "--allowedTools", cfg["allowed_tools"]]
    if resume:
        cmd.insert(2, "--continue")
    workdir = Path(cfg["workdir"]).expanduser()
    try:
        res = runner(cmd, input=prompt, capture_output=True, text=True, timeout=cfg["timeout"], cwd=workdir, env=clean_env())
    except subprocess.TimeoutExpired:
        return f"Timed out after {cfg['timeout']} s."
    except OSError as err:
        return f"Could not start claude: {err.__class__.__name__}"
    if res.returncode != 0:
        return "claude failed: " + " ".join((res.stderr or "").split())[-200:]
    return res.stdout


def audit(path: Path, user: int, length: int, outcome: str) -> None:
    """One line per request, no content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} user={user} chars={length} {outcome}\n")


class Bridge:
    """Holds the polling offset and the 'fresh conversation' flag; one request at a time."""

    def __init__(self, api: Telegram, cfg: Dict[str, Any], state_dir: Path, runner: Callable[..., Any] = subprocess.run) -> None:
        self.api, self.cfg, self.runner = api, cfg, runner
        self.offset_file = state_dir / "telegram_offset"
        self.log_file = state_dir / "telegram_bridge.log"
        self.fresh = not cfg["keep_session"]
        try:
            self.offset = int(self.offset_file.read_text().strip())
        except (OSError, ValueError):
            self.offset = 0

    def _save_offset(self) -> None:
        self.offset_file.parent.mkdir(parents=True, exist_ok=True)
        self.offset_file.write_text(str(self.offset))

    def handle(self, msg: Dict[str, Any]) -> None:
        user, chat, text = msg["from"]["id"], msg["chat"]["id"], msg["text"].strip()
        if text == "/new":
            self.fresh = True
            return self.api.send(chat, "New conversation started.")
        if text == "/status":
            c = self.cfg
            return self.api.send(chat, f"model={c['model']} tools={c['allowed_tools']} workdir={c['workdir']} session={'new' if self.fresh else 'continued'}")
        answer = ask_claude(text, self.cfg, resume=self.cfg["keep_session"] and not self.fresh, runner=self.runner)
        self.fresh = False if self.cfg["keep_session"] else True
        audit(self.log_file, user, len(text), "ok" if not answer.startswith(("claude failed", "Timed out", "Could not")) else "error")
        self.api.send(chat, answer, self.cfg["max_reply_chars"])

    def step(self, wait: int = 30) -> int:
        """One polling round. Returns the number of messages answered."""
        answered = 0
        for update in self.api.updates(self.offset, wait):
            self.offset = max(self.offset, update["update_id"] + 1)
            msg = accepted(update, self.cfg["allowed_user_ids"])
            self._save_offset()  # saved before handling: a crash never replays a command
            if msg is not None:
                self.handle(msg)
                answered += 1
        return answered


def discover(api: Telegram) -> int:
    """Print who wrote to the bot, so the user can fill allowed_user_ids. Does not answer anyone."""
    seen: Dict[int, str] = {}
    for update in api.updates(0, wait=1):
        sender = (update.get("message") or {}).get("from") or {}
        if "id" in sender:
            seen[sender["id"]] = sender.get("first_name", "")
    for uid, name in seen.items():
        print(f"{uid}\t{name}")
    print(f"{len(seen)} sender(s). Put your own id in allowed_user_ids.", file=sys.stderr)
    return 0


def main(argv: List[str]) -> int:
    command = argv[0] if argv else ""
    if command not in ("run", "discover"):
        print(__doc__)
        return 2
    api = Telegram(read_token())
    if command == "discover":
        return discover(api)
    try:
        cfg = load_config()
    except ValueError as err:
        print(f"config error: {err}", file=sys.stderr)
        return 78
    if not cfg["allowed_user_ids"]:
        print("allowed_user_ids is empty: run `discover`, then list your id in the config. Refusing to start.", file=sys.stderr)
        return 78
    bridge = Bridge(api, cfg, brain_home() / "state")
    print("telegram bridge running", file=sys.stderr)
    while True:
        try:
            bridge.step()
        except RuntimeError as err:
            print(f"{err}; retrying in 15 s", file=sys.stderr)
            time.sleep(15)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
