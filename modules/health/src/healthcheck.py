#!/usr/bin/env python3
"""Watchdog: did every scheduled job run on time, and does every connector still work? (beta)

Cheap, read-only checks. Key and token files are only tested for presence, size and permissions
(like `test -s`), their content is never read. Python 3.9+, standard library only.

Usage:
  healthcheck.py check [--json] [--fast]   print the status (exit 1 if something is broken)
  healthcheck.py boot                      SessionStart hook: fast check, write/remove state/boot.d/health.md, catch up
  healthcheck.py run                       scheduled job: full check (MCP servers too), same outputs
  healthcheck.py catchup [--dry-run]       relaunch stale jobs that have a command (like anacron)
  healthcheck.py repair [--dry-run]        run the repair playbook (repair.py): safe fixes once per failure per 24 h
  healthcheck.py status                    repair switch, recent repairs, what waits on you

Config (optional): ~/.carlo-brain/config.d/health.json, see the module README.
Never raises in `boot` and `run`: a broken watchdog must not block a session.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python3 -I` does not add the script folder
import repair  # noqa: E402

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"
BROKEN = (WARN, FAIL)
DEFAULT_RETRY_H = 6
TOKEN_MAX_AGE_DAYS = 335  # the long-lived login token lasts one year: warn a month before
KEY_ENV = re.compile(r"(API_KEY|_KEY$|SECRET|PASSWORD|PASSWD)", re.I)


@dataclass(frozen=True)
class Finding:
    """One line of status. `kind` is job or connector."""
    level: str
    name: str
    text: str
    kind: str = "job"


def brain_home() -> Path:
    return Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain")


def read_json(path: Path) -> dict:
    """A JSON object from a file; {} when missing or broken."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_settings(brain: Path) -> dict:
    return read_json(brain / "config.d" / "health.json")


def installed_modules(brain: Path) -> Dict[str, dict]:
    modules = read_json(brain / "config.json").get("modules")
    return modules if isinstance(modules, dict) else {}


def parse_time(value: object) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def human_age(hours: float) -> str:
    return f"{int(hours)} hours" if hours < 48 else f"{int(hours // 24)} days"


# ------------------------------------------------------------------ job definitions

def max_gap_hours(days: List[str], window_h: float) -> float:
    """Longest wait between two slots of a weekly schedule, plus the catch-up window."""
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    slots = sorted({names.index(d.lower()[:3]) for d in days if d.lower()[:3] in names})
    if not slots:
        return 24.0 + window_h
    gaps = [((slots[(i + 1) % len(slots)] - s) % 7 or 7) * 24 for i, s in enumerate(slots)]
    return max(gaps) + window_h


def self_improve_jobs(brain: Path) -> List[dict]:
    """One job per task of config.d/self-improve-tasks.json; proof is the task state file."""
    jobs = []
    for task in read_json(brain / "config.d" / "self-improve-tasks.json").get("tasks", []):
        if not isinstance(task, dict) or not task.get("name"):
            continue
        name = str(task["name"])
        jobs.append({"name": f"self-improve:{name}",
                     "proof": [str(brain / "state" / "self-improve" / "tasks" / f"{name}.json")],
                     "max_age_h": max_gap_hours(list(task.get("days") or []), float(task.get("window_h", 24))),
                     "command": str(task.get("command", "")) if task.get("catch_up") else ""})
    return jobs


def proactive_job(brain: Path) -> List[dict]:
    """The scan job, only when at least one source is switched on."""
    sources = read_json(brain / "config.d" / "proactive.json").get("sources", {})
    if not any(isinstance(s, dict) and s.get("enabled") for s in sources.values()):
        return []
    return [{"name": "proactive", "proof": [str(brain / "state" / "proactive" / "signals.json")], "max_age_h": 12,
             "command": f"python3 -I {brain}/proactive/run.py run"}]


