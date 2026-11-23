#!/usr/bin/env python3
"""Local, read-only search over your whole computer, in a fixed order (beta).

Order: vault, configured folders, Apple Notes, Apple Messages, Apple Mail (subject, sender and message
bodies), then optionally Spotlight. Content is read from text files, PDF, Word, PowerPoint and Excel files
and .emlx mail (see textextract.py). Results are `path:line: snippet`, capped. Nothing is sent, and the only
thing written is the optional text cache under ~/.carlo-brain/state/search-cache (off unless
`"cache": true` or --rebuild-cache).
A deny list (keys, .env files, .ssh, shell profiles, secret stores, Library) always applies, binary and
huge files are skipped, and a line that looks like a secret is never printed (nor cached).

Usage: search.py "<query>" [--source vault,folders,notes,messages,mail,spotlight] [--max 30] [--json] [--spotlight]
       search.py --rebuild-cache [query]
Config (optional): ~/.carlo-brain/config.d/search.json, see the module README.
Python 3.9+, standard library only.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python3 -I` does not add the script folder
import textextract as tx  # noqa: E402

DEFAULT_FOLDERS = ["~/Documents", "~/Desktop", "~/Downloads"]
DEFAULT_SOURCES = ["vault", "folders", "notes", "messages", "mail"]
# Always applied (the config can add to these, never remove).
DENY_DIRS = {".ssh", ".gnupg", ".aws", ".kube", ".git", "library", "keys", "secrets", "node_modules", ".venv", "venv",
             "__pycache__", ".trash", ".cache", "caches", "site-packages"}
DENY_FILES = [".env", ".env.*", "*.env", "*.pem", "*.key", "*.p12", "*.pfx", "*.keychain*", "*.kdbx", "id_rsa*", "id_ed25519*",
              "*token*", "*secret*", "*password*", "*passwd*", "*credential*", ".netrc", ".npmrc", ".pgpass", "*.gpg",
              ".zshrc", ".zprofile", ".zshenv", ".bashrc", ".bash_profile", ".profile", ".bash_history", ".zsh_history"]
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".heic", ".pdf", ".zip", ".gz", ".tar", ".dmg", ".pkg", ".app", ".mp3", ".mp4",
              ".mov", ".wav", ".sqlite", ".db", ".pyc", ".so", ".dylib", ".exe", ".xlsx", ".docx", ".pptx", ".psd", ".iso"}
SECRET_LINE = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY|(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*\S{6,}"
                         r"|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9-]{10,})", re.I)
REDACTED = "[line hidden: looks like a secret]"


@dataclass(frozen=True)
class Hit:
    """One result. `line` is 0 for a file name match or a non-file source."""
    source: str
    path: str
    line: int
    snippet: str

    def render(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"[{self.source}] {where}: {self.snippet}" if self.snippet else f"[{self.source}] {where}"


def brain_home() -> Path:
    return Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain")


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def vault_path(brain: Path) -> Optional[Path]:
    raw = os.environ.get("CARLO_VAULT") or read_json(brain / "config.json").get("vault")
    return Path(str(raw)).expanduser() if raw else None


def fold(text: str) -> str:
    """Lowercase without accents, so 'ecole' finds 'École'."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def terms_of(query: str) -> List[str]:
    return [t for t in fold(query).split() if t]


def matches(text: str, terms: Sequence[str]) -> bool:
    folded = fold(text)
    return bool(terms) and all(t in folded for t in terms)


