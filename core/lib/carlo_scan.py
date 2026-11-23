"""`carlo scan`: a read-only, local map of your computer (projects, recent files, note apps, sources, tools).

Reads only names, dates and the first lines of README and Markdown files. Never reads mail or message
content (sources are probed for presence only). Honors the same deny list as the search module (keys, .env,
.ssh, Library, secrets, shell profiles), skips node_modules, .git internals and virtual envs, and is capped in
time, depth and entries. Writes JSON and a short Markdown summary under ~/.carlo-brain/state/scan/ and
sends nothing anywhere. Python 3.9+, standard library only.

Usage (through the CLI): carlo scan [--quick | --full] [--background] [--status] [--yes] [--root PATH]
"""
from __future__ import annotations

import fnmatch
import heapq
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python3 -I` does not add the script folder
import carlo_config as cfg  # noqa: E402
import carlo_scan_sources as sources  # noqa: E402

# Same lists as modules/search/src/search.py (a test checks this one is a superset).
DENY_DIRS = {".ssh", ".gnupg", ".aws", ".kube", ".git", "library", "keys", "secrets", "node_modules", ".venv", "venv",
             "__pycache__", ".trash", ".cache", "caches", "site-packages"}
DENY_FILES = [".env", ".env.*", "*.env", "*.pem", "*.key", "*.p12", "*.pfx", "*.keychain*", "*.kdbx", "id_rsa*", "id_ed25519*",
              "*token*", "*secret*", "*password*", "*passwd*", "*credential*", ".netrc", ".npmrc", ".pgpass", "*.gpg",
              ".zshrc", ".zprofile", ".zshenv", ".bashrc", ".bash_profile", ".profile", ".bash_history", ".zsh_history"]
# Noise, not secrets: build output and bundles nobody wants in a map.
SKIP_DIRS = {"build", "dist", ".next", "target", "pods", "deriveddata", ".gradle", "env", ".tox", ".mypy_cache",
             ".pytest_cache", ".idea", ".vscode", "applications"}
SKIP_SUFFIXES = (".app", ".photoslibrary", ".lrlibrary", ".xcodeproj", ".xcworkspace", ".framework", ".bundle")
SECRET_LINE = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY|(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*\S{6,}"
                         r"|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9-]{10,})", re.I)
DEFAULT_ROOTS = ["~/Desktop", "~/Documents", "~/Projects", "~/Projets", "~/Developer", "~/code", "~/dev", "~/src", "~/work", "~/repos"]
README_NAMES = ("README.md", "README", "README.txt", "readme.md", "Readme.md")
NOTION_EXPORT = re.compile(r"^Export-[0-9a-f-]{8,}", re.I)
RECENT_DAYS = 30
FOLDER_MIN_FILES = 5

# mode -> (max depth, seconds, max entries, recent files kept per root)
MODES: Dict[str, Tuple[int, int, int, int]] = {"quick": (3, 25, 60_000, 15), "full": (6, 900, 600_000, 40)}


def scan_dir() -> Path:
    return cfg.state_dir() / "scan"


def is_denied_name(name: str, extra: Sequence[str] = ()) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatch(lowered, pat.lower()) for pat in [*DENY_FILES, *extra])


def is_skipped_dir(name: str, extra: Sequence[str] = ()) -> bool:
    lowered = name.lower()
    return (lowered in DENY_DIRS or lowered in SKIP_DIRS or lowered in {e.lower() for e in extra}
            or lowered.endswith(SKIP_SUFFIXES) or name.startswith("."))


def configured_roots(override: Sequence[str] = ()) -> List[Path]:
    """Folders to scan: --root values, else scan.roots from the config, else the usual places that exist."""
    raw = list(override) or cfg.get("scan.roots") or DEFAULT_ROOTS
    out: List[Path] = []
    for item in raw:
        path = Path(str(item)).expanduser()
        if path.is_dir() and path not in out:
            out.append(path)
    return out


def label(path: object) -> str:
    """Path with the home folder shown as ~."""
    text = str(path)
    home = str(Path.home())
    return "~" + text[len(home):] if text == home or text.startswith(home + os.sep) else text


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def clip_line(line: str, width: int = 160) -> str:
    line = " ".join(line.split())
    if SECRET_LINE.search(line):
        return "[line hidden: looks like a secret]"
    return line if len(line) <= width else line[:width - 3] + "..."


def head_lines(path: Path, count: int = 5, limit: int = 2048) -> List[str]:
    """First non-empty text lines of a small file (badges and HTML skipped). Never raises."""
    if is_denied_name(path.name):
        return []
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit)
    except OSError:
        return []
    if b"\0" in raw:
        return []
    lines = [ln.strip() for ln in raw.decode("utf-8", errors="ignore").splitlines()]
    kept = [clip_line(ln) for ln in lines if ln and not ln.startswith(("[![", "![", "<", "---"))]
    return kept[:count]


class Walk:
    """Mutable collector used during one walk only; the result is turned into plain dicts at the end."""

    def __init__(self, root: Path, depth: int, deadline: float, max_entries: int, top_n: int, extra_dirs: Sequence[str], extra_files: Sequence[str]):
        self.root, self.depth, self.deadline, self.max_entries, self.top_n = root, depth, deadline, max_entries, top_n
        self.extra_dirs, self.extra_files = extra_dirs, extra_files
        self.entries = 0
        self.reason = ""
        self.repos: List[Path] = []
        self.vaults: List[Path] = []
        self.exports: List[str] = []
        self.heap: List[Tuple[float, str, int]] = []
        self.buckets: Dict[str, List[float]] = {}  # first folder under root -> mtimes of recent files outside repos
        self.cutoff = time.time() - RECENT_DAYS * 86400

    def over_budget(self) -> bool:
        if self.reason:
            return True
        if self.entries >= self.max_entries:
            self.reason = "entry cap reached"
        elif time.monotonic() > self.deadline:
            self.reason = "time cap reached"
        return bool(self.reason)

    def add_file(self, entry: "os.DirEntry[str]", in_repo: bool) -> None:
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            return
        item = (info.st_mtime, entry.path, info.st_size)
        if len(self.heap) < self.top_n:
            heapq.heappush(self.heap, item)
        elif item[0] > self.heap[0][0]:
            heapq.heapreplace(self.heap, item)
        if info.st_mtime >= self.cutoff and not in_repo:
            rel = Path(entry.path).relative_to(self.root)
            if len(rel.parts) > 1:
                self.buckets.setdefault(rel.parts[0], []).append(info.st_mtime)

    def visit(self, path: Path, depth: int, in_repo: bool, stack: list) -> None:
        try:
            entries = list(os.scandir(path))
        except OSError:
            return
        names = {e.name for e in entries}
        if ".git" in names:
            self.repos.append(path)
            in_repo = True
        if ".obsidian" in names:
            self.vaults.append(path)
        for entry in entries:
            self.entries += 1
            if NOTION_EXPORT.match(entry.name):
                self.exports.append(entry.path)
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                if depth < self.depth and not is_skipped_dir(entry.name, self.extra_dirs):
                    stack.append((Path(entry.path), depth + 1, in_repo))
            elif not entry.name.startswith(".") and not is_denied_name(entry.name, self.extra_files) and entry.is_file(follow_symlinks=False):
                self.add_file(entry, in_repo)
            if (self.entries >= self.max_entries or self.entries % 256 == 0) and self.over_budget():
                return

    def run(self) -> None:
        stack = [(self.root, 0, False)]
        while stack and not self.over_budget():
            path, depth, in_repo = stack.pop()
            self.visit(path, depth, in_repo, stack)


def count_markdown(folder: Path, cap: int = 5000, depth: int = 6) -> int:
    """Markdown files in a vault (names only, capped)."""
    total, stack = 0, [(folder, 0)]
    while stack and total < cap:
        path, level = stack.pop()
        try:
            for entry in os.scandir(path):
                if entry.is_dir(follow_symlinks=False):
                    if level < depth and not is_skipped_dir(entry.name):
                        stack.append((Path(entry.path), level + 1))
                elif entry.name.lower().endswith(".md"):
                    total += 1
        except OSError:
            continue
    return min(total, cap)


def repo_record(path: Path) -> dict:
    last = sources.last_commit_ts(path)
    readme = next((p for p in (path / n for n in README_NAMES) if p.is_file()), None)
    return {"name": path.name, "path": str(path), "last_commit": iso(last) if last else None,
            "last_commit_days": int((time.time() - last) // 86400) if last else None,
            "remote_host": sources.remote_host(path), "readme_head": head_lines(readme) if readme else []}


def file_record(path_str: str, mtime: float, size: int) -> dict:
    record = {"path": path_str, "modified": iso(mtime), "size": size}
    if path_str.lower().endswith((".md", ".markdown", ".txt")):
        title = head_lines(Path(path_str), count=1, limit=1024)
        if title:
            record["title"] = title[0]
    return record


def folder_records(walk: Walk) -> List[dict]:
    out = []
    for name, mtimes in walk.buckets.items():
        path = walk.root / name
        if len(mtimes) >= FOLDER_MIN_FILES and path not in walk.repos:
            out.append({"name": name, "path": str(path), "recent_files": len(mtimes), "last_modified": iso(max(mtimes)),
                        "last_modified_days": int((time.time() - max(mtimes)) // 86400)})
    return sorted(out, key=lambda r: -r["recent_files"])[:20]


def scan_roots(roots: Sequence[Path], mode: str, progress: Optional[Callable[[dict], None]] = None,
               max_seconds: Optional[int] = None) -> dict:
    """Walk the roots and probe sources and tools. Returns the scan as plain data (nothing is written here)."""
    depth, seconds, max_entries, top_n = MODES[mode]
    started = time.monotonic()
    deadline = started + (max_seconds if max_seconds is not None else seconds)
    extra_dirs, extra_files = list(cfg.get("scan.deny_dirs") or []), list(cfg.get("scan.deny_files") or [])
    projects: List[dict] = []
    folders: List[dict] = []
    recent: Dict[str, List[dict]] = {}
    vaults: List[dict] = []
    exports: List[str] = []
    entries, reason = 0, ""
    for index, root in enumerate(roots):
        if progress:
            progress({"phase": f"scanning {label(root)}", "roots_done": index, "roots_total": len(roots), "entries_seen": entries, "projects_found": len(projects)})
        walk = Walk(root, depth, deadline, max_entries - entries, top_n, extra_dirs, extra_files)
        walk.run()
        entries += walk.entries
        reason = reason or walk.reason
        projects += [repo_record(p) for p in walk.repos if p not in {Path(x["path"]) for x in projects}]
        folders += folder_records(walk)
        recent[str(root)] = [file_record(p, m, s) for m, p, s in sorted(walk.heap, reverse=True)]
        vaults += [{"path": str(v), "markdown_files": count_markdown(v)} for v in walk.vaults]
        exports += walk.exports
    projects.sort(key=lambda r: (r["last_commit_days"] is None, r["last_commit_days"] or 0))
    notion = sorted(set(exports) | set(sources.notion_downloads()))
    return {"version": 1, "mode": mode, "generated": cfg.now_iso(), "roots": [str(r) for r in roots],
            "limits": {"max_depth": depth, "seconds": seconds, "max_entries": max_entries, "recent_per_root": top_n},
            "projects": projects, "recent_folders": folders, "recent_files": recent,
            "notes": {"obsidian": vaults, "notion_exports": notion, "apple_notes": sources.apple_notes()},
            "sources": sources.probe_sources(), "tools": sources.installed_tools(),
            "stats": {"entries": entries, "seconds": round(time.monotonic() - started, 1), "truncated": bool(reason), "reason": reason}}


def render_summary(scan: dict) -> str:
    """Short Markdown summary (about 60 lines at most)."""
    stats, notes, src = scan["stats"], scan["notes"], scan["sources"]
    lines = [f"# Computer scan ({scan['mode']}, {scan['generated'][:10]})", "",
             f"Scanned: {', '.join(label(r) for r in scan['roots']) or 'nothing'}. {stats['entries']} entries in {stats['seconds']} s."
             + (f" Partial ({stats['reason']})." if stats["truncated"] else ""), "", f"## Projects ({len(scan['projects'])} git repos)"]
    for p in scan["projects"][:15]:
        age = "no commit" if p["last_commit_days"] is None else f"{p['last_commit_days']} d ago"
        host = f", {p['remote_host']}" if p["remote_host"] else ""
        about = f": {p['readme_head'][0]}" if p["readme_head"] else ""
        lines.append(f"- {p['name']} ({label(p['path'])}, last commit {age}{host}){about}")
    if len(scan["projects"]) > 15:
        lines.append(f"- ... and {len(scan['projects']) - 15} more (see scan.json)")
    lines += ["", f"## Folders with many recent files ({len(scan['recent_folders'])})"]
    lines += [f"- {f['name']} ({label(f['path'])}): {f['recent_files']} files in {RECENT_DAYS} days" for f in scan["recent_folders"][:10]]
    apple = notes["apple_notes"]
    vaults = ", ".join("%s (%d notes)" % (label(v["path"]), v["markdown_files"]) for v in notes["obsidian"]) or "none"
    lines += ["", "## Notes", f"- Obsidian vaults: {vaults}",
              f"- Notion export: {'yes (' + str(len(notes['notion_exports'])) + ')' if notes['notion_exports'] else 'none'}",
              f"- Apple Notes: {apple['count'] if apple.get('count') is not None else apple.get('status', 'unknown')}"]
    lines += ["", "## Sources (presence only)"] + [f"- {k}: {v}" for k, v in src.items() if k != "mcp_servers"]
    lines += ["", "## Tools", "- " + (", ".join(k for k, v in scan["tools"].items() if v) or "none") + " installed"]
    top = [f for files in scan["recent_files"].values() for f in files][:10]
    lines += ["", "## Recently active files"] + [f"- {label(f['path'])} ({f['modified'][:10]})" + (f": {f['title']}" if f.get("title") else "") for f in top]
    return "\n".join(lines) + "\n"


def write_outputs(scan: dict) -> Path:
    folder = scan_dir()
    cfg.atomic_write(folder / "scan.json", json.dumps(scan, indent=1, ensure_ascii=False) + "\n")
    cfg.atomic_write(folder / "scan.md", render_summary(scan))
    return folder / "scan.md"


def load_scan() -> dict:
    try:
        data = json.loads((scan_dir() / "scan.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- progress, consent

def progress_path() -> Path:
    return scan_dir() / "progress.json"


def write_progress(update: dict) -> None:
    """Merge `update` into progress.json (a new dict each time). Never raises."""
    try:
        current = read_progress()
        cfg.atomic_write(progress_path(), json.dumps({**current, **update, "updated": cfg.now_iso()}, indent=1) + "\n")
    except OSError:
        pass


def read_progress() -> dict:
    try:
        data = json.loads(progress_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def pid_alive(pid: object) -> bool:
    try:
        os.kill(int(str(pid)), 0)
        return True
    except (OSError, ValueError):
        return False


def status_lines() -> List[str]:
    state = read_progress()
    if not state:
        return ["No scan yet. Run: carlo scan --quick"]
    status = state.get("status", "unknown")
    if status in ("running", "starting") and not pid_alive(state.get("pid")):
        status = "stopped (the process is gone; run it again)"
    out = [f"scan {state.get('mode', '?')}: {status}"]
    if status == "running":
        out.append(f"  {state.get('phase', '')} ({state.get('roots_done', 0)}/{state.get('roots_total', 0)} folders, "
                   f"{state.get('entries_seen', 0)} entries, {state.get('projects_found', 0)} projects so far)")
    if state.get("error"):
        out.append(f"  error: {state['error']}")
    if status == "done":
        out.append(f"  summary: {scan_dir() / 'scan.md'}")
    out.append(f"  updated: {state.get('updated', '?')}")
    return out


def consent_path() -> Path:
    return scan_dir() / "consent.json"


def save_consent(roots: Sequence[Path]) -> None:
    cfg.atomic_write(consent_path(), json.dumps({"roots": [str(r) for r in roots], "at": cfg.now_iso()}, indent=1) + "\n")


def consented_roots() -> List[Path]:
    """Roots the user agreed to scan earlier (the weekly job never goes beyond them)."""
    try:
        data = json.loads(consent_path().read_text(encoding="utf-8"))
        return [Path(r) for r in data.get("roots", []) if Path(r).is_dir()]
    except (OSError, ValueError, AttributeError):
        return []


def run_and_store(mode: str, roots: Sequence[Path], max_seconds: Optional[int] = None) -> dict:
    """Scan with progress, write outputs, mark done or failed. Used by foreground, background and the weekly job."""
    write_progress({"status": "running", "mode": mode, "pid": os.getpid(), "started": cfg.now_iso(), "phase": "starting",
                    "roots_done": 0, "roots_total": len(roots), "entries_seen": 0, "projects_found": 0, "error": ""})
    last = [0.0]

    def tick(update: dict) -> None:
        if time.monotonic() - last[0] > 1:
            last[0] = time.monotonic()
            write_progress(update)

    try:
        scan = scan_roots(roots, mode, tick, max_seconds)
        write_outputs(scan)
    except Exception as exc:  # noqa: BLE001 - recorded in the progress file, then re-raised
        write_progress({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        raise
    write_progress({"status": "done", "phase": "finished", "roots_done": len(roots), "entries_seen": scan["stats"]["entries"],
                    "projects_found": len(scan["projects"])})
    return scan


# ---------------------------------------------------------------- CLI

def consent_text(roots: Sequence[Path], mode: str) -> str:
    depth, seconds, _, _ = MODES[mode]
    return ("carlo scan will read, in these folders only:\n" + "\n".join(f"  {label(r)}" for r in roots)
            + f"\nWhat it reads: file and folder names, dates, and the first lines of README and Markdown files (depth {depth}, "
              f"at most {seconds} s). It never reads mail or messages, keys, .env files, .ssh, Library or shell profiles, and sends nothing anywhere.\n"
              "Results stay in ~/.carlo-brain/state/scan/.")


def confirmed(args: object, roots: Sequence[Path], mode: str, ask: Callable[[str], str] = input, tty: Optional[bool] = None) -> bool:
    print(consent_text(roots, mode))
    if getattr(args, "yes", False):
        return True
    if not (sys.stdin.isatty() if tty is None else tty):
        print("Consent needed: run again with --yes to confirm these folders.")
        return False
    return ask("Scan these folders? [y/N] ").strip().lower() in ("y", "yes")


def start_background(mode: str, roots: Sequence[Path], max_seconds: Optional[int]) -> int:
    write_progress({"status": "starting", "mode": mode, "phase": "queued", "pid": 0, "error": ""})
    cmd = [sys.executable, "-I", str(Path(__file__).resolve()), "worker", mode, *(["--max-seconds", str(max_seconds)] if max_seconds else []),
           *[str(r) for r in roots]]
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                            env={**os.environ, "CARLO_HEADLESS": "1"})
    write_progress({"pid": proc.pid})
    print(f"Scan started in the background (pid {proc.pid}). Check: carlo scan --status")
    return 0


def run_cli(args: object) -> int:
    """Entry point for `carlo scan`. `args` carries quick, full, background, status, yes, root, dismiss, max_seconds."""
    if getattr(args, "status", False):
        print("\n".join(status_lines()))
        return 0
    if getattr(args, "dismiss", None):
        import carlo_mapdiff
        carlo_mapdiff.dismiss(args.dismiss)
        print(f"Noted: '{args.dismiss}' will not be suggested again.")
        return 0
    mode = "full" if getattr(args, "full", False) else "quick"
    roots = configured_roots(getattr(args, "root", None) or [])
    if not roots:
        print("No folder to scan: none of the usual places exist. Pass --root PATH or set scan.roots with `carlo config set scan.roots '[\"~/Work\"]'`.")
        return 1
    if not confirmed(args, roots, mode):
        return 2
    save_consent(roots)
    max_seconds = getattr(args, "max_seconds", None)
    if getattr(args, "background", False):
        return start_background(mode, roots, max_seconds)
    scan = run_and_store(mode, roots, max_seconds)
    print(render_summary(scan))
    print(f"Saved: {scan_dir() / 'scan.json'} and scan.md")
    return 0


def worker(argv: Sequence[str]) -> int:
    """Background process: `worker MODE [--max-seconds N] ROOT...` (consent was given before it started)."""
    mode, rest = argv[0], list(argv[1:])
    seconds = None
    if rest[:1] == ["--max-seconds"]:
        seconds, rest = int(rest[1]), rest[2:]
    try:
        run_and_store(mode, [Path(r) for r in rest if Path(r).is_dir()], seconds)
    except Exception as exc:  # noqa: BLE001 - already written to progress.json
        cfg.log_error("scan.worker", exc)
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "worker" and sys.argv[2] in MODES:
        sys.exit(worker(sys.argv[2:]))
    print("Use `carlo scan`.", file=sys.stderr)
    sys.exit(2)