def night_job(brain: Path) -> List[dict]:
    """The night trigger, only when a task is queued (an empty queue legitimately never runs)."""
    queue = brain / "data" / "night" / "queue"
    if not queue.is_dir() or not any(not p.name.startswith(".") for p in queue.iterdir()):
        return []
    return [{"name": "night", "proof": [str(brain / "state" / "night" / "launched_*"),
                                         str(brain / "state" / "night" / "REPORT.md")], "max_age_h": 48, "command": ""}]


def configured_jobs(settings: dict) -> List[dict]:
    jobs = []
    for job in settings.get("jobs", []):
        if isinstance(job, dict) and job.get("name") and job.get("proof"):
            proof = job["proof"] if isinstance(job["proof"], list) else [job["proof"]]
            jobs.append({"name": str(job["name"]), "proof": [os.path.expanduser(str(p)) for p in proof],
                         "max_age_h": float(job.get("max_age_h", 24)), "command": str(job.get("command", ""))})
    return jobs


def collect_jobs(brain: Path, settings: dict) -> List[dict]:
    have = installed_modules(brain)
    jobs: List[dict] = []
    if "self-improve" in have:
        jobs += self_improve_jobs(brain)
    if "proactive" in have:
        jobs += proactive_job(brain)
    if "night" in have:
        jobs += night_job(brain)
    jobs += configured_jobs(settings)
    ignored = {str(n) for n in settings.get("ignore", [])}
    return [j for j in jobs if j["name"] not in ignored]


def newest_proof(patterns: List[str]) -> Optional[datetime]:
    """Most recent modification time among the files matching the patterns."""
    times = []
    for pattern in patterns:
        for path in glob.glob(pattern):
            try:
                times.append(os.path.getmtime(path))
            except OSError:
                continue
    return datetime.fromtimestamp(max(times)).astimezone() if times else None


def check_jobs(brain: Path, settings: dict, now: datetime) -> List[Finding]:
    """One finding per job: ok, stale, or never ran since it was installed."""
    findings = []
    for job in collect_jobs(brain, settings):
        limit = float(job["max_age_h"])
        last = newest_proof(job["proof"])
        if last is None:
            since = parse_time((installed_modules(brain).get(job["name"].split(":")[0]) or {}).get("installed_at"))
            if since and now - since > timedelta(hours=limit):
                findings.append(Finding(FAIL, job["name"], f"{job['name']}: never ran, installed {human_age((now - since).total_seconds() / 3600)} ago, threshold {human_age(limit)}"))
            else:
                findings.append(Finding(SKIP, job["name"], f"{job['name']}: no run yet"))
            continue
        age = (now - last).total_seconds() / 3600
        if age > limit:
            findings.append(Finding(FAIL, job["name"], f"{job['name']}: last run {human_age(age)} ago, threshold {human_age(limit)}"))
        else:
            findings.append(Finding(OK, job["name"], f"{job['name']}: last run {human_age(age)} ago"))
    return findings


# ------------------------------------------------------------------ connectors

def file_state(path: Path, max_age_days: Optional[int] = None) -> str:
    """'' when the file is present, non empty, private and fresh; else a reason. Content is never read."""
    try:
        info = path.stat()
    except OSError:
        return "missing"
    if info.st_size == 0:
        return "empty"
    if info.st_mode & 0o077:
        return "readable by others (chmod 600)"
    if max_age_days and (datetime.now().timestamp() - info.st_mtime) > max_age_days * 86400:
        return f"older than {max_age_days} days, renew it"
    return ""


def sqlite_state(path: Path) -> str:
    """'' when the database opens read-only and answers a trivial query, else a reason."""
    if not path.exists():
        return "missing"
    if not os.access(path, os.R_OK):
        return "not readable (Full Disk Access?)"
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        try:
            conn.execute("select count(*) from sqlite_master").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return f"cannot be read ({exc.__class__.__name__})"
    return ""


def connector_line(name: str, problem: str, good: str, level: str = FAIL) -> Finding:
    return Finding(OK if not problem else level, name, f"{name}: {good if not problem else problem}", "connector")


