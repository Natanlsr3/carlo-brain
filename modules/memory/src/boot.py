#!/usr/bin/env python3
"""SessionStart hook: inject a short, hard-capped context (recent sessions, signals, pending items).

SYSTEM_PROMPT and MAP are imported by CLAUDE.md, so they are not repeated here. Other modules can
add signals by dropping `*.md` files in ~/.carlo-brain/state/boot.d/ (a file whose first line is
`<!-- once -->` is deleted after it has been shown). This script never raises: a broken hook must
not block the session.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _lib in (os.environ.get("CARLO_LIB"), str(Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain") / "lib")):
    if _lib:
        sys.path.insert(0, _lib)
import carlo_config as cfg  # noqa: E402
import filters  # noqa: E402
import health  # noqa: E402
import sessionlog  # noqa: E402

MAX_CONTEXT = 9000  # Claude Code truncates hook output around 10,000 characters
MAX_ENTRY = 1500
MAX_DROPIN = 1500
N_ENTRIES = 4
ONCE = "<!-- once -->"


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def dropins(folder: Path) -> list:
    """Sections from boot.d/*.md. `once` files are removed after being read."""
    sections = []
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        text = read(path).strip()
        if not text:
            continue
        once = text.startswith(ONCE)
        body = text[len(ONCE):].strip() if once else text
        sections.append((f"Signal: {path.stem}", clip_block(body, MAX_DROPIN)))
        if once:
            try:
                path.unlink()
            except OSError:
                pass
    return sections


def clip_block(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "\n[...] (cut, read the source file)"


def facts_pending(queue: Path) -> int:
    """Open items in FACTS_TO_VALIDATE.md, not counting ones flagged suspect."""
    return sum(1 for line in read(queue).splitlines() if line.startswith("- [ ] ") and "(suspect" not in line)


def compaction_note(event: dict) -> Optional[tuple]:
    """After a compaction, point to the mechanical summary written by the PreCompact hook."""
    if event.get("source") != "compact":
        return None
    session = re.sub(r"[^A-Za-z0-9_-]", "", str(event.get("session_id") or ""))
    folder = cfg.state_dir() / "compactions"
    found = sorted(folder.glob(f"{session}_*.md" if session else "*.md"), key=lambda p: p.stat().st_mtime) if folder.is_dir() else []
    if not found:
        return None
    return ("After compaction", f"Context was compacted. A mechanical summary from before is in {found[-1]} "
            "(last messages, changed files, git commands, decisions). Re-read it if a detail is missing.")


def project_entries(entries: list, cwd: Path, projects: dict) -> tuple:
    """(project name, entry file, related log entries) when the cwd matches a configured project."""
    for part in reversed(cwd.parts):
        conf = projects.get(part) if isinstance(projects, dict) else None
        if conf:
            tags = [str(t).lower() for t in conf.get("tags", [part])]
            related = [e for e in entries if any(t in e.lower() for t in tags)][:3]
            return part, conf.get("entry"), related
    return "", None, []


def session_sections(entries: list, cwd: Path, projects: dict) -> list:
    name, entry_file, related = project_entries(entries, cwd, projects)
    sections = []
    if name:
        where = f" Read `{entry_file}` (vault) before working." if entry_file else ""
        sections.append((f"Current project: {name}", f"Matched from the working directory.{where}"))
    if related:
        sections.append((f"Recent sessions on {name}", "\n\n".join(clip_block(e, MAX_ENTRY) for e in related)))
        if entries and entries[0] not in related:
            sections.append(("Latest session (any topic)", clip_block(entries[0], MAX_ENTRY)))
    elif entries:
        sections.append(("Recent sessions", "\n\n".join(clip_block(e, MAX_ENTRY) for e in entries[:N_ENTRIES])))
    return sections


def fit(header: str, sections: list, limit: int = MAX_CONTEXT) -> str:
    """Join sections in priority order without ever exceeding `limit` characters."""
    out = header
    for index, (title, body) in enumerate(sections):
        block = f"\n\n## {title}\n{body}"
        omitted = len(sections) - index
        note = f"\n\n[context capped: {omitted} section(s) omitted]"
        if len(out) + len(block) + (len(note) if omitted > 1 else 0) > limit:
            room = limit - len(out) - len(note) - 10
            if room > 200:
                out += block[:room].rstrip() + " [...]"
                omitted -= 1
            return (out + (f"\n\n[context capped: {omitted} section(s) omitted]" if omitted else ""))[:limit]
        out += block
    return out[:limit]


def build_context(event: dict, now=None) -> str:
    system = cfg.system_dir()
    sections: list = []
    problems = health.fit(health.check(now), 600)
    if problems:
        sections.append(("Needs attention (Carlo Brain health)", problems + "\n\nTell the user in one line."))
    sections += dropins(cfg.boot_dir())
    note = compaction_note(event)
    if note:
        sections.append(note)
    if system:
        pending = facts_pending(system / "FACTS_TO_VALIDATE.md")
        if pending:
            sections.append((f"Memory: {pending} fact(s) to validate",
                             "`00_System/FACTS_TO_VALIDATE.md`: present them in one line (skill `validate_facts.md`)."))
        entries = sessionlog.entries(read(system / "SESSION_LOG.md"))
        cwd = Path(event.get("cwd") or os.getcwd())
        sections += session_sections(entries, cwd, cfg.get("memory.projects", {}))
    return fit("# Context (injected by the carlo-brain memory module)", sections)


def main() -> None:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except ValueError:
        event = {}
    if cfg.is_headless() or event.get("source") == "resume":
        return
    context = build_context(event if isinstance(event, dict) else {})
    if "first_boot" not in cfg.last_runs():
        cfg.mark_run("first_boot")
    cfg.mark_run("boot")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - a hook must never block the session
        cfg.log_error("memory.boot", exc)
        print(f"carlo boot: {exc}", file=sys.stderr)
