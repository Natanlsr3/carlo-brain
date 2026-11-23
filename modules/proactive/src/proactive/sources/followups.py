"""Follow-ups: who replied to you, and who you are still waiting on. No LLM, read-only.

Builds one thread per person from WhatsApp private chats and Apple Mail sent items. A thread is
"open" when your last message expects an answer (question, request, slot) and nothing came back.
State is kept in followups.json: tracked threads, plus replies kept visible for a while.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from ..model import Signal, SourceError, SourceResult, explain_outage
from ..paths import state_dir
from ..text import short, subject_key
from . import mail_apple, slots, whatsapp
from .mail import load_contacts

FORMAT = "%Y-%m-%d %H:%M:%S"
CLOSING = re.compile(
    r"^(?:thanks|thank you|ok|okay|great|perfect|cool|sure|sounds good|got it|noted|see you|talk soon"
    r"|good night|have a (?:good|nice|great) \w+|cheers)\b[^?]{0,20}$",
    re.IGNORECASE,
)
MAIL_CLOSING = re.compile(r"^(?:hi[^,\n]{0,40},?\s*)?(?:thanks|thank you|perfect|received|great|noted|ok)\b", re.IGNORECASE)
EXPECTS_ANSWER = re.compile(
    r"\?|\b(?:are you (?:free|available)|can you|could you|would you|let me know|please (?:confirm|send|reply)"
    r"|what do you think|do you have|when (?:can|are)|any update|did you (?:see|get)|ok for|works for you)\b",
    re.IGNORECASE,
)
LINK_ONLY = re.compile(r"https?://\S+")
Thread = Dict[str, Any]
Message = Tuple[datetime, bool, str, Optional[int]]  # when, from_me, text, mail rowid


def threads_from_chats(rows: Sequence[Tuple], names: Dict[str, str]) -> Dict[str, Thread]:
    """rows = (chat_jid, content, timestamp, is_from_me, media_type), private chats only."""
    threads: Dict[str, Thread] = {}
    for jid, content, ts, mine, media in rows:
        if jid.endswith(("@g.us", "@broadcast", "@newsletter")):
            continue
        text = (content or "").strip() or (f"[{media}]" if media else "")
        if not text:
            continue
        thread = threads.setdefault(
            f"wa:{jid}", {"name": (names.get(jid) or jid.split("@")[0]).strip(), "channel": "WhatsApp", "messages": []}
        )
        thread["messages"].append((whatsapp.parse_ts(ts), bool(mine), text, None))
    return threads


def threads_from_mail(
    sent: Sequence[Tuple], received: Sequence[Tuple], contacts: Dict[str, str], mine: Sequence[str]
) -> Dict[str, Thread]:
    """sent = (rowid, epoch, to_address, to_name, subject); received = (rowid, epoch, from_address, subject)."""
    own = {a.lower() for a in mine}
    threads: Dict[str, Thread] = {}
    for rowid, epoch, address, name, subject in sent:
        address = (address or "").lower()
        if address in own or mail_apple.AUTOMATED_SENDER.search(address) or slots.CALENDAR_SUBJECT.search(subject or ""):
            continue
        thread = threads.setdefault(
            f"mail:{address}",
            {"name": contacts.get(address) or name or address.split("@")[0], "channel": "mail", "messages": []},
        )
        thread["messages"].append((datetime.fromtimestamp(epoch), True, subject or "", rowid))
    for rowid, epoch, address, subject in received:
        thread = threads.get(f"mail:{(address or '').lower()}")
        if thread is not None and not mail_apple.AUTO_REPLY.search(subject or ""):
            thread["messages"].append((datetime.fromtimestamp(epoch), False, subject or "", rowid))
    for thread in threads.values():
        thread["messages"].sort(key=lambda m: m[0])
    return threads


def broadcasts(threads: Dict[str, Thread], threshold: int = 3) -> Set[str]:
    """Texts you sent to `threshold` people or more: a broadcast, not a wait."""
    who: Dict[str, Set[str]] = {}
    for key, thread in threads.items():
        for _when, mine, text, _row in thread["messages"]:
            if mine and len(subject_key(text)) >= 8:
                who.setdefault(subject_key(text), set()).add(key)
    return {k for k, v in who.items() if len(v) >= threshold}


def expects_answer(thread: Thread, text: str, rowid: Optional[int], read_body: Callable[[int], str]) -> bool:
    """WhatsApp: a question, request or slot. Mail: yes, unless it is a closing reply (thanks, noted)."""
    if thread["channel"] == "WhatsApp":
        return bool(EXPECTS_ANSWER.search(text) or slots.find(text))
    if rowid is not None and re.match(r"\s*(?:re|fw|fwd|tr)\s*:", text, re.IGNORECASE):
        head = re.split(slots.QUOTED, read_body(rowid) or "")[0].strip()
        return not (len(head) <= 250 and "?" not in head and MAIL_CLOSING.match(head))
    return True


def open_threads(
    threads: Dict[str, Thread],
    now: datetime,
    max_wait: timedelta,
    ignore: Set[str],
    read_body: Callable[[int], str] = lambda _: "",
) -> Dict[str, Dict[str, Any]]:
    """Threads whose last message is yours, recent enough, and expects an answer."""
    mass = broadcasts(threads)
    found: Dict[str, Dict[str, Any]] = {}
    for key, thread in threads.items():
        if not thread["messages"]:
            continue
        when, mine, text, rowid = thread["messages"][-1]
        age = now - when
        if not mine or age > max_wait or age < timedelta(0):
            continue
        if (len(text) <= 40 and CLOSING.match(text) and not EXPECTS_ANSWER.search(text)) or LINK_ONLY.fullmatch(text):
            continue
        if subject_key(text) in mass:
            continue
        ident = key.split(":", 1)[1].lower()
        if {thread["name"].lower(), ident, ident.split("@")[0]} & ignore:
            continue
        if not expects_answer(thread, text, rowid, read_body):
            continue
        found[key] = {
            "name": thread["name"],
            "channel": thread["channel"],
            "since": when.strftime(FORMAT),
            "excerpt": short(text, 60),
            "asked": "?" in text,
        }
    return found


def update(
    threads: Dict[str, Thread],
    state: Dict[str, Any],
    now: datetime,
    channels_ok: Set[str],
    cfg: Dict[str, Any],
    read_body: Callable[[int], str] = lambda _: "",
) -> Dict[str, Any]:
    """New state (the old one is not modified). A broken channel keeps its tracked threads as they were."""
    opts = cfg["sources"]["followups"]
    max_wait = timedelta(days=opts["max_wait_days"])
    keep = timedelta(hours=opts["keep_replies_hours"])
    replies = [r for r in state.get("replies", []) if now - datetime.strptime(r["seen"], FORMAT) < keep]
    tracked: Dict[str, Dict[str, Any]] = {}
    for key, entry in state.get("tracked", {}).items():
        since = datetime.strptime(entry["since"], FORMAT)
        if entry["channel"] not in channels_ok:
            if now - since <= max_wait:
                tracked[key] = entry
            continue
        msg = next((m for m in threads.get(key, {}).get("messages", []) if not m[1] and m[0] > since), None)
        if msg:
            body = ""
            if msg[3] is not None:
                body = short(re.split(slots.QUOTED, read_body(msg[3]) or "")[0], 150)
            replies.append(
                {
                    "key": key,
                    "name": entry["name"],
                    "channel": entry["channel"],
                    "when": msg[0].strftime(FORMAT),
                    "excerpt": body or short(msg[2], 150),
                    "seen": now.strftime(FORMAT),
                }
            )
    ignore = {i.lower() for i in opts["ignore"]}
    tracked.update(open_threads(threads, now, max_wait, ignore, read_body))
    return {"tracked": tracked, "replies": replies}


def to_signals(state: Dict[str, Any], now: datetime, cfg: Dict[str, Any]) -> List[Signal]:
    """Replies that arrived, and threads waiting longer than min_wait_days."""
    important = {n.lower() for n in cfg["scoring"]["important_names"]}
    bonus_important = cfg["scoring"]["important_bonus"]
    min_wait = timedelta(days=cfg["sources"]["followups"]["min_wait_days"])
    out: List[Signal] = []
    for r in sorted(state.get("replies", []), key=lambda r: r["when"], reverse=True)[:10]:
        out.append(
            Signal(
                "reply",
                f"{r['name']} replied ({r['channel']}): {r['excerpt']}",
                "followups",
                bonus=bonus_important if r["name"].lower() in important else 0,
                question=f"Answer to {r['name']} ready ({r['channel']}): send it? (go / let me look)",
            )
        )
    waiting = []
    for entry in state.get("tracked", {}).values():
        age = now - datetime.strptime(entry["since"], FORMAT)
        if age >= min_wait:
            waiting.append((age, entry))
    waiting.sort(key=lambda x: (x[1]["asked"], x[0]), reverse=True)
    for age, e in waiting[:10]:
        days = age.days
        out.append(
            Signal(
                "followup",
                f"Waiting on {e['name']} ({e['channel']}, {days} d): {e['excerpt']}",
                "followups",
                bonus=(5 if e["asked"] else 0) + min(days, 20) // 10,
                question=f"Nudge to {e['name']} ready ({days} d without reply): send it? (go / let me look)",
            )
        )
    return out


def load_state(path: Path) -> Dict[str, Any]:
    """Previous state, empty if absent or corrupt."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: Dict[str, Any], path: Path) -> None:
    """Atomic write (temp file then replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(path)


def collect(cfg: Dict[str, Any], now: datetime, state_file: Optional[Path] = None) -> SourceResult:
    """Read the enabled channels, update the state, return signals."""
    opts = cfg["sources"]["followups"]
    result = SourceResult()
    since = now - timedelta(days=opts["max_wait_days"] + 1)
    threads: Dict[str, Thread] = {}
    ok: Set[str] = set()
    read_body: Callable[[int], str] = lambda _: ""
    if "whatsapp" in opts["channels"] and cfg["sources"]["whatsapp"]["enabled"]:
        try:
            db = whatsapp.find_db(cfg["sources"]["whatsapp"]["db"])
            names = whatsapp.load_names(db)
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
                rows = con.execute(
                    "SELECT chat_jid, content, timestamp, is_from_me, media_type FROM messages WHERE timestamp >= ?"
                    " AND chat_jid NOT LIKE '%@g.us' AND chat_jid NOT LIKE '%@broadcast' ORDER BY timestamp",
                    (since.strftime("%Y-%m-%d"),),
                ).fetchall()
            threads.update(threads_from_chats(rows, names))
            ok.add("WhatsApp")
        except (SourceError, OSError, sqlite3.Error) as err:
            result.outages.append(explain_outage("Follow-ups (WhatsApp)", err))
    if "mail" in opts["channels"] and cfg["sources"]["apple_mail"]["enabled"]:
        try:
            index = mail_apple.find_index(cfg["sources"]["apple_mail"]["root"] or None)
            sent, received = mail_apple.sent_and_received(index, since, cfg["identity"]["addresses"])
            contacts = load_contacts(cfg["contacts"]["csv"])
            threads.update(threads_from_mail(sent, received, contacts, cfg["identity"]["addresses"]))
            read_body = mail_apple.MailFiles(index.parents[2]).body
            ok.add("mail")
        except (SourceError, OSError, sqlite3.Error) as err:
            result.outages.append(explain_outage("Follow-ups (mail)", err))
    path = state_file or state_dir() / "followups.json"
    state = update(threads, load_state(path), now, ok, cfg, read_body)
    if ok:
        save_state(state, path)
    result.signals = to_signals(state, now, cfg)
    return result
