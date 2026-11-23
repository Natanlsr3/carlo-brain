"""Meeting slots mentioned in messages ("Thursday at 3pm"), so none is missing from your calendar.

The module cannot read your calendar. It lists the slots; the assistant compares them with the
calendar at session start (any calendar connector works, see modules/connectors).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Sequence

from ..model import Signal, SourceError, SourceResult, explain_outage
from . import mail_apple, whatsapp
from ..text import short

DAYS = (
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun|tomorrow|today|tonight"
    r"|next week|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2}|\d{1,2}(?:st|nd|rd|th)?"
    r" (?:of )?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*|\d{1,2}/\d{1,2}"
)
TIME = r"\d{1,2}:\d{2}\s?(?:am|pm)?|\d{1,2}\s?(?:am|pm)|\d{1,2}\s?h\s?\d{0,2}|noon"
SLOT = re.compile(
    rf"\b(?:{DAYS})\b[^.\n?!]{{0,40}}?\b(?:{TIME})(?!\w)|\b(?:{TIME})\b[^.\n?!]{{0,25}}?\b(?:{DAYS})\b", re.IGNORECASE
)
QUOTED = re.compile(r"\bon .{0,90}? wrote\s*:|-----Original|_{10,}|^\s*From:\s", re.IGNORECASE | re.MULTILINE)
MASS_MAIL = re.compile(r"unsubscribe|view (?:it )?in (?:your )?browser|manage (?:your )?preferences|email sent to", re.I)
CALENDAR_SUBJECT = re.compile(r"^(?:invitation|updated invitation|accepted|declined|canceled|cancelled)\b", re.IGNORECASE)


def find(text: str) -> List[str]:
    """Short excerpts around each slot, ignoring the quoted part of a mail."""
    body = text or ""
    quoted = QUOTED.search(body)
    if quoted:
        body = body[: quoted.start()]
    out = []
    for m in SLOT.finditer(body):
        start, end = max(0, m.start() - 50), min(len(body), m.end() + 30)
        out.append(re.sub(r"\s+", " ", body[start:end]).strip())
    return out


def from_chats(rows: Iterable[whatsapp.Row]) -> List[str]:
    """Slots in private chats only (groups are too noisy)."""
    lines = []
    for jid, name, content, ts, mine in rows:
        if jid.endswith(("@g.us", "@broadcast", "@newsletter")):
            continue
        for excerpt in find(content)[:1]:
            lines.append(f"{ts[5:16]} WhatsApp {name} ({'me' if mine else 'them'}): \"{excerpt}\"")
    return lines


def from_mail(
    mails: Iterable[mail_apple.MailRow], read_body: mail_apple.BodyReader, people: Sequence[str], direct: set
) -> List[str]:
    """Slots in mail from real people (known sender or addressed to you), not newsletters or invitations."""
    lines, seen = [], set()
    known = {p.lower() for p in people}
    for rowid, date, sender, subject, _files, _read in mails:
        if mail_apple.AUTOMATED_SENDER.search(sender) or CALENDAR_SUBJECT.search(subject):
            continue
        if sender not in known and rowid not in direct:
            continue
        body = read_body(rowid)
        if MASS_MAIL.search(body):
            continue
        for excerpt in find(f"{subject}\n{body}")[:1]:
            if (sender, subject) not in seen:
                seen.add((sender, subject))
                lines.append(f"{date[5:16]} mail {sender} '{short(subject, 50)}': \"{excerpt}\"")
    return lines


def summarise(lines: Sequence[str], limit: int) -> List[Signal]:
    """One info signal that carries the slot lines as detail."""
    if not lines:
        return []
    n = len(lines)
    title = f"{n} meeting slot{'s' if n > 1 else ''} mentioned in messages, check them against the calendar"
    return [Signal("slot", title, "slots", detail=tuple(sorted(lines)[-limit:]))]


def collect(cfg: Dict[str, Any], now: datetime) -> SourceResult:
    """Scan WhatsApp private chats and Apple Mail for slots (each part optional)."""
    result = SourceResult()
    since = now - timedelta(hours=cfg["lookback_hours"])
    lines: List[str] = []
    wa = cfg["sources"]["whatsapp"]
    if wa["enabled"]:
        try:
            db = whatsapp.find_db(wa["db"])
            lines += from_chats(whatsapp.name_rows(whatsapp.read_rows(db, since), whatsapp.load_names(db)))
        except Exception as err:  # noqa: BLE001 - one source failing must not stop the others
            result.outages.append(explain_outage("Slots (WhatsApp)", err))
    mail = cfg["sources"]["apple_mail"]
    if mail["enabled"]:
        try:
            index = mail_apple.find_index(mail["root"] or None)
            files = mail_apple.MailFiles(index.parents[2])
            direct = mail_apple.direct_ids(index, since, cfg["identity"]["addresses"])
            lines += from_mail(mail_apple.recent(index, since), files.body, [], direct)
        except (SourceError, OSError) as err:
            result.outages.append(explain_outage("Slots (mail)", err))
        except Exception as err:  # noqa: BLE001
            result.outages.append(explain_outage("Slots (mail)", err))
    result.signals = summarise(lines, cfg["sources"]["slots"]["max_items"])
    return result
