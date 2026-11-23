"""The STATUS line: how an unattended step reports its own outcome.

A step is only counted as done when the agent's LAST status line says `done`. The exit code of
`claude -p` says the process ended, not that the work was finished.
"""
from __future__ import annotations

import re
from typing import Tuple

INSTRUCTION = (
    "LAST LINE REQUIRED in your reply, alone on its line: `STATUS: done|partial|failed - reason in one sentence`. "
    "Write `done` only if everything asked in this step is really done; otherwise `partial` or `failed` with the reason. "
    "Without this line the step is counted as not finished."
)
_PATTERN = re.compile(r"^\W*status\W+(done|partial|failed)\b\W*(.*)$", re.IGNORECASE)
LIMIT = re.compile(r"hit your|usage limit|rate limit|limit reached", re.IGNORECASE)


def read(text: str) -> Tuple[str, str]:
    """(status, reason) from the LAST status line; ('absent', ...) when there is none."""
    found = None
    for line in text.splitlines():
        match = _PATTERN.match(line.strip())
        if match:
            found = (match.group(1).lower(), match.group(2).strip(" *`-:") or "no reason given")
    return found if found else ("absent", "no STATUS line in the agent's output")


def hit_limit(text: str) -> bool:
    """True if the output says the usage limit was reached (wait instead of failing)."""
    return bool(LIMIT.search(text or ""))
