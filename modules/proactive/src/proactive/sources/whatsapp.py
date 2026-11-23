"""WhatsApp signals from the local database of the whatsapp-mcp bridge (read-only, no LLM).

Keeps three things: groups where several people talk about an action, messages that mention
you, and private chats whose last message is not yours. Setup: modules/connectors/whatsapp.
Table layout expected (lharries/whatsapp-mcp): messages(chat_jid, content, timestamp,
is_from_me, media_type) and chats(jid, name); optional whatsapp.db with whatsmeow_contacts.
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from ..model import Signal, SourceError, SourceResult, explain_outage
from ..paths import brain_home, state_dir
from ..text import short

# (chat_jid, chat_name, content, timestamp, is_from_me)
Row = Tuple[str, str, str, str, int]

ACTION_WORDS = (
    r"qr|check.?in|forms?|sign.?up|register\w*|deadline|due (?:date|by)|mandatory|attendance|don.t forget"
    r"|reminder|urgent|poll|vote|rsvp|doodle|pay(?:ment)?|before (?:tonight|tomorrow|midnight|noon|monday|friday)"
    r"|who.s coming|are you free|availab\w+|please confirm|asap|by (?:eod|end of day)"
)


def usual_places() -> Tuple[Path, ...]:
    """Where the bridge database usually lives (evaluated at call time so CARLO_BRAIN_HOME is honoured)."""
    return (
        Path.home() / "whatsapp-mcp" / "whatsapp-bridge" / "store" / "messages.db",
        brain_home() / "data" / "whatsapp-mcp" / "whatsapp-bridge" / "store" / "messages.db",
    )


def action_regex(extra: Sequence[str]) -> "re.Pattern[str]":
    """Keyword regex: built-in action words plus the user's own keywords (escaped)."""
    words = ACTION_WORDS + "".join("|" + re.escape(w) for w in extra if w.strip())
    return re.compile(rf"\b(?:{words})\b", re.IGNORECASE)


def find_db(configured: str = "") -> Path:
    """Configured path, else the first usual location that exists. Raises SourceError."""
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return path
        raise SourceError(f"WhatsApp database not found: {path}")
    for candidate in usual_places():
        if candidate.exists():
            return candidate
    raise SourceError("WhatsApp bridge database not found (set sources.whatsapp.db in the config)")


def parse_ts(value: str) -> datetime:
    """Bridge timestamp (ISO, with or without zone) -> naive local datetime."""
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed


def load_names(db: Path) -> Dict[str, str]:
    """jid -> display name from the bridge address book (empty if the file is missing)."""
    book = db.parent / "whatsapp.db"
    if not book.exists():
        return {}
    names: Dict[str, str] = {}
    with sqlite3.connect(f"file:{book}?mode=ro", uri=True) as con:
        for jid, full, push in con.execute("SELECT their_jid, full_name, push_name FROM whatsmeow_contacts"):
            if full or push:
                names[jid] = full or push
        try:
            for lid, number in con.execute("SELECT lid, pn FROM whatsmeow_lid_map"):
                name = names.get(f"{number}@s.whatsapp.net") or names.get(f"{lid}@lid")
                if name:
                    names[f"{lid}@lid"] = name
        except sqlite3.Error:
            pass  # older bridge without the LID map
    return names


def read_rows(db: Path, since: datetime) -> List[Row]:
    """Messages since `since`, oldest first. Raises sqlite3.Error if unreadable."""
    cutoff = since.strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
        return con.execute(
            "SELECT m.chat_jid, c.name, m.content, m.timestamp, m.is_from_me FROM messages m"
            " LEFT JOIN chats c ON c.jid = m.chat_jid WHERE m.timestamp >= ? ORDER BY m.timestamp",
            (cutoff,),
        ).fetchall()


def name_rows(rows: Sequence[Row], names: Dict[str, str]) -> List[Row]:
    """Private chats take the address-book name (the bridge sometimes reuses one name for many chats)."""
    out: List[Row] = []
    for jid, name, content, ts, mine in rows:
        if not jid.endswith("@g.us"):
            name = names.get(jid) or jid.split("@")[0]
        elif not name:
            name = names.get(jid, jid)
        out.append((jid, name, content, ts, mine))
    return out


