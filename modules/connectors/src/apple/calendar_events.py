"""Upcoming events from the macOS Calendar database, read-only (beta).

Usage: calendar_events.py [--days 7] [--calendar NAME] [--json]

Reads Calendar.sqlitedb (events including recurring occurrences, cancelled ones skipped). This
needs no calendar permission, only Full Disk Access, and works with iCloud, Google and Exchange
accounts added to the Calendar app. The table layout is private: checked on macOS 15, may change.
If it breaks, use the Google Calendar connector (connectors/google) instead.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import APPLE_EPOCH, AccessError, open_ro  # noqa: E402

CANDIDATES = (
    "~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb",
    "~/Library/Calendars/Calendar.sqlitedb",
)
CANCELLED = 3  # EKEventStatusCanceled

QUERY = (
    "select o.occurrence_start_date, o.occurrence_end_date, i.summary, i.all_day, c.title"
    " from OccurrenceCache o join CalendarItem i on i.ROWID = o.event_id"
    " left join Calendar c on c.ROWID = o.calendar_id"
    " where o.occurrence_start_date < ? and o.occurrence_end_date >= ? and coalesce(i.status, 0) != ?"
    " order by o.occurrence_start_date"
)


def find_database() -> str:
    """First existing Calendar database. Raises FileNotFoundError."""
    for candidate in CANDIDATES:
        path = os.path.expanduser(candidate)
        if os.path.exists(path):
            return path
    raise FileNotFoundError("Calendar database not found (is the Calendar app set up?)")


def upcoming(conn: sqlite3.Connection, start: float, end: float, calendar: Optional[str] = None) -> List[Dict[str, object]]:
    """Events overlapping [start, end] (Unix seconds), as dicts."""
    rows = conn.execute(QUERY, (end - APPLE_EPOCH, start - APPLE_EPOCH, CANCELLED)).fetchall()
    events = []
    for began, ended, summary, all_day, cal in rows:
        if calendar and (cal or "").lower() != calendar.lower():
            continue
        events.append({
            "start": datetime.fromtimestamp(began + APPLE_EPOCH).strftime("%Y-%m-%d %H:%M"),
            "end": datetime.fromtimestamp(ended + APPLE_EPOCH).strftime("%Y-%m-%d %H:%M"),
            "title": summary or "(no title)",
            "all_day": bool(all_day),
            "calendar": cal or "",
        })
    return events


def format_event(e: Dict[str, object]) -> str:
    """One line per event; all-day events show the date only."""
    when = str(e["start"])[:10] + " (all day)" if e["all_day"] else f"{e['start']} - {str(e['end'])[11:]}"
    return f"{when} | {e['title']}" + (f" [{e['calendar']}]" if e["calendar"] else "")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Upcoming calendar events (read-only)")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--calendar")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    now = time.time()
    try:
        with open_ro(find_database()) as conn:
            events = upcoming(conn, now, now + args.days * 86400, args.calendar)
    except (AccessError, FileNotFoundError, sqlite3.Error) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=1))
    else:
        print("\n".join(format_event(e) for e in events))
        print(f"{len(events)} event(s) in the next {args.days} day(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
