"""Read Apple Notes (NoteStore.sqlite), read-only. Password-protected notes are reported, never read.

Usage: notes.py list [--max 30] | notes.py search "<text>" [--max 20] | notes.py read "<title>"
The note body decoder (gzip + protobuf) is reverse engineered and may break with a new macOS.
"""
from __future__ import annotations

import argparse
import gzip
import os
import sqlite3
import sys
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import AccessError, apple_date, fold, one_line, open_ro  # noqa: E402

DB = os.path.expanduser("~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite")
# (title, folder, modified, protected, snippet, zdata)
Note = Tuple[str, str, str, bool, str, Optional[bytes]]

# Live notes: not deleted, not in "Recently Deleted" (ZFOLDERTYPE = 1).
SELECT = (
    "select o.Z_PK, o.ZTITLE1, o.ZSNIPPET, o.ZMODIFICATIONDATE1, o.ZISPASSWORDPROTECTED, f.ZTITLE2, d.ZDATA "
    "from ZICCLOUDSYNCINGOBJECT o join ZICNOTEDATA d on d.Z_PK = o.ZNOTEDATA "
    "left join ZICCLOUDSYNCINGOBJECT f on f.Z_PK = o.ZFOLDER "
    "where coalesce(o.ZMARKEDFORDELETION, 0) = 0 and coalesce(f.ZFOLDERTYPE, 0) != 1 "
    "order by o.ZMODIFICATIONDATE1 desc"
)


def _varint(data: bytes, pos: int) -> Tuple[int, int]:
    value = shift = 0
    while True:
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7


def _fields(data: bytes) -> List[Tuple[int, bytes]]:
    """Length-delimited protobuf fields (number, content); other wire types are skipped."""
    pos, out = 0, []
    while pos < len(data):
        key, pos = _varint(data, pos)
        wire, number = key & 7, key >> 3
        if wire == 0:
            _, pos = _varint(data, pos)
        elif wire == 1:
            pos += 8
        elif wire == 5:
            pos += 4
        elif wire == 2:
            size, pos = _varint(data, pos)
            out.append((number, data[pos : pos + size]))
            pos += size
        else:
            raise ValueError("unknown protobuf wire type")
    return out


def note_body(zdata: Optional[bytes]) -> str:
    """Text of a note: gzip, then protobuf Document(2) > Note(3) > text(2). Empty if undecodable."""
    if not zdata:
        return ""
    try:
        raw = gzip.decompress(bytes(zdata))
        document = next(v for n, v in _fields(raw) if n == 2)
        note = next(v for n, v in _fields(document) if n == 3)
        text = next(v for n, v in _fields(note) if n == 2)
    except (OSError, ValueError, StopIteration, IndexError):
        return ""
    return text.decode("utf-8", "replace").replace("￼", "").strip()


def list_notes(conn: sqlite3.Connection) -> List[Note]:
    """Live notes, newest first."""
    return [
        (t or "(untitled)", f or "", apple_date(m), bool(p), s or "", z)
        for _pk, t, s, m, p, f, z in conn.execute(SELECT)
    ]


def _line(n: Note) -> str:
    title, folder, date, protected, _snippet, _z = n
    return f"{date} | {folder} | {title}" + (" (protected)" if protected else "")


def search(notes: List[Note], text: str, limit: int) -> List[str]:
    """Notes whose title, snippet or body contain every word (accent and case insensitive)."""
    words = fold(text).split()
    out: List[str] = []
    for n in notes:
        title, _folder, _date, protected, snippet, zdata = n
        body = "" if protected else note_body(zdata)
        if all(w in fold(" ".join((title, snippet, body))) for w in words):
            excerpt = ""
            if not protected and words:
                at = fold(body).find(words[0])
                excerpt = " | " + one_line(body[max(at - 40, 0) :], 120)
            out.append(_line(n) + excerpt)
            if len(out) >= limit:
                break
    return out


def read(notes: List[Note], title: str) -> str:
    """Body of the most recent note whose title contains the query."""
    words = fold(title).split()
    for n in notes:
        if all(w in fold(n[0]) for w in words):
            if n[3]:
                return f"{n[0]}: password protected, not readable."
            return f"{_line(n)}\n\n{note_body(n[5])}"
    return "No note found."


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Apple Notes (read-only)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("list")
    p1.add_argument("--max", type=int, default=30)
    p2 = sub.add_parser("search")
    p2.add_argument("text")
    p2.add_argument("--max", type=int, default=20)
    p3 = sub.add_parser("read")
    p3.add_argument("title")
    args = parser.parse_args(argv)
    try:
        with open_ro(DB) as conn:
            notes = list_notes(conn)
    except (AccessError, FileNotFoundError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
    if args.cmd == "list":
        lines = [_line(n) for n in notes[: args.max]]
        print("\n".join(lines))
        print(f"{len(lines)} note(s) of {len(notes)}")
    elif args.cmd == "search":
        lines = search(notes, args.text, args.max)
        print("\n".join(lines))
        print(f"{len(lines)} result(s)")
    else:
        print(read(notes, args.title))
    return 0


if __name__ == "__main__":
    sys.exit(main())
