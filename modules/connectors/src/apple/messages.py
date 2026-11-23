"""Search iMessage / SMS (chat.db), read-only.

Usage: messages.py search "<text>" [--days N] [--max 20]
       messages.py thread "<name or number>" [--max 30]
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contacts as ct  # noqa: E402
from _common import APPLE_EPOCH, AccessError, apple_date, fold, one_line, open_ro, normalise_phone  # noqa: E402

DB = os.path.expanduser("~/Library/Messages/chat.db")
QUERY = (
    "select m.date, m.is_from_me, h.id, m.text, m.attributedBody from message m "
    "left join handle h on h.ROWID = m.handle_id {where} order by m.date desc"
)


def extract_text(text: Optional[str], body: Optional[bytes]) -> str:
    """Message text: the `text` column, else a heuristic decode of attributedBody.

    attributedBody is a typedstream NSAttributedString: after the "NSString" marker comes 0x2B,
    then the length (1 byte, or 0x81 + 2 bytes, or 0x82 + 4 bytes, little endian), then UTF-8.
    This is reverse engineered and can break with a new macOS version.
    """
    if text:
        return text.replace("￼", "").strip()
    if not body:
        return ""
    data = bytes(body)
    i = data.find(b"NSString")
    if i < 0:
        return ""
    j = data.find(b"\x2b", i + 8, i + 24)
    if j < 0 or j + 1 >= len(data):
        return ""
    pos = j + 1
    first = data[pos]
    if first == 0x81:
        size, pos = int.from_bytes(data[pos + 1 : pos + 3], "little"), pos + 3
    elif first == 0x82:
        size, pos = int.from_bytes(data[pos + 1 : pos + 5], "little"), pos + 5
    else:
        size, pos = first, pos + 1
    return data[pos : pos + size].decode("utf-8", "replace").replace("￼", "").strip()


def name_table(book: List[ct.Contact]) -> Dict[str, str]:
    """Address book: key (last 9 digits, or lowercase mail) -> display name."""
    table: Dict[str, str] = {}
    for c in book:
        for phone in c.phones:
            digits = normalise_phone(phone)
            if digits:
                table.setdefault(digits[-9:], c.display)
        for address in c.emails:
            table.setdefault(address.lower(), c.display)
    return table


def handle_name(handle: Optional[str], table: Dict[str, str]) -> str:
    """Contact name for an iMessage handle (number or mail), else the handle."""
    if not handle:
        return "?"
    key = handle.lower() if "@" in handle else normalise_phone(handle)[-9:]
    return table.get(key, handle)


def _line(date: int, from_me: int, handle: Optional[str], text: str, table: Dict[str, str]) -> str:
    who = "me" if from_me else handle_name(handle, table)
    return f"{apple_date(date)} | {who} | {one_line(text)}"


def search(conn: sqlite3.Connection, text: str, days: Optional[int], limit: int, table: Dict[str, str]) -> List[str]:
    """Messages containing every word of `text` (accent and case insensitive), newest first."""
    where, params = "", []
    if days:
        where, params = "where m.date >= ?", [(time.time() - days * 86400 - APPLE_EPOCH) * 1e9]
    words = fold(text).split()
    out: List[str] = []
    for date, from_me, handle, raw, body in conn.execute(QUERY.format(where=where), params):
        content = extract_text(raw, body)
        haystack = fold(content)
        if content and all(w in haystack for w in words):
            out.append(_line(date, from_me, handle, content, table))
            if len(out) >= limit:
                break
    return out


def handles_for(target: str, conn: sqlite3.Connection, book: List[ct.Contact]) -> Tuple[List[int], str]:
    """Handle ROWIDs of a person given by name or number."""
    if re.fullmatch(r"[+\d\s().-]{6,}", target):
        numbers, mails, label = [target], [], target
    else:
        found = ct.by_name(target, book)
        numbers = [p for c in found for p in c.phones]
        mails = [m.lower() for c in found for m in c.emails]
        label = found[0].display if found else target
        if "@" in target:
            mails.append(target.lower())
    ids = []
    for rowid, handle in conn.execute("select ROWID, id from handle"):
        if "@" in handle:
            if handle.lower() in mails:
                ids.append(rowid)
        elif any(ct.same_number(handle, n) for n in numbers):
            ids.append(rowid)
    return ids, label


def thread(conn: sqlite3.Connection, target: str, limit: int, book: List[ct.Contact], table: Dict[str, str]) -> List[str]:
    """Last messages exchanged with a person, oldest first."""
    ids, _ = handles_for(target, conn, book)
    if not ids:
        return []
    where = f"where m.handle_id in ({','.join('?' * len(ids))})"
    out: List[str] = []
    for date, from_me, handle, raw, body in conn.execute(QUERY.format(where=where), ids):
        content = extract_text(raw, body)
        if content:
            out.append(_line(date, from_me, handle, content, table))
            if len(out) >= limit:
                break
    return out[::-1]


def _address_book() -> List[ct.Contact]:
    """Contacts for name resolution; empty if unreadable (not blocking)."""
    try:
        return ct.load_contacts()
    except (AccessError, FileNotFoundError, sqlite3.Error):
        return []


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="iMessage/SMS (read-only)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("search")
    p1.add_argument("text")
    p1.add_argument("--days", type=int)
    p1.add_argument("--max", type=int, default=20)
    p2 = sub.add_parser("thread")
    p2.add_argument("target")
    p2.add_argument("--max", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        book = _address_book()
        table = name_table(book)
        with open_ro(DB) as conn:
            lines = search(conn, args.text, args.days, args.max, table) if args.cmd == "search" else thread(conn, args.target, args.max, book, table)
    except (AccessError, FileNotFoundError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    print(f"{len(lines)} message(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
