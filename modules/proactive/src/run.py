#!/usr/bin/env python3
"""Entry point of the proactive module. Run with python3 -I (this file adds its own folder to the path).

  run.py init      write a starter ~/.carlo-brain/config.d/proactive.json (never overwrites)
  run.py doctor    show which sources are enabled and readable
  run.py scan      read the enabled sources, write signals.json and digest.md
  run.py brief     turn signals.json into briefing.md and the boot file
  run.py run       scan + brief (+ voice if due)
  run.py boot      SessionStart hook: refresh in the background if stale, speak if due. Never blocks.
  run.py say       speak the current briefing now
  run.py mail-recent [hours]   print recent Apple Mail subjects (read-only), handy to test access
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from proactive import briefing, config, scan, voice  # noqa: E402
from proactive.paths import config_path, state_dir  # noqa: E402

HERE = Path(__file__).resolve().parent


def load_cfg() -> dict:
    """Config from the usual place; CARLO_PROACTIVE_CONFIG overrides the path."""
    override = os.environ.get("CARLO_PROACTIVE_CONFIG")
    return config.load(Path(override) if override else config_path())


def cmd_init() -> int:
    """Copy config.example.json next to the code if there is no config yet."""
    target = config_path()
    if target.exists():
        print(f"config already exists: {target}")
        return 0
    example = HERE / "config.example.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"wrote {target}; edit identity and enable the sources you want")
    return 0


def cmd_doctor(cfg: dict) -> int:
    """List sources, enabled state, and a one-line readability check for each enabled one."""
    now = datetime.now()
    for name, _fn in scan.SOURCES:
        enabled = cfg["sources"][name]["enabled"]
        print(f"{name:<10} {'enabled' if enabled else 'disabled'}")
    if any(cfg["sources"][n]["enabled"] for n in cfg["sources"]):
        result = scan.scan(cfg, now)
        print(f"\nscan: {len(result.signals)} signal(s), {len(result.outages)} outage(s)")
        for line in result.outages:
            print(f"  - {line}")
    voices = "on" if cfg["voice"]["enabled"] else "off"
    print(f"voice      {voices}")
    return 0


def cmd_scan(cfg: dict) -> int:
    """Scan and write outputs."""
    now = datetime.now()
    result = scan.scan(cfg, now)
    scan.write_outputs(result, now)
    print(f"{len(result.signals)} signal(s), {len(result.outages)} outage(s)")
    return 0


def cmd_brief(cfg: dict) -> int:
    """Generate and print the briefing."""
    print(briefing.generate(cfg, datetime.now()), end="")
    return 0


def cmd_run(cfg: dict) -> int:
    """Scan, brief, then voice if due (voice runs in the background)."""
    cmd_scan(cfg)
    cmd_brief(cfg)
    voice.play_if_due(datetime.now(), cfg)
    return 0


def is_stale(cfg: dict) -> bool:
    """True if signals.json is older than refresh_minutes (or missing)."""
    path = state_dir() / "signals.json"
    try:
        return time.time() - path.stat().st_mtime > cfg["refresh_minutes"] * 60
    except OSError:
        return True


def cmd_boot(cfg: dict) -> int:
    """Hook: cheap and never blocking. A stale scan is refreshed in a detached process."""
    if not any(cfg["sources"][n]["enabled"] for n in cfg["sources"]):
        return 0
    if is_stale(cfg):
        subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), "run"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    else:
        voice.play_if_due(datetime.now(), cfg)
    return 0


def cmd_mail_recent(hours: int) -> int:
    """Print recent mail subjects: a quick check that Full Disk Access works."""
    from datetime import timedelta

    from proactive.sources import mail_apple

    index = mail_apple.find_index()
    rows = mail_apple.recent(index, datetime.now() - timedelta(hours=hours))
    for _rowid, date, sender, subject, files, read in rows[-30:]:
        print(f"{date} {'  ' if read else '* '}{sender} | {subject[:70]}" + (f" [{len(files)} file(s)]" if files else ""))
    print(f"{len(rows)} message(s), * = unread")
    return 0


def main(argv: list) -> int:
    """Dispatch. Hook commands never raise: a broken config must not break a session."""
    command = argv[0] if argv else "run"
    try:
        if command == "init":
            return cmd_init()
        if command == "mail-recent":
            return cmd_mail_recent(int(argv[1]) if len(argv) > 1 else 24)
        cfg = load_cfg()
        if command == "say":
            return 0 if voice.speak(cfg) else 1
        handlers = {"doctor": cmd_doctor, "scan": cmd_scan, "brief": cmd_brief, "run": cmd_run, "boot": cmd_boot}
        if command not in handlers:
            print(__doc__)
            return 2
        return handlers[command](cfg)
    except Exception as err:  # noqa: BLE001
        print(f"proactive {command}: {err}", file=sys.stderr)
        return 0 if command == "boot" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