def check_auth_token(brain: Path, have: Dict[str, dict]) -> List[Finding]:
    """Headless `claude -p` jobs need a long-lived login token; only relevant when such a job is installed."""
    if not ({"night", "self-improve"} & set(have)):
        return []
    problem = file_state(brain / "keys" / "claude_oauth_token", TOKEN_MAX_AGE_DAYS)
    return [connector_line("claude-auth", f"keys/claude_oauth_token {problem} (unattended jobs may lose their login)" if problem else "",
                           "login token file present", WARN)]


def check_databases(brain: Path, settings: dict, platform: str) -> List[Finding]:
    """WhatsApp and Apple databases, only when they exist or a source is enabled for them."""
    out = []
    sources = read_json(brain / "config.d" / "proactive.json").get("sources", {})
    wa = sources.get("whatsapp", {}) if isinstance(sources, dict) else {}
    candidates = [Path(os.path.expanduser(str(wa["db"])))] if wa.get("db") else []
    candidates += [Path.home() / "whatsapp-mcp" / "whatsapp-bridge" / "store" / "messages.db",
                   brain / "data" / "whatsapp-mcp" / "whatsapp-bridge" / "store" / "messages.db"]
    db = next((c for c in candidates if c.exists()), None)
    if db is not None or wa.get("enabled"):
        problem = sqlite_state(db or candidates[0])
        out.append(connector_line("whatsapp", f"database {problem}" if problem else "", "database readable"))
    if platform == "darwin":
        apple = {"apple-notes": Path.home() / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite",
                 "apple-messages": Path.home() / "Library/Messages/chat.db"}
        for name, path in apple.items():
            if path.exists():
                out.append(connector_line(name, sqlite_state(path), "database readable"))
    for item in settings.get("files", []):
        if isinstance(item, dict) and item.get("name") and item.get("path"):
            path = Path(os.path.expanduser(str(item["path"])))
            problem = sqlite_state(path) if item.get("sqlite") else ("" if path.exists() and os.access(path, os.R_OK) else "missing or unreadable")
            out.append(connector_line(str(item["name"]), problem, "readable"))
    return out


def check_telegram(brain: Path) -> List[Finding]:
    if not (brain / "config.d" / "telegram.json").exists():
        return []
    problem = file_state(brain / "keys" / "telegram_bot_token")
    return [connector_line("telegram", f"bot token file {problem}" if problem else "", "bot token file present")]


