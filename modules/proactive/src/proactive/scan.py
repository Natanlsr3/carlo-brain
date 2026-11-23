"""Run every enabled source, collect signals and outages, write the human readable digest."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from .model import Signal, SourceResult, explain_outage
from .paths import state_dir
from .sources import followups, schedules, slots, todo, whatsapp
from .sources import mail as mail_source

# Source name in the config -> collect function. Order = order in the digest.
SOURCES: List[Tuple[str, Callable[[Dict[str, Any], datetime], SourceResult]]] = [
    ("followups", followups.collect),
    ("schedules", schedules.collect),
    ("todo", todo.collect),
    ("whatsapp", whatsapp.collect),
    ("apple_mail", mail_source.collect),
    ("slots", slots.collect),
]


def scan(cfg: Dict[str, Any], now: datetime) -> SourceResult:
    """Collect from enabled sources. A crashing source becomes an outage line, it never hides the others."""
    merged = SourceResult()
    for name, collect in SOURCES:
        if not cfg["sources"][name]["enabled"]:
            continue
        try:
            part = collect(cfg, now)
        except Exception as err:  # noqa: BLE001 - last line of defence, reported not swallowed
            merged.outages.append(explain_outage(name, err))
            continue
        merged.signals.extend(part.signals)
        merged.outages.extend(part.outages)
    merged.outages[:] = list(dict.fromkeys(merged.outages))
    return merged


def digest_markdown(result: SourceResult, now: datetime) -> str:
    """Digest grouped by kind, outages first."""
    lines = [f"# Signals ({now:%Y-%m-%d %H:%M})", ""]
    if result.outages:
        lines += ["## Sources in outage", *[f"- {o}" for o in result.outages], ""]
    by_kind: Dict[str, List[Signal]] = {}
    for s in result.signals:
        by_kind.setdefault(s.kind, []).append(s)
    for kind, items in by_kind.items():
        lines.append(f"## {kind.replace('_', ' ')}")
        for s in items:
            lines.append(f"- {s.title}")
            lines += [f"    - {d}" for d in s.detail]
        lines.append("")
    if len(lines) == 2:
        lines.append("Nothing to report.")
    return "\n".join(lines) + "\n"


def write_outputs(result: SourceResult, now: datetime, directory: Path = None) -> Path:
    """Write signals.json (machine) and digest.md (human) into the state directory."""
    directory = directory or state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"generated": now.strftime("%Y-%m-%d %H:%M:%S"), "outages": result.outages,
               "signals": [asdict(s) for s in result.signals]}
    (directory / "signals.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    (directory / "digest.md").write_text(digest_markdown(result, now), encoding="utf-8")
    return directory / "signals.json"


def load_signals(directory: Path = None) -> Tuple[List[Signal], List[str]]:
    """Read signals.json back. Missing file = no signals and an outage line (never a silent empty briefing)."""
    path = (directory or state_dir()) / "signals.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], ["scan has not run yet (no signals.json)"]
    signals = [Signal(**{**s, "detail": tuple(s.get("detail", ()))}) for s in data.get("signals", [])]
    return signals, list(data.get("outages", []))
