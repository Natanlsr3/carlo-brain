"""Which tool calls send content outside the machine, and how to flatten their input to text."""
from __future__ import annotations

import re
from typing import Any

READ_ONLY = re.compile(r"^(get|list|read|search|fetch|find|download|query|view|describe)", re.I)
SENDING = re.compile(r"(send|reply|forward|post|publish|share|schedule|draft|create_event|update_event|comment|invite|upload)", re.I)
MAIL_OSA = re.compile(r"osascript[\s\S]*(?:application\s+\\?[\"']?Mail|tell\s+application\s+\\?\"Mail)[\s\S]*(?:send|outgoing message)", re.I)
MAIL_CLI = re.compile(r"(?:^|[;&|]\s*)(?:sendmail|msmtp|mutt|mailx?)\b", re.I)
CURL_POST = re.compile(r"\bcurl\b[\s\S]*?(?:-X\s*POST|\s-d\b|--data\S*|\s-F\b|--form\S*|--json|\s-T\b)", re.I)
EXTERNAL_URL = re.compile(r"https?://(?!(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?:[:/\s'\"]|$))[\w.-]+", re.I)
GH_WRITE = re.compile(r"\bgh\s+(?:issue|pr)\s+(?:comment|create)\b", re.I)


def bash_sends(command: str) -> bool:
    """True when a shell command sends content out: mail, POST to an external URL, GitHub comment or creation."""
    return bool(MAIL_OSA.search(command) or MAIL_CLI.search(command) or GH_WRITE.search(command)
                or (CURL_POST.search(command) and EXTERNAL_URL.search(command)))


def is_send(tool: str, tool_input: Any, extra_tools: tuple = ()) -> bool:
    """True when the tool call must be guarded and audited."""
    if tool in extra_tools:
        return True
    if tool == "Bash":
        return isinstance(tool_input, dict) and bash_sends(str(tool_input.get("command", "")))
    if tool.startswith("mcp__"):
        action = tool.split("__")[-1]
        return not READ_ONLY.match(action) and bool(SENDING.search(action))
    return False


def text_fields(obj: Any, path: str = "") -> list:
    """Flatten a tool input into (field path, text) pairs, every scalar included."""
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in text_fields(v, f"{path}.{k}" if path else str(k))]
    if isinstance(obj, (list, tuple)):
        return [p for i, v in enumerate(obj) for p in text_fields(v, f"{path}[{i}]")]
    if obj is None or isinstance(obj, bool):
        return []
    return [(path or "input", str(obj))]
