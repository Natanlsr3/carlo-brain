#!/usr/bin/env python3
"""PreToolUse: block any read of files that hold secrets, and any command that prints the environment.

Why: a hand-written masking command always ends up missing one token format, and the secret then
lands in the conversation (and in the provider's logs). So these files are never read at all, with
Bash, Read, Grep or Glob. Exit code 2 blocks the tool call and shows the reason to the assistant.

Unreadable stdin fails OPEN (exit 0 plus a stderr warning) so a broken hook never freezes every tool call;
`carlo config set security.fail_closed true` makes it block instead.

Allowed on purpose: `test -s <file>` (checks presence, reads nothing) and passing a key file PATH
to a program through a `NAME_KEY_FILE=<path>` variable (the program reads the key itself).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

SECRET_FILE = re.compile(
    r"""(?:^|[\s/'"=<>(|;&])(?:
        \.zprofile|\.zshrc|\.zshenv|\.zlogin|\.bash_profile|\.bashrc|\.profile|
        \.env(?!\.example|\.sample|\.template)(?:\.[\w.-]+)?|
        secrets?\.(?:md|txt|json|ya?ml|toml)|secrets/|\.netrc|\.npmrc|\.pypirc|credentials(?:\.json)?|
        id_(?:rsa|ed25519|ecdsa)|(?-i:[a-z0-9_.-]*_key)(?:\.(?:txt|json|pem|yml|yaml|toml|cfg|conf|ini))?|(?-i:[\w.-]*\.key)|
        [\w.-]*token[\w.-]*\.txt|\.aws/|\.ssh/|\.gnupg/|\.config/gh/hosts\.yml|\.carlo-brain/keys|\.claude\.json
    )(?=$|[\s'"):;|&>/])""",
    re.X | re.I,
)
# A path component named secret or secrets (~/secrets, ./secret) is a secrets file or folder. A bare word
# in a command (`grep -r secret src/`) is not: it has no "/" in front of it.
SECRET_PATH_PART = re.compile(r"(?<=/)secrets?(?=$|[\s'\"):;|&>/])", re.I)
# Commands that dump the environment: env, printenv, export, set, declare -x, alone or piped.
DUMP_ENV = re.compile(
    r"(?:^|[;&|(]\s*|\$\(\s*)(?:printenv\b|env\s*(?:$|[;&|)>])|export\s*(?:$|[;&|)>]|-p\b)|set\s*(?:$|[;&|)>])|declare\s+-[xp])"
)
ECHO_VAR = re.compile(r"(?:echo|printf)[^;&|]*\$\{?[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z_]*", re.I)
KEY_FILE_ARG = re.compile(r"\b[A-Z_]*_KEY_FILE=\S+")
PRESENCE_TEST = re.compile(r"\btest\s+-[sfe]\s+\S+|\[\s+-[sfe]\s+\S+\s+\]")

REASON = (
    "Blocked by block_secret_reads.py: this file or command can expose secrets. Never read shell profiles, "
    "environment files, secrets files or key files, even with a masking command. To know whether a key exists: "
    "`test -s <file> && echo present`. To use it: pass the file path to the program through a NAME_KEY_FILE=<path> "
    "variable so it reads the key itself."
)


def blocked(tool: str, tool_input: dict) -> bool:
    """True when the call would read a secret file or dump the environment."""
    if tool == "Bash":
        command = PRESENCE_TEST.sub("", KEY_FILE_ARG.sub("", str(tool_input.get("command", ""))))
        return bool(SECRET_FILE.search(command) or SECRET_PATH_PART.search(command) or DUMP_ENV.search(command) or ECHO_VAR.search(command))
    if tool in ("Read", "Grep", "Glob", "NotebookEdit", "Edit", "Write"):
        path = " ".join(str(tool_input.get(k, "")) for k in ("file_path", "notebook_path", "path", "pattern", "glob"))
        return bool(SECRET_FILE.search(" " + path) or SECRET_PATH_PART.search(path))
    return False


def fail_closed() -> bool:
    """True when the user asked to block on unreadable input (config key security.fail_closed). Default: open."""
    try:
        home = Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain")
        config = json.loads((home / "config.json").read_text(encoding="utf-8"))
        return config.get("security", {}).get("fail_closed") is True
    except (OSError, ValueError, AttributeError):
        return False


def unreadable(why: str) -> int:
    """Exit code for input we cannot parse: 0 with a warning by default, 2 when fail_closed is set."""
    closed = fail_closed()
    print(f"secret-read hook: unreadable input ({why}); " + ("blocking (security.fail_closed)" if closed
          else "letting the call through (set security.fail_closed to true to block instead)"), file=sys.stderr)
    return 2 if closed else 0


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError as exc:
        return unreadable(str(exc))
    if not isinstance(data, dict):
        return unreadable("JSON object expected")
    tool_input = data.get("tool_input")
    if blocked(str(data.get("tool_name", "")), tool_input if isinstance(tool_input, dict) else {}):
        print(REASON, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
