"""Journal: journal.jsonl (machine) and CHANGELOG.md (human, newest first, in the improvement folder)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .settings import Settings


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> Optional[str]:
    """Hash of a file, None if it does not exist."""
    return sha256(path.read_bytes()) if path.is_file() else None


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def write(cfg: Settings, entry: Dict[str, Any]) -> None:
    """Append to journal.jsonl and put one readable line at the top of CHANGELOG.md."""
    cfg.state.mkdir(parents=True, exist_ok=True)
    with (cfg.state / "journal.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    view = cfg.improvement / "CHANGELOG.md"
    view.parent.mkdir(parents=True, exist_ok=True)
    line = (f"- {entry['date']} | {entry['verdict']} (tier {entry['tier']}) | "
            f"{entry.get('title', entry['id'])} [{entry['id']}]: {entry['reason']}")
    current = view.read_text(encoding="utf-8") if view.exists() else "# Change log of automatic improvements\n"
    head, _, rest = current.partition("\n")
    if not head.startswith("#"):
        head, rest = "# Change log of automatic improvements", current
    view.write_text(f"{head}\n\n{line}\n{rest.lstrip(chr(10))}", encoding="utf-8")
