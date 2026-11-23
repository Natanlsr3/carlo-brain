"""Read module.toml on any Python 3.9+.

Uses `tomllib` when available (3.11+). Older Pythons get a small parser that supports the subset
module.toml is allowed to use: comments, `key = value` with strings, integers, booleans and
(multi-line) arrays of those, `[table]` and `[[array.of.tables]]` headers. No inline tables.
"""
from __future__ import annotations

import json
import re
from typing import Any

try:  # pragma: no cover - depends on the interpreter
    import tomllib as _tomllib
except ImportError:  # Python < 3.11
    _tomllib = None


class TomlError(ValueError):
    """The file is not valid for our TOML subset."""


def loads(text: str) -> dict:
    """Parse TOML text into a dict."""
    if _tomllib is not None:
        try:
            return _tomllib.loads(text)
        except _tomllib.TOMLDecodeError as exc:
            raise TomlError(str(exc)) from exc
    return _mini_loads(text)


def _strip_comment(line: str) -> str:
    out, quote = [], ""
    for ch in line:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            break
        out.append(ch)
    return "".join(out).strip()


def _value(raw: str) -> Any:
    raw = raw.strip()
    if raw in ("true", "false"):
        return raw == "true"
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
        return raw[1:-1]
    if raw.startswith(("\"", "[")):
        if raw.startswith("["):
            raw = re.sub(r",\s*\]", "]", raw)
            raw = raw if '"' in raw else raw.replace("'", '"')
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise TomlError(f"unsupported value: {raw}") from exc
    raise TomlError(f"unsupported value: {raw}")


def _descend(root: dict, path: list, array: bool) -> dict:
    node = root
    for i, key in enumerate(path):
        last = i == len(path) - 1
        if last and array:
            node = node.setdefault(key, [])
            if not isinstance(node, list):
                raise TomlError(f"{key} is not an array of tables")
            node.append({})
            return node[-1]
        child = node.setdefault(key, {})
        if isinstance(child, list):
            child = child[-1]
        node = child
    return node


def _mini_loads(text: str) -> dict:
    root: dict = {}
    current = root
    pending = ""
    for number, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw)
        if pending:
            pending += " " + line
            if pending.count("[") > pending.count("]"):
                continue
            line, pending = pending, ""
        if not line:
            continue
        header = re.fullmatch(r"(\[\[?)\s*([\w.-]+)\s*\]\]?", line)
        if header:
            current = _descend(root, header.group(2).split("."), header.group(1) == "[[")
            continue
        match = re.fullmatch(r"([\w-]+)\s*=\s*(.+)", line)
        if not match:
            raise TomlError(f"line {number}: cannot parse {raw.strip()!r}")
        if match.group(2).startswith("[") and match.group(2).count("[") > match.group(2).count("]"):
            pending = line
            continue
        current[match.group(1)] = _value(match.group(2))
    return root
