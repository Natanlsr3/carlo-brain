"""Read-only access to Apple Mail's local index and .emlx files (macOS only).

Nothing here writes to Mail, changes read status or sends anything. Opening a database in
mode=ro does not mark messages as read. Mail version folders change between macOS releases
(V9, V10, ...), so the newest one is auto-detected.

Needs Full Disk Access for the process that runs it (Terminal, or the scheduler's Python).
"""
from __future__ import annotations

import email
import os
import re
import sqlite3
import unicodedata
from datetime import datetime
from email import policy
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import unquote

from ..model import SourceError

# (rowid, received "YYYY-MM-DD HH:MM:SS" local, sender address, subject, attachment names, read flag)
MailRow = Tuple[int, str, str, str, List[str], int]

IGNORED_MAILBOX = re.compile(r"trash|spam|deleted|junk|draft|outbox|sendlater|bin\b", re.IGNORECASE)
AUTOMATED_SENDER = re.compile(
    r"no.?reply|notification|newsletter|news@|info@|mailer|calendar|hello@|support@|contact@|marketing"
    r"|digest|bounce|do-not-reply|team@|receipt|billing|alerts?@|updates?@",
    re.IGNORECASE,
)
AUTO_REPLY = re.compile(r"automatic reply|out of office|undeliverable|delivery status|mail delivery", re.IGNORECASE)


def find_index(root: Optional[Path] = None) -> Path:
    """Path of the newest 'Envelope Index'. Raises SourceError if Mail data is absent."""
    base = Path(root).expanduser() if root else Path.home() / "Library" / "Mail"
    found = sorted(base.glob("V*/MailData/Envelope Index"), key=_version_key, reverse=True)
    if not found:
        raise SourceError(f"Apple Mail index not found under {base}")
    return found[0]


def _version_key(path: Path) -> int:
    digits = re.sub(r"\D", "", path.parents[1].name)
    return int(digits) if digits else 0


def connect(index: Path) -> sqlite3.Connection:
    """Open the index read-only. Raises sqlite3.Error / OSError if denied or locked."""
    con = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    con.execute("SELECT 1 FROM messages LIMIT 1").fetchone()
    return con


def check(index: Path) -> None:
    """Fail loudly (not with an empty result) if the index cannot be read."""
    con = connect(index)
    con.close()


def recent(index: Path, since: datetime) -> List[MailRow]:
    """Messages received since `since`, oldest first, with attachment names and read flag."""
    epoch = int(since.timestamp())
    with connect(index) as con:
        rows = con.execute(
            "SELECT m.ROWID, datetime(m.date_received,'unixepoch','localtime'), a.address, s.subject, m.read"
            " FROM messages m JOIN addresses a ON m.sender=a.ROWID JOIN subjects s ON m.subject=s.ROWID"
            " WHERE m.date_received >= ? AND m.deleted = 0 ORDER BY m.date_received",
            (epoch,),
        ).fetchall()
        files: Dict[int, List[str]] = {}
        for message, name in con.execute(
            "SELECT message, name FROM attachments WHERE message IN"
            " (SELECT ROWID FROM messages WHERE date_received >= ?)",
            (epoch,),
        ):
            files.setdefault(message, []).append(name or "")
    return [(r, d, (a or "").lower(), s or "", files.get(r, []), rd or 0) for r, d, a, s, rd in rows]


def direct_ids(index: Path, since: datetime, my_addresses: Iterable[str]) -> Set[int]:
    """ROWIDs of mail where you are a direct To/Cc recipient (filters mailing lists)."""
    mine = [a.lower() for a in my_addresses if a]
    if not mine:
        return set()
    marks = ",".join("?" * len(mine))
    with connect(index) as con:
        return {
            r
            for (r,) in con.execute(
                "SELECT DISTINCT r.message FROM recipients r JOIN addresses a ON r.address=a.ROWID"
                f" JOIN messages m ON m.ROWID=r.message WHERE m.date_received >= ? AND lower(a.address) IN ({marks})",
                (int(since.timestamp()), *mine),
            )
        }


def _useful_mailboxes(con: sqlite3.Connection) -> List[int]:
    return [
        rowid
        for rowid, url in con.execute("SELECT ROWID, url FROM mailboxes")
        if not IGNORED_MAILBOX.search(unicodedata.normalize("NFC", unquote(url or "")))
    ]