def check_mcp(expected: List[str], run: Callable = subprocess.run) -> List[Finding]:
    """Expected MCP servers appear in `claude mcp list` and are not reported as failed. Slow: full mode only."""
    if not expected:
        return []
    if shutil.which("claude") is None:
        return [Finding(WARN, "mcp", "mcp: claude CLI not found, cannot check servers", "connector")]
    try:
        res = run(["claude", "mcp", "list"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [Finding(WARN, "mcp", f"mcp: claude mcp list failed ({exc.__class__.__name__})", "connector")]
    lines = (res.stdout or "").splitlines()
    out = []
    for name in expected:
        line = next((ln for ln in lines if ln.strip().lower().startswith(str(name).lower() + ":")), "")
        bad = not line or re.search(r"fail|error|needs auth|✗", line, re.I)
        out.append(connector_line(f"mcp:{name}", "not configured" if not line else ("reported as not connected" if bad else ""),
                                  "configured and connected"))
    return out


def check_connectors(brain: Path, settings: dict, platform: str, full: bool,
                     run: Callable = subprocess.run) -> List[Finding]:
    have = installed_modules(brain)
    out = check_auth_token(brain, have) + check_databases(brain, settings, platform) + check_telegram(brain)
    if full:
        out += check_mcp([str(n) for n in settings.get("expect_mcp", [])], run)
    return out


def run_checks(brain: Optional[Path] = None, now: Optional[datetime] = None, full: bool = True,
               platform: str = sys.platform, run: Callable = subprocess.run) -> List[Finding]:
    brain = brain or brain_home()
    settings = load_settings(brain)
    return check_jobs(brain, settings, now or datetime.now().astimezone()) + check_connectors(brain, settings, platform, full, run)


# ------------------------------------------------------------------ outputs

def render_note(findings: List[Finding], limit: int = 900, actions: Sequence[str] = ()) -> str:
    """Markdown for state/boot.d/health.md; empty when nothing is broken.

    `actions` are the one-line commands or settings paths only the user can run; they are never cut by the cap.
    """
    broken = [f for f in findings if f.level in BROKEN]
    if not broken:
        return ""
    lines = ["<!-- carlo-brain:health -->", "## Health", "Something scheduled or connected is broken. Say it in one line, then offer to fix it:"]
    for finding in broken:
        lines.append(f"- {finding.text}")
    lines.append("Details: `carlo doctor`.")
    text = "\n".join(lines)
    text = text if len(text) <= limit else text[: limit - 20].rstrip() + "\n(truncated)"
    if actions:
        text += "\nOnly the user can do these (hand over one, as a single action; do not run them yourself):\n" + "\n".join(f"- `{a}`" for a in actions)
    return text


def write_note(brain: Path, findings: List[Finding], actions: Sequence[str] = ()) -> None:
    """Write boot.d/health.md when broken, remove it when healthy again."""
    path = brain / "state" / "boot.d" / "health.md"
    text = render_note(findings, actions=actions)
    if text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    elif path.exists() and "carlo-brain:health" in path.read_text(encoding="utf-8", errors="replace"):
        path.unlink()


# ------------------------------------------------------------------ catch-up

def clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k == "CLAUDE_CODE_OAUTH_TOKEN" or not KEY_ENV.search(k)}
    env["CARLO_HEADLESS"] = "1"
    return env


def catch_up(brain: Path, findings: List[Finding], now: datetime, launch: Optional[Callable] = None,
             dry_run: bool = False) -> List[str]:
    """Relaunch stale jobs that declare a command, at most once per retry window. Returns what was started."""
    settings = load_settings(brain)
    retry_h = float(settings.get("catchup_retry_h", DEFAULT_RETRY_H))
    stale = {f.name for f in findings if f.kind == "job" and f.level == FAIL}
    started = []
    for job in collect_jobs(brain, settings):
        if job["name"] not in stale or not job["command"]:
            continue
        marker = brain / "state" / "health" / (re.sub(r"[^A-Za-z0-9_.-]", "_", job["name"]) + ".json")
        last = parse_time(read_json(marker).get("attempted_at"))
        if last and now - last < timedelta(hours=retry_h):
            continue
        started.append(job["name"])
        if dry_run:
            continue
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"attempted_at": now.isoformat(timespec="seconds")}), encoding="utf-8")  # before launch: never twice
        (launch or default_launch)(job["command"], brain)
    return started


