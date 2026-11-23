"""Shared helpers for the Apple connectors: read-only SQLite access, accents, Apple dates.

macOS only. Needs Full Disk Access for the app that runs the scripts (Terminal, or your editor).
Databases are opened with mode=ro; if the live file is locked, a temporary copy is read and
deleted afterwards. Nothing here ever writes to an Apple database.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Union
from urllib.parse import quote

# Seconds between the Unix epoch (1970) and the Apple epoch (2001-01-01).
APPLE_EPOCH = 978307200

ACCESS_HINT = "this app has no Full Disk Access (System Settings > Privacy & Security > Full Disk Access)"


class AccessError(Exception):
    """Access to an Apple database was denied or the file is unreadable."""


def _copy_db(path: Path, folder: Path) -> Path:
    try:
        for suffix in ("", "-wal", "-shm"):
            source = Path(str(path) + suffix)
            if source.exists():
                shutil.copy2(source, folder / (path.name + suffix))
    except PermissionError as err:
        raise AccessError(ACCESS_HINT) from err
    return folder / path.name


@contextmanager
def open_ro(path: Union[str, Path]) -> Iterator[sqlite3.Connection]:
    """Open a SQLite file read-only. Falls back to a throwaway copy when the live file is locked."""
    db = Path(path)
    if not db.exists():
        raise FileNotFoundError(f"database not found: {db}")
    tmp: Optional[Path] = None
    conn: Optional[sqlite3.Connection] = None
    try:
        try:
            conn = sqlite3.connect(f"file:{quote(str(db))}?mode=ro", uri=True)
            conn.execute("select count(*) from sqlite_master").fetchone()
        except sqlite3.DatabaseError:  # locked (OperationalError) or not a database at all
            if conn is not None:
                conn.close()
            if not os.access(db, os.R_OK):
                raise AccessError(ACCESS_HINT) from None
            tmp = Path(tempfile.mkdtemp(prefix="carlo_apple_"))
            copy = _copy_db(db, tmp)
            try:
                conn = sqlite3.connect(str(copy))
                conn.execute("select count(*) from sqlite_master").fetchone()
            except sqlite3.DatabaseError as err:
                raise AccessError(f"database unreadable ({err})") from err
        yield conn
    finally:
        if conn is not None:
            conn.close()
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


def fold(text: Optional[str]) -> str:
    """Lowercase without accents, for comparing."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def apple_date(value: Union[float, int, None]) -> str:
    """Apple timestamp (seconds, or nanoseconds in recent Messages) as local 'YYYY-MM-DD HH:MM'."""
    if not value:
        return "?"
    seconds = value / 1e9 if abs(value) > 1e11 else value
    return datetime.fromtimestamp(seconds + APPLE_EPOCH).strftime("%Y-%m-%d %H:%M")


def one_line(text: str, limit: int = 160) -> str:
    """Single-line text cut to `limit` characters."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "..."


def normalise_phone(number: str, default_country_code: Optional[str] = None) -> str:
    """Digits only, international form without '+'.

    A national number starting with 0 gets `default_country_code` (argument, or the
    CARLO_DEFAULT_COUNTRY_CODE environment variable, e.g. "1", "33", "44") when one is set.
    """
    digits = re.sub(r"\D", "", number)
    if digits.startswith("00"):
        return digits[2:]
    cc = default_country_code if default_country_code is not None else os.environ.get("CARLO_DEFAULT_COUNTRY_CODE", "")
    if cc and digits.startswith("0"):
        return cc + digits[1:]
    return digits


def same_number(a: str, b: str) -> bool:
    """True if two numbers are equal or share their last 9 digits (handles +CC / national forms)."""
    na, nb = normalise_phone(a), normalise_phone(b)
    if not na or not nb:
        return False
    return na == nb or (len(na) >= 9 and len(nb) >= 9 and na[-9:] == nb[-9:])