def sent_and_received(
    index: Path, since: datetime, my_addresses: Iterable[str], max_recipients: int = 3
) -> Tuple[List[Tuple], List[Tuple]]:
    """Mail you sent (To only, at most `max_recipients` people) and replies received from those people.

    Returns (sent, received): sent = (rowid, epoch, to_address, to_name, subject),
    received = (rowid, epoch, from_address, subject). Drafts, trash and spam are ignored.
    """
    mine = [a.lower() for a in my_addresses if a]
    if not mine:
        return [], []
    epoch = int(since.timestamp())
    with connect(index) as con:
        boxes = ",".join(str(b) for b in _useful_mailboxes(con)) or "0"
        marks = ",".join("?" * len(mine))
        raw = con.execute(
            "SELECT m.ROWID, m.date_received, a.address, a.comment, s.subject FROM messages m"
            " JOIN addresses e ON e.ROWID = m.sender"
            " JOIN recipients r ON r.message = m.ROWID AND r.type = 0"
            " JOIN addresses a ON a.ROWID = r.address JOIN subjects s ON s.ROWID = m.subject"
            f" WHERE m.date_received >= ? AND m.deleted = 0 AND m.mailbox IN ({boxes})"
            f" AND lower(e.address) IN ({marks}) ORDER BY m.date_received",
            (epoch, *mine),
        ).fetchall()
        per_mail: Dict[int, int] = {}
        for rowid, *_ in raw:
            per_mail[rowid] = per_mail.get(rowid, 0) + 1
        sent = list({(r[0], (r[2] or "").lower()): r for r in raw if per_mail[r[0]] <= max_recipients}.values())
        people = sorted({(r[2] or "").lower() for r in sent})
        received: List[Tuple] = []
        for i in range(0, len(people), 500):
            lot = people[i : i + 500]
            received += con.execute(
                "SELECT m.ROWID, m.date_received, e.address, s.subject FROM messages m"
                " JOIN addresses e ON e.ROWID = m.sender JOIN subjects s ON s.ROWID = m.subject"
                f" WHERE m.date_received >= ? AND m.deleted = 0 AND m.mailbox IN ({boxes})"
                f" AND lower(e.address) IN ({','.join('?' * len(lot))})",
                (epoch, *lot),
            ).fetchall()
    return sent, received


class MailFiles:
    """Lazy lookup of .emlx bodies and downloaded attachments (one directory walk per run)."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root).expanduser() if root else Path.home() / "Library" / "Mail"
        self._emlx: Optional[Dict[int, Path]] = None
        self._attach: Optional[Dict[int, List[Path]]] = None

    def _walk(self) -> None:
        self._emlx, self._attach = {}, {}
        for folder, dirs, names in os.walk(self.root):
            parts = Path(folder).parts
            for name in names:
                stem = name.split(".")[0]
                if name.endswith((".emlx", ".partial.emlx")) and stem.isdigit():
                    self._emlx.setdefault(int(stem), Path(folder) / name)
                elif "Attachments" in parts:
                    idx = parts.index("Attachments")
                    if idx + 1 < len(parts) and parts[idx + 1].isdigit():
                        self._attach.setdefault(int(parts[idx + 1]), []).append(Path(folder) / name)

    def body(self, rowid: int) -> str:
        """Plain text of a message, "" if not found. Never touches the read flag."""
        if self._emlx is None:
            self._walk()
        path = (self._emlx or {}).get(rowid)
        if path is None:
            return ""
        try:
            raw = path.read_bytes().split(b"\n", 1)[1]
        except (OSError, IndexError):
            return ""
        msg = email.message_from_bytes(raw, policy=policy.default)
        part = msg.get_body(("plain", "html"))
        if part is None:
            return ""
        text = part.get_content()
        return re.sub(r"<[^>]+>", " ", text) if part.get_content_type() == "text/html" else text

    def attachments(self, rowid: int) -> List[Path]:
        """Downloaded attachment files of a message (empty if Mail did not download them)."""
        if self._attach is None:
            self._walk()
        return list((self._attach or {}).get(rowid, []))


BodyReader = Callable[[int], str]
