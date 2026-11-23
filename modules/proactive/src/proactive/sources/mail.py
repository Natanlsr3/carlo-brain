"""Unread mail from real people addressed to you (Apple Mail, read-only, macOS only)."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from ..model import Signal, SourceResult, explain_outage
from ..text import short
from . import mail_apple


def load_contacts(csv_path: str) -> Dict[str, str]:
    """address -> name from an optional CSV with columns name,email (empty if not configured)."""
    if not csv_path:
        return {}
    path = Path(csv_path).expanduser()
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            (row.get("email") or "").strip().lower(): row["name"]
            for row in csv.DictReader(handle)
            if (row.get("email") or "").strip() and row.get("name")
        }


def collect(cfg: Dict[str, Any], now: datetime, root: Optional[Path] = None) -> SourceResult:
    """Unread, directly addressed, non automated mail from the lookback window."""
    own = cfg["sources"]["apple_mail"]
    result = SourceResult()
    if not own["unread_direct"]:
        return result
    since = now - timedelta(hours=cfg["lookback_hours"])
    try:
        index = mail_apple.find_index(root or (own["root"] or None))
        direct = mail_apple.direct_ids(index, since, cfg["identity"]["addresses"])
        rows = mail_apple.recent(index, since)
    except Exception as err:  # noqa: BLE001 - reported as an outage line
        result.outages.append(explain_outage("Mail", err))
        return result
    names = load_contacts(cfg["contacts"]["csv"])
    mine = {a.lower() for a in cfg["identity"]["addresses"]}
    for rowid, date, sender, subject, _files, read in reversed(rows):
        if read or rowid not in direct or sender in mine or mail_apple.AUTOMATED_SENDER.search(sender):
            continue
        who = names.get(sender) or sender
        result.signals.append(
            Signal("direct_unread", f"Unread mail from {who}: '{short(subject, 60)}' ({date[5:16]})", "mail",
                   question=f"Reply to {who} ready: send it? (go / let me look)")
        )
        if len(result.signals) >= own["max_items"]:
            break
    return result
