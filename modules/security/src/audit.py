#!/usr/bin/env python3
"""Tamper-evident audit log of outgoing sends: JSONL, each line carries the SHA-256 of the previous one.

Only fingerprints of the content are stored, never the content itself. Editing or deleting a line
in the middle breaks the chain, which `audit.py verify` reports.

Usage: audit.py verify | audit.py show [N]
       audit.py record     (PostToolUse hook: reads the event on stdin, records sends only)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _lib in (os.environ.get("CARLO_LIB"), str(Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain") / "lib")):
    if _lib:
        sys.path.insert(0, _lib)
import carlo_config as cfg  # noqa: E402
import detectors  # noqa: E402
import targets  # noqa: E402

try:
    import fcntl
except ImportError:  # Windows: no locking
    fcntl = None  # type: ignore[assignment]

ZERO = "0" * 64
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RECIPIENT_KEYS = ("to", "cc", "bcc", "recipient", "recipients", "channel", "channel_id", "chat_id", "user", "user_id",
                  "attendees", "email", "phone", "number")
SUBJECT_KEYS = ("subject", "title", "summary", "name", "message", "body", "text", "content", "command")


def path() -> Path:
    return cfg.state_dir() / "audit.jsonl"


def line_hash(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def fingerprint(tool_input: Any) -> str:
    return hashlib.sha256(json.dumps(tool_input, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _flat(value: Any) -> list:
    if isinstance(value, dict):
        return [x for v in value.values() for x in _flat(v)]
    if isinstance(value, (list, tuple)):
        return [x for v in value for x in _flat(v)]
    return [] if value is None else [str(value)]


def recipients(tool_input: Any) -> list:
    found: list = []
    if isinstance(tool_input, dict):
        for key in RECIPIENT_KEYS:
            found += _flat(tool_input.get(key))
    if not found:
        found = EMAIL.findall(json.dumps(tool_input, ensure_ascii=False, default=str))
    return list(dict.fromkeys(found))[:10]


def redact(text: str) -> str:
    """Replace every sensitive span found by the detectors, so a preview can never carry a secret."""
    for item in reversed(detectors.scan(text)):
        text = text[:item.start] + "[redacted]" + text[item.end:]
    return text


def subject(tool_input: Any) -> str:
    """Short preview (80 characters) of the subject or first text field, with sensitive spans redacted."""
    if isinstance(tool_input, dict):
        for key in SUBJECT_KEYS:
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return redact(" ".join(value.split()))[:80]
    return ""


def read_all(file: Optional[Path] = None) -> list:
    file = file or path()
    out = []
    for line in file.read_text(encoding="utf-8").splitlines() if file.exists() else []:
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append({"_corrupt": line})
    return out


def append(tool: str, tool_input: Any, status: str, session: str = "", file: Optional[Path] = None) -> dict:
    """Add one record (status: ok, blocked, error). The previous hash is read under a lock."""
    file = file or path()
    file.parent.mkdir(parents=True, exist_ok=True)
    with open(file, "a+", encoding="utf-8") as handle:
        if fcntl:
            fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        lines = [l for l in handle.read().splitlines() if l.strip()]
        try:
            previous = json.loads(lines[-1]).get("hash", ZERO) if lines else ZERO
        except ValueError:
            previous = ZERO
        record = {"ts": cfg.now_iso(), "session": session[:8], "tool": tool, "recipients": recipients(tool_input),
                  "subject": subject(tool_input), "content_sha256": fingerprint(tool_input), "status": status, "prev": previous}
        record["hash"] = line_hash(record)
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def verify(file: Optional[Path] = None) -> tuple:
    """(ok, number of records, index of the first broken record or -1)."""
    previous = ZERO
    records = read_all(file)
    for index, record in enumerate(records):
        if "_corrupt" in record or record.get("prev") != previous or record.get("hash") != line_hash(record):
            return False, len(records), index
        previous = record["hash"]
    return True, len(records), -1


def status_of(response: Any) -> str:
    text = json.dumps(response, default=str).lower() if response is not None else ""
    return "error" if re.search(r'"(is_error|error)"\s*:\s*(true|"[^"]+")', text) else "ok"


def record_hook(event: dict) -> bool:
    """PostToolUse: record the call when it is a send. Returns True when recorded."""
    tool, data = str(event.get("tool_name", "")), event.get("tool_input")
    extra = tuple(cfg.get("security.send_tools", []) or [])
    if not targets.is_send(tool, data, extra):
        return False
    append(tool, data, status_of(event.get("tool_response")), str(event.get("session_id", "")))
    return True


def main(argv: list) -> int:
    mode = argv[0] if argv else "record"
    if mode == "verify":
        ok, count, bad = verify()
        print(f"{count} record(s), chain ok" if ok else f"CHAIN BROKEN at record {bad} of {count}")
        return 0 if ok else 1
    if mode == "show":
        limit = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 20
        for record in read_all()[-limit:]:
            print(f"{record.get('ts')} {record.get('status'):<8} {record.get('tool')} -> "
                  f"{', '.join(record.get('recipients', []))} | {record.get('subject')}")
        return 0
    try:
        record_hook(json.load(sys.stdin))
    except Exception as exc:  # noqa: BLE001 - auditing must never break a tool call
        cfg.log_error("security.audit", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
