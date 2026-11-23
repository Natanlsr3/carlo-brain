"""The morning report: what ran, what did not, where to resume. Shown once at the next session start."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List

from .config import Settings

LABEL = {"finished": "done", "partial": "TO FINISH", "blocked": "NOT STARTED", "not_started": "NOT STARTED"}


def lines_for(results: Iterable) -> List[str]:
    """One line per task."""
    out = []
    for r in results:
        steps = f" ({r.steps_done}/{r.steps_total} steps)" if r.steps_total else ""
        out.append(f"- **{r.name}**: {LABEL.get(r.state, r.state)}{steps}. {r.reason}")
    return out


def write(cfg: Settings, results: Iterable, now: datetime, extra: Iterable[str] = ()) -> None:
    """Write REPORT.md and raise the unread flag read by the boot hook."""
    results = list(results)
    cfg.state.mkdir(parents=True, exist_ok=True)
    body = lines_for(results) + list(extra)
    text = f"# Night report, {now:%Y-%m-%d}\n\n" + ("\n".join(body) if body else "Nothing was queued.") + "\n"
    (cfg.state / "REPORT.md").write_text(text, encoding="utf-8")
    (cfg.state / "report_unread").write_text(now.isoformat(timespec="seconds"), encoding="utf-8")


def boot_note(cfg: Settings) -> None:
    """SessionStart: put an unread report in the boot drop-in once (flag consumed)."""
    note = cfg.brain / "state" / "boot.d" / "night.md"
    flag = cfg.state / "report_unread"
    if not flag.exists():
        return  # nothing new; an unshown note must not be deleted here (the injector removes it after showing it)
    try:
        text = (cfg.state / "REPORT.md").read_text(encoding="utf-8")
    except OSError:
        flag.unlink(missing_ok=True)
        return
    note.parent.mkdir(parents=True, exist_ok=True)
    # First line `<!-- once -->`: the core boot injector deletes the file after showing it, so it never repeats.
    note.write_text("<!-- once -->\n" + text[:1400], encoding="utf-8")
    flag.unlink(missing_ok=True)