def analyse(
    rows: Sequence[Row], identity_names: Sequence[str], extra_keywords: Sequence[str] = (), min_group: int = 3
) -> Tuple[Dict[str, Dict[str, Any]], List[Tuple[str, str, str]], Dict[str, Tuple[str, str]]]:
    """Return (busy groups, mentions, private chats waiting on you)."""
    action = action_regex(extra_keywords)
    mention = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in identity_names if n) + r")\b", re.I) if any(identity_names) else None
    groups: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"name": "", "n": 0, "words": defaultdict(int), "examples": []})
    mentions: List[Tuple[str, str, str]] = []
    last_private: Dict[str, Tuple[str, str, int]] = {}
    for jid, name, content, ts, mine in rows:
        text = content or ""
        if jid.endswith("@g.us"):
            hits = {m.group(0).lower() for m in action.finditer(text)}
            if hits and not mine:
                g = groups[jid]
                g["name"] = name or jid
                g["n"] += 1
                for h in hits:
                    g["words"][h] += 1
                if len(g["examples"]) < 3 and len(text) > 15:
                    g["examples"].append(f"{ts[11:16]} {short(text, 140)}")
            if mention and not mine and mention.search(text):
                mentions.append((name or jid, ts[:16], short(text, 140)))
        elif not jid.endswith(("@broadcast", "@newsletter")):
            last_private[jid] = (name or jid, short(text, 140), mine)
    busy = {j: g for j, g in groups.items() if g["n"] >= min_group}
    waiting = {j: (n, t) for j, (n, t, mine) in last_private.items() if not mine and t}
    return busy, mentions, waiting


def write_raw(rows: Sequence[Row], path: Path) -> None:
    """Full thread dump for the weekly LLM triage pass. Private (0600), local only."""
    threads: Dict[str, List[str]] = defaultdict(list)
    for jid, name, content, ts, mine in rows:
        if jid.endswith("@broadcast") or not (content or "").strip():
            continue
        title = f"{name} ({'group' if jid.endswith('@g.us') else 'private'})"
        threads[title].append(f"{ts[5:16]} {'me' if mine else '.'}: {short(content, 300)}")
    lines: List[str] = []
    for title, msgs in threads.items():
        lines += [f"## {title}", *msgs, ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    path.chmod(0o600)


def collect(cfg: Dict[str, Any], now: datetime) -> SourceResult:
    """Run the WhatsApp source. Outages are reported, never swallowed."""
    own = cfg["sources"]["whatsapp"]
    result = SourceResult()
    try:
        db = find_db(own["db"])
        rows = read_rows(db, now - timedelta(hours=cfg["lookback_hours"]))
        try:
            names = load_names(db)
        except sqlite3.Error as err:
            names = {}
            result.outages.append(explain_outage("WhatsApp address book (numbers shown instead)", err))
    except (SourceError, OSError, sqlite3.Error) as err:
        result.outages.append(explain_outage("WhatsApp", err))
        return result
    rows = name_rows(rows, names)
    if own["write_raw"]:
        write_raw(rows, state_dir() / "raw_messages.md")
    busy, mentions, waiting = analyse(rows, cfg["identity"]["names"], own["extra_keywords"], own["group_min_messages"])
    for g in sorted(busy.values(), key=lambda g: -g["n"]):
        top = ", ".join(f"{w} x{n}" for w, n in sorted(g["words"].items(), key=lambda x: -x[1])[:3])
        result.signals.append(
            Signal("group_activity", f"Group '{g['name']}' is discussing an action ({g['n']} messages: {top})",
                   "whatsapp", detail=tuple(g["examples"]))
        )
    for chat, when, text in mentions[-5:]:
        result.signals.append(Signal("mention", f"{chat} mentions you ({when[5:]})", "whatsapp", detail=(text,)))
    for name, text in list(waiting.values())[-8:]:
        result.signals.append(
            Signal("direct_unanswered", f"{name} wrote last on WhatsApp", "whatsapp",
                   question=f"Reply to {name} ready: send it? (go / let me look)", detail=(text,))
        )
    return result
