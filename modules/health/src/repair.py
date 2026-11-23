"""Self-repair playbook for the watchdog (beta): known failures mapped to fixes.

Safe fixes run on their own, at most once per failure per 24 hours, and each attempt is logged to
state/health/repair.log:
  - a launchd job of Carlo Brain that is not loaded: `launchctl bootstrap`
  - an expected MCP server that disappeared: re-register it with the command stored in config
  - the WhatsApp bridge, when configured and not running: start it again
  - a log file over `max_log_mb`: copy to `<name>.1`, then truncate in place
  - a missing state folder: create it

Unsafe or impossible fixes never run: an expired login, a lost Full Disk Access permission, a missing key
file. For these (and for any fix that failed, was tried less than 24 hours ago, or is switched off) the exact
one-line command goes to the next session through state/boot.d/health.md.

Config (config.d/health.json): "repair": {"enabled": true, "max_log_mb": 10, "mcp_commands": {"name": "claude mcp add ..."},
"logs": ["~/some.log"], "whatsapp_bridge": {"command": "/path/to/bridge", "cwd": "/path"}}, or "repair": false.
Python 3.9+, standard library only. Key and token files are never opened.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

COOLDOWN_H = 24
DEFAULT_MAX_LOG_MB = 10
LAUNCHD_PREFIX = "com.carlo-brain."
FDA_COMMAND = 'open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"'
FIXED, FAILED, THROTTLED, MANUAL, WOULD_FIX, OFF = "fixed", "failed", "throttled", "manual", "would-fix", "off"
NEEDS_YOU = (FAILED, THROTTLED, MANUAL, OFF)


class RepairError(Exception):
    """A fix ran and did not work (the message goes to the log)."""


@dataclass(frozen=True)
class Ctx:
    """Everything a play needs; the callables are injected so tests never touch a real system."""
    brain: Path
    home: Path
    settings: dict
    run: Callable
    popen: Callable
    env: dict
    platform: str
    full: bool
    uid: int


@dataclass(frozen=True)
class Issue:
    """One known failure. `fix` is None for what only the user can do; `manual` is the one-line command for them."""
    play: str
    key: str
    text: str
    manual: str
    fix: Optional[Callable[[], str]] = None


@dataclass(frozen=True)
class Outcome:
    key: str
    text: str
    status: str
    detail: str
    manual: str


def repair_config(settings: dict) -> dict:
    """The `repair` section with defaults; `"repair": false` switches everything automatic off."""
    raw = settings.get("repair", True)
    if raw is False:
        return {"enabled": False}
    return {"enabled": True, **raw} if isinstance(raw, dict) else {"enabled": True}


def _tail(res: subprocess.CompletedProcess) -> str:
    return ((res.stderr or res.stdout or "").strip().splitlines() or ["no output"])[0][:200]


# ------------------------------------------------------------------ safe plays

def _real_home(home: Path) -> bool:
    try:
        import pwd
        return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve() == Path(home).resolve()
    except (ImportError, KeyError, OSError):
        return True


def launchd_issues(ctx: Ctx) -> List[Issue]:
    """Carlo Brain launchd jobs whose plist exists but which launchd does not know (macOS)."""
    agents = ctx.home / "Library" / "LaunchAgents"
    if ctx.platform != "darwin" or not agents.is_dir():
        return []
    if ctx.run is subprocess.run and (os.environ.get("CARLO_NO_LAUNCHD") or not _real_home(ctx.home)):
        return []  # a throwaway HOME (tests, trials) must never load jobs into the user's real launchd session
    ignored = {str(n) for n in ctx.settings.get("ignore", [])}
    domain, issues = f"gui/{ctx.uid}", []
    for plist in sorted(agents.glob(f"{LAUNCHD_PREFIX}*.plist")):
        label = plist.stem
        if label in ignored or label[len(LAUNCHD_PREFIX):] in ignored:
            continue
        try:
            loaded = ctx.run(["launchctl", "print", f"{domain}/{label}"], capture_output=True, text=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return []
        if not loaded:
            issues.append(Issue("launchd", f"launchd:{label}", f"scheduled job {label} is not loaded",
                                f"launchctl bootstrap {domain} {shlex.quote(str(plist))}", _bootstrap(ctx, domain, plist)))
    return issues


def _bootstrap(ctx: Ctx, domain: str, plist: Path) -> Callable[[], str]:
    def fix() -> str:
        res = ctx.run(["launchctl", "bootstrap", domain, str(plist)], capture_output=True, text=True, timeout=20)
        if res.returncode != 0:
            raise RepairError(_tail(res))
        return f"bootstrapped {plist.name}"
    return fix


def mcp_issues(ctx: Ctx) -> List[Issue]:
    """Expected MCP servers absent from `claude mcp list`. Slow, so only in the full check."""
    expected = [str(n) for n in ctx.settings.get("expect_mcp", [])]
    if not ctx.full or not expected:
        return []
    try:
        res = ctx.run(["claude", "mcp", "list"], capture_output=True, text=True, timeout=60, env=ctx.env)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if res.returncode != 0:
        return []
    listed = {ln.split(":", 1)[0].strip().lower() for ln in (res.stdout or "").splitlines() if ":" in ln}
    commands = repair_config(ctx.settings).get("mcp_commands") or {}
    issues = []
    for name in expected:
        if name.lower() in listed:
            continue
        argv = _mcp_argv(commands.get(name))
        manual = " ".join(shlex.quote(a) for a in argv) if argv else f"claude mcp add {shlex.quote(name)} -s user -- <command>  (store it in health.json repair.mcp_commands to automate)"
        issues.append(Issue("mcp", f"mcp:{name}", f"MCP server {name} is not registered", manual,
                            _register(ctx, argv) if argv else None))
    return issues


def _mcp_argv(command: object) -> List[str]:
    """argv of a stored `claude mcp add ...` command; anything else is refused (this is config, not trusted input)."""
    try:
        argv = shlex.split(command) if isinstance(command, str) else [str(a) for a in command or []]
    except ValueError:
        return []
    return argv if argv[:3] == ["claude", "mcp", "add"] and len(argv) > 3 else []


def _register(ctx: Ctx, argv: List[str]) -> Callable[[], str]:
    def fix() -> str:
        res = ctx.run(argv, capture_output=True, text=True, timeout=60, env=ctx.env)
        if res.returncode != 0:
            raise RepairError(_tail(res))
        return f"registered {argv[3]}"
    return fix


def bridge_issues(ctx: Ctx) -> List[Issue]:
    """The WhatsApp bridge, only when configured (settings, or an enabled proactive source with the installed binary)."""
    conf = repair_config(ctx.settings).get("whatsapp_bridge")
    default = ctx.brain / "data" / "whatsapp-mcp" / "whatsapp-bridge" / "whatsapp-bridge"
    sources = _read_json(ctx.brain / "config.d" / "proactive.json").get("sources", {})
    wa_on = isinstance(sources, dict) and isinstance(sources.get("whatsapp"), dict) and sources["whatsapp"].get("enabled")
    if isinstance(conf, dict) and conf.get("command"):
        argv = shlex.split(str(conf["command"]))
    elif default.exists() and (wa_on or conf):
        argv = [str(default)]
    else:
        return []
    if (ctx.home / "Library" / "LaunchAgents" / f"{LAUNCHD_PREFIX}whatsapp-bridge.plist").exists():
        return []  # a launchd service restarts it; the launchd play covers an unloaded one
    cwd = os.path.expanduser(str(conf["cwd"])) if isinstance(conf, dict) and conf.get("cwd") else str(Path(argv[0]).parent)
    try:
        alive = ctx.run(["pgrep", "-f", argv[0]], capture_output=True, text=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return []
    if alive:
        return []
    return [Issue("bridge", "whatsapp-bridge", "the WhatsApp bridge is not running", f"cd {shlex.quote(cwd)} && {shlex.join(argv)}", _start_bridge(ctx, argv, cwd))]


def _start_bridge(ctx: Ctx, argv: List[str], cwd: str) -> Callable[[], str]:
    def fix() -> str:
        log = ctx.brain / "state" / "logs" / "whatsapp-bridge.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("ab") as handle:
            ctx.popen(argv, cwd=cwd, env=ctx.env, stdin=subprocess.DEVNULL, stdout=handle, stderr=handle, start_new_session=True)
        return f"started {Path(argv[0]).name}"
    return fix


def log_issues(ctx: Ctx) -> List[Issue]:
    """Logs under state/ (and the ones listed in config) bigger than `max_log_mb`."""
    conf = repair_config(ctx.settings)
    limit = float(conf.get("max_log_mb", DEFAULT_MAX_LOG_MB)) * 1024 * 1024
    paths = list((ctx.brain / "state").rglob("*.log")) + [Path(os.path.expanduser(str(p))) for p in conf.get("logs", [])]
    issues = []
    for path in sorted(set(paths)):
        try:
            big = path.is_file() and not path.is_symlink() and path.stat().st_size > limit
        except OSError:
            continue
        if big:
            quoted = shlex.quote(str(path))
            issues.append(Issue("log", f"log:{path}", f"log {path.name} is over {conf.get('max_log_mb', DEFAULT_MAX_LOG_MB)} MB",
                                f"cp {quoted} {quoted}.1 && : > {quoted}", _rotate(path)))
    return issues


def _rotate(path: Path) -> Callable[[], str]:
    def fix() -> str:
        """Copy then truncate in place, so a process that keeps the file open keeps writing to it."""
        rotated = path.with_name(path.name + ".1")
        shutil.copyfile(path, rotated)
        with path.open("r+b") as handle:
            handle.truncate(0)
        return f"rotated to {rotated.name}"
    return fix


def dir_issues(ctx: Ctx) -> List[Issue]:
    """State folders other parts of Carlo Brain expect to exist."""
    wanted = [ctx.brain / "config.d", ctx.brain / "state", ctx.brain / "state" / "boot.d", ctx.brain / "state" / "health", ctx.brain / "state" / "logs"]
    modules = _read_json(ctx.brain / "config.json").get("modules")
    for name in ("proactive", "night", "self-improve"):
        if isinstance(modules, dict) and name in modules:
            wanted.append(ctx.brain / "state" / name)
    return [Issue("dir", f"dir:{d}", f"state folder {d} is missing", f"mkdir -p {shlex.quote(str(d))}", _mkdir(d))
            for d in wanted if not d.is_dir()]


def _mkdir(path: Path) -> Callable[[], str]:
    def fix() -> str:
        path.mkdir(parents=True, exist_ok=True)
        return f"created {path}"
    return fix


# ------------------------------------------------------------------ plays that only you can do

def manual_issues(ctx: Ctx, findings: Sequence) -> List[Issue]:
    """Broken findings whose fix needs you: login, Full Disk Access, key files. Nothing here runs."""
    keys = ctx.brain / "keys"
    out = []
    for f in findings:
        if f.level not in ("warn", "fail"):
            continue
        if "Full Disk Access" in f.text and f.name in ("apple-notes", "apple-messages", "whatsapp"):
            out.append(Issue("fda", f"fda:{f.name}", f.text, FDA_COMMAND + "   # then enable your terminal app, restart it"))
        elif f.name == "claude-auth":
            fix = f"chmod 600 {shlex.quote(str(keys / 'claude_oauth_token'))}" if "chmod 600" in f.text else \
                  f"claude setup-token   # then save the token in {keys / 'claude_oauth_token'} (chmod 600)"
            out.append(Issue("login", "login:claude", f.text, fix))
        elif f.name == "telegram":
            path = keys / "telegram_bot_token"
            fix = f"chmod 600 {shlex.quote(str(path))}" if "chmod 600" in f.text else f"save the bot token from BotFather in {path} (chmod 600)"
            out.append(Issue("key", "key:telegram", f.text, fix))
    return out


PLAYBOOK = (launchd_issues, mcp_issues, bridge_issues, log_issues, dir_issues)


# ------------------------------------------------------------------ run

def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def state_file(brain: Path) -> Path:
    return brain / "state" / "health" / "repair.json"


def log_file(brain: Path) -> Path:
    return brain / "state" / "health" / "repair.log"


def _last_attempt(state: dict, key: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(state.get(key)))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _write_state(brain: Path, state: dict) -> None:
    path = state_file(brain)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")


def _log(brain: Path, now: datetime, key: str, status: str, detail: str) -> None:
    path = log_file(brain)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{now.isoformat(timespec='seconds')} {status} {key}: {detail}\n")


def _attempt(issue: Issue, brain: Path, now: datetime) -> Outcome:
    try:
        detail = issue.fix()  # type: ignore[misc]
        status = FIXED
    except RepairError as exc:
        status, detail = FAILED, str(exc)
    except (OSError, subprocess.SubprocessError) as exc:
        status, detail = FAILED, f"{exc.__class__.__name__}: {exc}"[:200]
    _log(brain, now, issue.key, status, detail)
    return Outcome(issue.key, issue.text, status, detail, issue.manual)


def run_repair(brain: Path, findings: Sequence, now: datetime, *, settings: Optional[dict] = None, dry_run: bool = False,
               full: bool = False, run: Callable = subprocess.run, popen: Callable = subprocess.Popen,
               env: Optional[dict] = None, platform: str = sys.platform, home: Optional[Path] = None) -> List[Outcome]:
    """Detect known failures and fix the safe ones. Returns one Outcome per issue; never raises on a play."""
    settings = settings if settings is not None else _read_json(brain / "config.d" / "health.json")
    ctx = Ctx(brain, home or Path.home(), settings, run, popen, env if env is not None else dict(os.environ), platform, full, os.getuid())
    enabled = bool(repair_config(settings)["enabled"])
    issues: List[Issue] = []
    for play in PLAYBOOK:
        try:
            issues += play(ctx)
        except Exception as exc:  # noqa: BLE001 - one broken play must not stop the others
            _log(brain, now, play.__name__, FAILED, f"detection error {exc.__class__.__name__}")
    issues += manual_issues(ctx, findings)
    state, outcomes = _read_json(state_file(brain)), []
    for issue in issues:
        last = _last_attempt(state, issue.key)
        if issue.fix is None:
            outcomes.append(Outcome(issue.key, issue.text, MANUAL, "needs you", issue.manual))
        elif not enabled:
            outcomes.append(Outcome(issue.key, issue.text, OFF, "repair is switched off", issue.manual))
        elif last and now - last < timedelta(hours=COOLDOWN_H):
            outcomes.append(Outcome(issue.key, issue.text, THROTTLED, f"tried {last.isoformat(timespec='minutes')}, next try after {COOLDOWN_H} hours", issue.manual))
        elif dry_run:
            outcomes.append(Outcome(issue.key, issue.text, WOULD_FIX, "dry run", issue.manual))
        else:
            state = {k: v for k, v in state.items() if (_last_attempt(state, k) or now) > now - timedelta(days=7)}
            state[issue.key] = now.isoformat(timespec="seconds")
            _write_state(brain, state)  # marked before the fix: never twice in a day, even if it crashes
            outcomes.append(_attempt(issue, brain, now))
    return outcomes


def actions_for_note(outcomes: Sequence[Outcome]) -> List[str]:
    """One line per thing waiting on you: what, then the exact command or settings path."""
    seen, lines = set(), []
    for o in outcomes:
        if o.status in NEEDS_YOU and o.manual not in seen:
            seen.add(o.manual)
            lines.append(f"{o.manual}")
    return lines


def recent_log(brain: Path, count: int = 8) -> List[str]:
    try:
        return log_file(brain).read_text(encoding="utf-8").splitlines()[-count:]
    except OSError:
        return []