def default_launch(command: str, brain: Path) -> None:
    env = {**clean_env(), "CARLO_BRAIN_HOME": str(brain)}
    subprocess.Popen(["/bin/sh", "-c", command], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


# ------------------------------------------------------------------ commands

def to_json(findings: List[Finding]) -> str:
    return json.dumps([{"level": f.level, "name": f.name, "text": f.text, "kind": f.kind} for f in findings], ensure_ascii=False)


def cmd_check(argv: List[str]) -> int:
    findings = run_checks(full="--fast" not in argv)
    if "--json" in argv:
        print(to_json(findings))
    else:
        for f in findings:
            print(f"[{f.level}] {f.text}")
    return 1 if any(f.level == FAIL for f in findings) else 0


def repair_pass(brain: Path, findings: List[Finding], now: datetime, full: bool, dry_run: bool = False,
                run: Callable = subprocess.run, platform: str = sys.platform):
    """Run the playbook; when something was fixed, check again so the note shows the real state.

    Returns (findings, actions waiting on the user, outcomes).
    """
    outcomes = repair.run_repair(brain, findings, now, dry_run=dry_run, full=full, env=clean_env(), run=run, platform=platform)
    if any(o.status == repair.FIXED for o in outcomes):
        findings = run_checks(brain, now, full=full, platform=platform, run=run)
    return findings, repair.actions_for_note(outcomes)


def cmd_repair(argv: List[str]) -> int:
    """Explicit run: full check, playbook, same note as the hook. --dry-run changes nothing."""
    brain, now, dry = brain_home(), datetime.now().astimezone(), "--dry-run" in argv
    findings = run_checks(brain, now, full=True)
    outcomes = repair.run_repair(brain, findings, now, dry_run=dry, full=True, env=clean_env())
    if not repair.repair_config(load_settings(brain))["enabled"]:
        print('repair is switched off (config.d/health.json: "repair": {"enabled": false}), nothing will be changed')
    for o in outcomes:
        print(f"[{o.status}] {o.text}" + (f" ({o.detail})" if o.status in (repair.FIXED, repair.FAILED, repair.THROTTLED) else ""))
        if o.status in repair.NEEDS_YOU:
            print(f"    you: {o.manual}")
    if not outcomes:
        print("nothing to repair")
    if not dry:
        if any(o.status == repair.FIXED for o in outcomes):
            findings = run_checks(brain, now, full=True)
        write_note(brain, findings, repair.actions_for_note(outcomes))
    return 1 if any(o.status == repair.FAILED for o in outcomes) else 0


def cmd_status() -> int:
    """Repair switch, last repairs, what waits on you (detection only, nothing is changed)."""
    brain, now = brain_home(), datetime.now().astimezone()
    conf = repair.repair_config(load_settings(brain))
    print(f"repair: {'on' if conf['enabled'] else 'off'} (once per failure per {repair.COOLDOWN_H} hours)")
    print("recent repairs:" if repair.recent_log(brain) else "recent repairs: none")
    for line in repair.recent_log(brain):
        print(f"  {line}")
    findings = run_checks(brain, now, full=False)
    waiting = [o for o in repair.run_repair(brain, findings, now, dry_run=True, full=False, env=clean_env())]
    todo = [o for o in waiting if o.status in repair.NEEDS_YOU or o.status == repair.WOULD_FIX]
    print("waiting:" if todo else "waiting: nothing")
    for o in todo:
        print(f"  [{o.status}] {o.text}" + (f"\n      you: {o.manual}" if o.status in repair.NEEDS_YOU else ""))
    return 0


def cmd_watch(full: bool) -> int:
    """boot and run: check, write the note, catch up. Never raises."""
    try:
        if os.environ.get("CARLO_HEADLESS"):
            return 0
        brain, now = brain_home(), datetime.now().astimezone()
        findings = run_checks(brain, now, full=full)
        try:
            findings, actions = repair_pass(brain, findings, now, full=full)
        except Exception as exc:  # a broken playbook must not hide the findings
            print(f"watchdog repair: {exc}", file=sys.stderr)
            actions = []
        write_note(brain, findings, actions)
        if load_settings(brain).get("catchup", True):
            catch_up(brain, findings, now)
    except Exception as exc:  # a watchdog must never break a session
        print(f"watchdog: {exc}", file=sys.stderr)
    return 0


def main(argv: List[str]) -> int:
    command = argv[0] if argv else "check"
    if command == "check":
        return cmd_check(argv[1:])
    if command == "boot":
        return cmd_watch(full=False)
    if command == "run":
        return cmd_watch(full=True)
    if command == "repair":
        return cmd_repair(argv[1:])
    if command == "status":
        return cmd_status()
    if command == "catchup":
        brain, now = brain_home(), datetime.now().astimezone()
        for name in catch_up(brain, run_checks(brain, now, full=False), now, dry_run="--dry-run" in argv):
            print(f"catch-up: {name}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
