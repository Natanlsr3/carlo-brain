"""Ranked briefing: at most N points, under a word budget, ending with one closed question.

Pure functions (testable) plus write_briefing(). Rule of thumb baked in:
- an item the assistant can act on (reply, nudge, calendar entry): the draft is prepared BEFORE
  speaking and the question is "X is ready: send it? (go / let me look)";
- plain information: no question;
- a decision only you can take (a deadline): a small closed question (yes / later).
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .model import Signal
from .paths import boot_dir, state_dir
from .text import clip_words, count_words, strip_dashes

BOOT_RULE = (
    "Proactive rule: for every actionable item below, prepare the draft first, then ask for a go. "
    "Information gets one line. A decision gets one small closed question. Nothing is sent without a go."
)


def score(signal: Signal, cfg: Dict[str, Any]) -> int:
    """Weight of the kind plus the signal's own bonus. Unknown kinds score 0."""
    rule = cfg["scoring"]["kinds"].get(signal.kind)
    return (rule["weight"] if rule else 0) + signal.bonus


def select(signals: Sequence[Signal], cfg: Dict[str, Any]) -> List[Signal]:
    """Top max_points by score (input order breaks ties), at most `cap` per kind."""
    ranked = sorted(enumerate(signals), key=lambda p: (-score(p[1], cfg), p[0]))
    count: Dict[str, int] = {}
    chosen: List[Signal] = []
    for _, s in ranked:
        rule = cfg["scoring"]["kinds"].get(s.kind)
        if rule is None or count.get(s.kind, 0) >= rule["cap"] or len(chosen) >= cfg["briefing"]["max_points"]:
            continue
        count[s.kind] = count.get(s.kind, 0) + 1
        chosen.append(s)
    return chosen


def outage_line(outages: Sequence[str]) -> str:
    """'Sources in outage: a; b' (3 shown), empty when everything works."""
    seen = list(dict.fromkeys(o.strip().lstrip("- ") for o in outages if o.strip()))
    if not seen:
        return ""
    more = f"; ... and {len(seen) - 3} more" if len(seen) > 3 else ""
    return "Sources in outage: " + "; ".join(clip_words(o, 14) for o in seen[:3]) + more


def render(points: Sequence[Signal], outages: Sequence[str], day: date, cfg: Dict[str, Any]) -> str:
    """Briefing text under max_words: the last points are dropped first, never the first."""
    limit = cfg["briefing"]["max_words"]
    per_point = cfg["briefing"]["words_per_point"]
    kept = list(points)
    while True:
        lines = [f"# Briefing for {day:%Y-%m-%d}"]
        lines += [f"{i}. {clip_words(p.title, per_point)}" for i, p in enumerate(kept, 1)] or ["Nothing important this morning."]
        warning = outage_line(outages)
        if warning:
            lines.append(warning)
        if kept and kept[0].question:
            lines += ["", f"Question: {kept[0].question}"]
        text = strip_dashes("\n".join(lines)) + "\n"
        if count_words(text) <= limit or len(kept) <= 1:
            return text if count_words(text) <= limit else hard_trim(text, limit)
        kept.pop()


def hard_trim(text: str, limit: int) -> str:
    """Last resort when point 1 plus the outage line is too long: drop the outage line, then cut words."""
    body = "\n".join(l for l in text.splitlines() if not l.startswith("Sources in outage")) + "\n"
    if count_words(body) <= limit:
        return body
    kept, used = [], 0
    for line in body.splitlines():
        room = limit - used
        if room <= 0:
            break
        words = line.split()
        kept.append(" ".join(words[:room]) + ("..." if len(words) > room else ""))
        used += min(len(words), room)
    return "\n".join(kept) + "\n"


def voice_outage(directory: Path) -> str:
    """If the last voice.log line is a failure, return one outage line (until a success clears it)."""
    try:
        last = (directory / "voice.log").read_text(encoding="utf-8").strip().splitlines()[-1]
    except (OSError, IndexError):
        return ""
    parts = last.split(" ", 2)
    if len(parts) >= 3 and parts[2].startswith("FAIL"):
        return f"Voice failed on {parts[0]} ({parts[2][5:].strip() or 'unknown cause'})"
    return ""


def build(signals: Sequence[Signal], outages: Sequence[str], day: date, cfg: Dict[str, Any],
          extra_outages: Sequence[str] = ()) -> str:
    """Select, then render."""
    return render(select(signals, cfg), [*outages, *extra_outages], day, cfg)


def write_briefing(text: str, cfg: Dict[str, Any], directory: Optional[Path] = None,
                   boot: Optional[Path] = None) -> None:
    """Write briefing.md and the short boot file the core injector picks up at session start."""
    directory = directory or state_dir()
    boot = boot or boot_dir()
    directory.mkdir(parents=True, exist_ok=True)
    boot.mkdir(parents=True, exist_ok=True)
    (directory / "briefing.md").write_text(text, encoding="utf-8")
    body = f"{BOOT_RULE}\n\n{text}"
    limit = cfg["briefing"]["boot_max_chars"]
    if len(body) > limit:
        body = body[: limit - 3].rstrip() + "..."
    (boot / "proactive.md").write_text(body, encoding="utf-8")


def generate(cfg: Dict[str, Any], now: datetime, directory: Optional[Path] = None,
             boot: Optional[Path] = None) -> str:
    """Read signals.json, build and write the briefing, return its text."""
    from .scan import load_signals  # local import: scan imports the sources

    directory = directory or state_dir()
    signals, outages = load_signals(directory)
    text = build(signals, outages, now.date(), cfg, [o for o in (voice_outage(directory),) if o])
    write_briefing(text, cfg, directory, boot)
    return text
