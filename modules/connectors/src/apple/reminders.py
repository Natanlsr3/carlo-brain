"""Apple Reminders, read-only, through AppleScript (macOS only).

Usage:
  reminders.py list [--list NAME]            open reminders as JSON lines
  reminders.py count [--list NAME]           number of open reminders
  reminders.py export --out FILE [--list NAME]
        writes the todo JSON the proactive module reads: [{"title","due","done","note"}]

Use case: dictate tasks to Siri ("remind me to ..."), let the briefing surface what is due.
This script never completes, edits or deletes a reminder. AppleScript starts the Reminders app;
if it was not running it is quit again afterwards. First run asks for Automation permission.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Callable, Dict, List, Optional

SEP = "\x1f"

SCRIPT = '''
set out to ""
tell application "Reminders"
  set theLists to {SCOPE}
  repeat with l in theLists
    repeat with r in (reminders of l whose completed is false)
      set d to ""
      try
        set d to (due date of r) as «class isot» as string
      end try
      set n to ""
      try
        set n to body of r
        if n is missing value then set n to ""
      end try
      set out to out & (name of r) & "{SEP}" & n & "{SEP}" & d & "{SEP}" & (name of l) & linefeed
    end repeat
  end repeat
end tell
return out
'''

Runner = Callable[[str], str]


def applescript(script: str) -> str:
    """Run AppleScript and return stdout. Raises RuntimeError with the AppleScript message."""
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "osascript failed")
    return res.stdout


def _quote(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_script(list_name: Optional[str]) -> str:
    """AppleScript listing open reminders of one list, or of all lists."""
    scope = f"{{list {_quote(list_name)}}}" if list_name else "every list"
    return SCRIPT.replace("{SCOPE}", scope).replace("{SEP}", SEP)


def parse(output: str) -> List[Dict[str, object]]:
    """Parse the AppleScript output into reminder dicts."""
    items = []
    for line in output.splitlines():
        parts = line.split(SEP)
        if len(parts) < 4 or not parts[0].strip():
            continue
        title, note, due, list_name = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
        items.append({"title": title, "note": note, "due": due[:19], "done": False, "list": list_name})
    return items


def fetch(list_name: Optional[str] = None, run: Runner = applescript) -> List[Dict[str, object]]:
    """Open reminders. Quits Reminders afterwards if this call started it."""
    was_open = run('application "Reminders" is running').strip() == "true"
    try:
        return parse(run(build_script(list_name)))
    finally:
        if not was_open:
            try:
                run('tell application "Reminders" to quit')
            except RuntimeError:
                pass


def to_todo_export(items: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """Shape read by the proactive module's todo source."""
    return [{"title": i["title"], "due": i["due"], "done": False, "note": i["note"]} for i in items]


def main(argv: Optional[List[str]] = None, run: Runner = applescript) -> int:
    parser = argparse.ArgumentParser(description="Apple Reminders (read-only)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("list", "count", "export"):
        p = sub.add_parser(name)
        p.add_argument("--list", dest="list_name")
        if name == "export":
            p.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        items = fetch(args.list_name, run)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
    if args.cmd == "count":
        print(len(items))
    elif args.cmd == "list":
        for item in items:
            print(json.dumps(item, ensure_ascii=False))
    else:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(to_todo_export(items), handle, ensure_ascii=False, indent=1)
        print(f"{len(items)} reminder(s) written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
