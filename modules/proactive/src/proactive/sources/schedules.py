"""Schedules that arrive by mail (work shifts, timetables, rotas) and never reach the calendar.

Looks at the last N days of Apple Mail for schedule words in the subject or a schedule-like
attachment (xlsx, ics, pdf, csv). For xlsx files already downloaded by Mail it previews the rows
that mention you. It never writes to the calendar: the assistant fills it in with you, then you
add a fragment of the subject to handled.txt so the mail stops coming back.
"""
from __future__ import annotations

import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set
from xml.etree import ElementTree

from ..model import Signal, SourceError, SourceResult, explain_outage
from ..paths import state_dir
from ..text import short, subject_key
from . import mail_apple

DEFAULT_WORDS = (
    r"schedule|timetable|shifts?|roster|rota|working hours|time ?sheet|week plan|class schedule|convocation"
)
USEFUL_FILE = re.compile(r"\.(?:xlsx|xls|pdf|ics|docx|csv)$", re.IGNORECASE)
MAX_BYTES = 2_000_000
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def words_regex(extra: Sequence[str]) -> "re.Pattern[str]":
    """Subject keyword regex (built-in words plus the user's)."""
    words = DEFAULT_WORDS + "".join("|" + re.escape(w) for w in extra if w.strip())
    return re.compile(rf"\b(?:{words})\b", re.IGNORECASE)


def load_handled(path: Path) -> Set[str]:
    """Subject fragments already handled (one per line, # comments)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {subject_key(x.split("#")[0]) for x in lines if x.split("#")[0].strip()}


def xlsx_rows(path: Path) -> List[List[str]]:
    """Rows of the first sheet as lists of text, standard library only. [] if oversized or unreadable."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            sheet = "xl/worksheets/sheet1.xml"
            if sheet not in names or zf.getinfo(sheet).file_size > MAX_BYTES:
                return []
            shared: List[str] = []
            if "xl/sharedStrings.xml" in names and zf.getinfo("xl/sharedStrings.xml").file_size <= MAX_BYTES:
                root = ElementTree.fromstring(zf.read("xl/sharedStrings.xml"))
                shared = ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")) for si in root.findall("m:si", NS)]
            rows = []
            for row in ElementTree.fromstring(zf.read(sheet)).iter(f"{{{NS['m']}}}row"):
                cells = []
                for c in row.findall("m:c", NS):
                    value = c.find("m:v", NS)
                    text = ""
                    if c.get("t") == "s" and value is not None and value.text and value.text.isdigit():
                        idx = int(value.text)
                        text = shared[idx] if idx < len(shared) else ""
                    elif c.get("t") == "inlineStr":
                        text = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
                    elif value is not None:
                        text = value.text or ""
                    cells.append(text.strip())
                if any(cells):
                    rows.append(cells)
            return rows
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError, KeyError):
        return []


def rows_about_me(rows: Sequence[Sequence[str]], names: Sequence[str], limit: int = 6) -> List[str]:
    """Rows mentioning one of your names, each as 'cell | cell | ...' (empty if no names configured)."""
    mine = [n.lower() for n in names if n]
    if not mine:
        return []
    hits = [" | ".join(c for c in row if c) for row in rows if any(n in " ".join(row).lower() for n in mine)]
    return [short(h, 120) for h in hits[:limit]]


def find(
    mails: Sequence[mail_apple.MailRow],
    keywords: "re.Pattern[str]",
    handled: Set[str],
    attachments_of=lambda rowid: [],
    names: Sequence[str] = (),
    limit: int = 5,
) -> List[Signal]:
    """Schedule mails not yet handled, newest first, one per subject."""
    out: List[Signal] = []
    seen: Set[str] = set()
    for rowid, date, sender, subject, files, _read in reversed(mails):
        key = subject_key(subject)
        if key in seen or any(h and h in key for h in handled):
            continue
        has_file = any(USEFUL_FILE.search(f) for f in files)
        if not (keywords.search(subject) or (has_file and keywords.search(" ".join(files)))):
            continue
        if mail_apple.AUTOMATED_SENDER.search(sender) and not has_file:
            continue
        seen.add(key)
        detail: List[str] = []
        for path in attachments_of(rowid):
            if path.suffix.lower() == ".xlsx":
                detail += rows_about_me(xlsx_rows(path), names)
        title = f"Schedule to add to the calendar: '{short(subject, 60)}' ({date[5:16]})"
        out.append(
            Signal("schedule", title, "schedules", detail=tuple(detail),
                   question=f"Schedule '{short(subject, 40)}' ready for the calendar: add it? (go / let me look)")
        )
        if len(out) >= limit:
            break
    return out


def collect(cfg: Dict[str, Any], now: datetime, handled_file: Optional[Path] = None) -> SourceResult:
    """Run the schedules source (needs apple_mail access)."""
    own = cfg["sources"]["schedules"]
    result = SourceResult()
    try:
        index = mail_apple.find_index(cfg["sources"]["apple_mail"]["root"] or None)
        mails = mail_apple.recent(index, now - timedelta(days=own["days"]))
        files = mail_apple.MailFiles(index.parents[2])
    except (SourceError, OSError) as err:
        result.outages.append(explain_outage("Schedules (mail)", err))
        return result
    except Exception as err:  # noqa: BLE001 - sqlite3.Error and friends: report, do not crash the scan
        result.outages.append(explain_outage("Schedules (mail)", err))
        return result
    handled = load_handled(handled_file or state_dir() / "handled.txt")
    result.signals = find(mails, words_regex(own["keywords"]), handled, files.attachments,
                          cfg["identity"]["names"], own["max_items"])
    return result