def snippet_of(line: str, terms: Sequence[str], width: int = 160) -> str:
    """The line trimmed around the first term, or a placeholder when it looks like a secret."""
    if SECRET_LINE.search(line):
        return REDACTED
    line = " ".join(line.split())
    if len(line) <= width:
        return line
    start = max(0, fold(line).find(terms[0]) - width // 3) if terms else 0
    return ("..." if start else "") + line[start:start + width].strip() + "..."


def is_denied(path: Path, extra_dirs: Sequence[str] = (), extra_files: Sequence[str] = ()) -> bool:
    """True for anything under a denied folder or with a denied name (case insensitive)."""
    dirs = DENY_DIRS | {d.lower() for d in extra_dirs}
    if any(part.lower() in dirs for part in path.parts[:-1]):
        return True
    name = path.name.lower()
    return any(fnmatch.fnmatch(name, pat.lower()) for pat in [*DENY_FILES, *extra_files])


def looks_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXT:
        return True
    try:
        with path.open("rb") as handle:
            return b"\0" in handle.read(4096)
    except OSError:
        return True


@dataclass(frozen=True)
class Options:
    """Search limits, built from the defaults and config.d/search.json."""
    limit: int = 30
    per_file: int = 3
    max_file_kb: int = 1024
    time_budget_s: float = 20.0
    extra_dirs: tuple = ()
    extra_files: tuple = ()
    folders: tuple = tuple(DEFAULT_FOLDERS)
    deep: bool = True  # read inside PDF, Office files and mail bodies
    max_doc_mb: int = 20
    max_mail_kb: int = 4096
    cache_dir: Optional[Path] = None  # None: no cache
    cache_max_mb: int = 200


def walk_files(root: Path, opts: Options, deadline: float) -> Iterator[Path]:
    """Files under root, skipping denied folders and names. Stops at the deadline."""
    deny = DENY_DIRS | {d.lower() for d in opts.extra_dirs}
    for current, dirs, files in os.walk(root, followlinks=False):
        if time.monotonic() > deadline:
            return
        dirs[:] = sorted(d for d in dirs if d.lower() not in deny and not d.startswith("."))
        for name in sorted(files):
            if not is_denied(Path(name), opts.extra_dirs, opts.extra_files):  # only the name: ancestors of an explicit root are allowed
                yield Path(current) / name


def redact_text(text: str) -> str:
    """Secret-looking lines replaced by the placeholder, so a secret is never cached nor shown in a snippet."""
    return "\n".join(REDACTED if SECRET_LINE.search(line) else line for line in text.splitlines())


def document_text(path: Path, opts: Options) -> Optional[str]:
    """Redacted text of a PDF or Office file, through the cache when it is on. None when it cannot be read."""
    try:
        info = path.stat()
    except OSError:
        return None
    if opts.cache_dir is not None:
        cached = tx.cache_get(opts.cache_dir, path, info.st_mtime, info.st_size)
        if cached is not None:
            return cached
    raw = tx.extract(path, opts.max_doc_mb * 1024 * 1024)
    if raw is None:
        return None
    text = redact_text(raw)
    if opts.cache_dir is not None and tx.cache_size(opts.cache_dir) < opts.cache_max_mb * 1024 * 1024:
        tx.cache_put(opts.cache_dir, path, info.st_mtime, info.st_size, text)
    return text


def lines_hits(lines: Sequence[str], path: str, terms: Sequence[str], per_file: int) -> List[Hit]:
    hits: List[Hit] = []
    for number, line in enumerate(lines, 1):
        if matches(line, terms):
            hits.append(Hit("", path, number, snippet_of(line, terms)))
            if len(hits) >= per_file:
                break
    return hits


def search_document(path: Path, terms: Sequence[str], opts: Options) -> List[Hit]:
    """Content hits in a PDF or Office file; falls back to a file name match."""
    text = document_text(path, opts) if opts.deep else None
    hits = lines_hits(text.splitlines(), str(path), terms, opts.per_file) if text else []
    if not hits and matches(path.name, terms):
        hits.append(Hit("", str(path), 0, "(file name)"))
    return hits


def search_file(path: Path, terms: Sequence[str], opts: Options) -> List[Hit]:
    """Lines of one text file that contain every term, plus a file name match."""
    if tx.is_document(path):
        return search_document(path, terms, opts)
    hits: List[Hit] = []
    try:
        if path.stat().st_size > opts.max_file_kb * 1024 or looks_binary(path):
            return hits
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for number, line in enumerate(handle, 1):
                if matches(line, terms):
                    hits.append(Hit("", str(path), number, snippet_of(line, terms)))
                    if len(hits) >= opts.per_file:
                        break
    except OSError:
        return hits
    if not hits and matches(path.name, terms):
        hits.append(Hit("", str(path), 0, "(file name)"))
    return hits


def mtime_of(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def search_tree(source: str, root: Path, terms: Sequence[str], opts: Options, deadline: float,
                doc_deadline: Optional[float] = None) -> List[Hit]:
    """Hits under one folder, most recently modified files first, capped.

    Text files are read during the walk. PDF and Office files are read afterwards, newest first, until
    `doc_deadline` (they are slower), so they cannot eat the budget of the plain files.
    """
    if not root.is_dir() or root.name.lower() in DENY_DIRS | {d.lower() for d in opts.extra_dirs}:
        return []
    found, documents = [], []
    for path in walk_files(root, opts, deadline):
        if tx.is_document(path):
            documents.append(path)
            continue
        for hit in search_file(path, terms, opts):
            found.append((mtime_of(path), Hit(source, hit.path, hit.line, hit.snippet)))
    for path in sorted(documents, key=mtime_of, reverse=True):
        if time.monotonic() > (doc_deadline or deadline):
            break
        for hit in search_document(path, terms, opts):
            found.append((mtime_of(path), Hit(source, hit.path, hit.line, hit.snippet)))
    found.sort(key=lambda item: -item[0])
    return [hit for _, hit in found][: opts.limit]


def run_reader(script: Path, args: List[str], timeout: int = 30) -> List[str]:
    """Output lines of a read-only connector script (empty when absent or failing)."""
    if not script.exists():
        return []
    env = {k: v for k, v in os.environ.items() if not re.search(r"(API_KEY|_KEY$|SECRET|PASSWORD|TOKEN)", k, re.I)}
    try:
        res = subprocess.run([sys.executable, "-I", str(script), *args], capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if res.returncode != 0:
        return []
    return [ln for ln in res.stdout.splitlines() if ln.strip() and not re.match(r"^\d+ (note|result|message)", ln)]


def search_apple(source: str, query: str, brain: Path, opts: Options, platform: str = sys.platform) -> List[Hit]:
    """Notes or Messages through the connectors' own read-only readers (macOS, Full Disk Access)."""
    if platform != "darwin":
        return []
    script = brain / "connectors" / "apple" / ("notes.py" if source == "notes" else "messages.py")
    lines = run_reader(script, ["search", query, "--max", str(opts.limit)])
    return [Hit(source, source, 0, snippet_of(ln, terms_of(query))) for ln in lines[: opts.limit]]


def find_mail_index(root: Optional[Path] = None) -> Optional[Path]:
    base = root or Path.home() / "Library" / "Mail"
    found = sorted(base.glob("V*/MailData/Envelope Index"), key=lambda p: int(re.sub(r"\D", "", p.parents[1].name) or 0), reverse=True)
    return found[0] if found else None


def search_mail(query: str, opts: Options, index: Optional[Path] = None, platform: str = sys.platform) -> List[Hit]:
    """Subject and sender in Apple Mail's local index, Sent included (read-only, mode=ro)."""
    index = index or (find_mail_index() if platform == "darwin" else None)
    terms = terms_of(query)
    if index is None or not terms:
        return []
    clause = " AND ".join("(lower(s.subject) LIKE ? OR lower(a.address) LIKE ? OR lower(coalesce(a.comment,'')) LIKE ?)" for _ in terms)
    args = [f"%{t}%" for t in terms for _ in range(3)] + [opts.limit]
    try:
        con = sqlite3.connect(f"file:{index}?mode=ro", uri=True, timeout=2)
        try:
            rows = con.execute("SELECT datetime(m.date_received,'unixepoch','localtime'), a.address, s.subject FROM messages m "
                               "JOIN addresses a ON m.sender=a.ROWID JOIN subjects s ON m.subject=s.ROWID "
                               f"WHERE m.deleted = 0 AND {clause} ORDER BY m.date_received DESC LIMIT ?", args).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    return [Hit("mail", "mail", 0, snippet_of(f"{d} from {a}: {s}", terms)) for d, a, s in rows]


def iter_emlx(root: Path, deadline: float) -> List[Path]:
    """Message files under Apple Mail's folder (Sent included; Trash, Junk, Drafts skipped), newest first."""
    found = []
    for current, dirs, files in os.walk(root, followlinks=False):
        if time.monotonic() > deadline:
            break
        dirs[:] = [d for d in dirs if not (d.lower().endswith(".mbox") and tx.IGNORED_MAILBOX.search(d)) and d.lower() != "attachments"]
        found += [Path(current) / n for n in files if n.endswith(".emlx")]
    return sorted(found, key=mtime_of, reverse=True)


def search_mail_bodies(terms: Sequence[str], opts: Options, root: Optional[Path] = None, deadline: Optional[float] = None,
                       platform: str = sys.platform) -> List[Hit]:
    """Message bodies in Apple Mail's local .emlx files, parsed read only. Plain text preferred, else HTML stripped.

    The message file itself is the hit path. Deadline defaults to one time budget.
    """
    if not terms or not opts.deep or (root is None and platform != "darwin"):
        return []
    base = root or Path.home() / "Library" / "Mail"
    deadline = deadline or time.monotonic() + opts.time_budget_s
    hits: List[Hit] = []
    for path in iter_emlx(base, deadline):
        if time.monotonic() > deadline or len(hits) >= opts.limit:
            break
        try:
            text = tx.extract_emlx(path, opts.max_mail_kb * 1024)
        except (OSError, ValueError):
            continue
        hits += [Hit("mail", h.path, h.line, h.snippet) for h in lines_hits(text.splitlines(), str(path), terms, opts.per_file)]
    return hits[: opts.limit]


def search_spotlight(query: str, folders: Sequence[Path], opts: Options, platform: str = sys.platform,
                     run: Callable = subprocess.run) -> List[Hit]:
    """File paths Spotlight knows (macOS `mdfind`), filtered by the deny list. Paths only."""
    if platform != "darwin":
        return []
    hits: List[Hit] = []
    for folder in folders:
        try:
            res = run(["mdfind", "-onlyin", str(folder), query], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            continue
        for line in (res.stdout or "").splitlines():
            path = Path(line)
            if line and not is_denied(path, opts.extra_dirs, opts.extra_files):
                hits.append(Hit("spotlight", line, 0, "(spotlight match)"))
    return hits[: opts.limit]


def build_options(brain: Path, limit: Optional[int] = None, force_cache: bool = False) -> Options:
    conf = read_json(brain / "config.d" / "search.json")
    return Options(limit=int(limit or conf.get("max_results", 30)), per_file=int(conf.get("max_per_file", 3)),
                   max_file_kb=int(conf.get("max_file_kb", 1024)), time_budget_s=float(conf.get("time_budget_s", 20)),
                   extra_dirs=tuple(str(d) for d in conf.get("deny_dirs", [])),
                   extra_files=tuple(str(f) for f in conf.get("deny_files", [])),
                   folders=tuple(conf.get("folders") or DEFAULT_FOLDERS), deep=bool(conf.get("deep", True)),
                   max_doc_mb=int(conf.get("max_doc_mb", 20)), max_mail_kb=int(conf.get("max_mail_kb", 4096)),
                   cache_dir=brain / "state" / "search-cache" if (conf.get("cache") or force_cache) else None,
                   cache_max_mb=int(conf.get("cache_max_mb", 200)))


def search_all(query: str, sources: Sequence[str], brain: Optional[Path] = None, limit: Optional[int] = None,
               platform: str = sys.platform, mail_root: Optional[Path] = None, force_cache: bool = False) -> List[Hit]:
    """Run the sources in the given order and return at most `limit` hits in total.

    Time: the walk of the folders gets `time_budget_s`, reading inside PDF, Office files and mail bodies
    gets the same again after it.
    """
    brain = brain or brain_home()
    opts, terms = build_options(brain, limit, force_cache), terms_of(query)
    deadline = time.monotonic() + opts.time_budget_s
    doc_deadline = deadline + opts.time_budget_s
    out: List[Hit] = []
    for source in sources:
        if len(out) >= opts.limit or not terms:
            break
        if source == "vault":
            vault = vault_path(brain)
            out += search_tree("vault", vault, terms, opts, deadline, doc_deadline) if vault else []
        elif source == "folders":
            for folder in opts.folders:
                out += search_tree("files", Path(folder).expanduser(), terms, opts, deadline, doc_deadline)
        elif source in ("notes", "messages"):
            out += search_apple(source, query, brain, opts, platform)
        elif source == "mail":
            index = find_mail_index(mail_root) if mail_root else None
            if mail_root is None or index is not None:  # an explicit root never falls back to the real Mail folder
                out += search_mail(query, opts, index=index, platform=platform)
            out += search_mail_bodies(terms, opts, mail_root, doc_deadline, platform)
        elif source == "spotlight":
            out += search_spotlight(query, [Path(f).expanduser() for f in opts.folders], opts, platform)
    return out[: opts.limit]


def rebuild_cache(brain: Optional[Path] = None) -> int:
    """Empty the text cache, then extract every PDF and Office file of the vault and folders into it.

    Returns how many documents were cached. Same deny list, size caps and redaction as a search; stops at
    the time budget (walk, then the same again for extraction) or at `cache_max_mb`.
    """
    brain = brain or brain_home()
    opts = build_options(brain, force_cache=True)
    assert opts.cache_dir is not None
    tx.cache_clear(opts.cache_dir)
    deadline = time.monotonic() + opts.time_budget_s
    doc_deadline = deadline + opts.time_budget_s
    roots = ([vault_path(brain)] if vault_path(brain) else []) + [Path(f).expanduser() for f in opts.folders]
    count = 0
    for root in roots:
        if not root.is_dir() or root.name.lower() in DENY_DIRS | {d.lower() for d in opts.extra_dirs}:
            continue
        for path in sorted((p for p in walk_files(root, opts, deadline) if tx.is_document(p)), key=mtime_of, reverse=True):
            if time.monotonic() > doc_deadline:
                return count
            count += 1 if document_text(path, opts) is not None else 0
    return count


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="carlo search", description="Read-only search over vault, folders (text, PDF, Office), Notes, Messages, Mail.")
    parser.add_argument("query", nargs="*")
    parser.add_argument("--source", help=f"comma list, in this order (default: {','.join(DEFAULT_SOURCES)})")
    parser.add_argument("--max", type=int, help="total results (default 30)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--spotlight", action="store_true", help="also ask Spotlight (macOS)")
    parser.add_argument("--rebuild-cache", action="store_true",
                        help="empty the text cache (state/search-cache) and refill it from PDF and Office files, then search if a query is given")
    args = parser.parse_args(list(argv))
    if not args.query and not args.rebuild_cache:
        parser.error("give a query, or --rebuild-cache")
    return args


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    if args.rebuild_cache:
        print(f"cache rebuilt: {rebuild_cache()} document(s)")
        if not args.query:
            return 0
    sources = [s.strip() for s in args.source.split(",")] if args.source else list(DEFAULT_SOURCES)
    if args.spotlight and "spotlight" not in sources:
        sources.append("spotlight")
    hits = search_all(" ".join(args.query), sources, limit=args.max, force_cache=args.rebuild_cache)
    if args.json:
        print(json.dumps([asdict(h) for h in hits], ensure_ascii=False))
    else:
        for hit in hits:
            print(hit.render())
        print(f"{len(hits)} result(s)")
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
