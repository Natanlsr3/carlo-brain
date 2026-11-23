"""Text extraction for `carlo search`: PDF, Word, PowerPoint, Excel and Apple Mail .emlx. Read only.

Standard library only. Office files are read with zipfile and regular expressions, never with an XML
parser, so a hostile file cannot use entity expansion. Everything is size capped. A failure of any kind
returns None (the caller falls back to the file name) and never raises.

PDF order: `pdftotext` if installed, else macOS `mdimport -t -d2`, else the Spotlight text (`mdls`).
"""
from __future__ import annotations

import email
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from email import policy
from pathlib import Path
from typing import Dict, List, Optional

OFFICE_EXT = {".docx", ".pptx", ".xlsx"}
DOCUMENT_EXT = OFFICE_EXT | {".pdf"}
MAX_TEXT_CHARS = 2_000_000
CACHE_VERSION = 1
IGNORED_MAILBOX = re.compile(r"trash|junk|spam|deleted|draft", re.I)
_RUN = re.compile(r"<(?:w|a):t(?:\s[^>]*)?>(.*?)</(?:w|a):t>", re.S)


def is_document(path: Path) -> bool:
    return path.suffix.lower() in DOCUMENT_EXT


def _unescape(text: str) -> str:
    return html.unescape(text)


def _read_members(path: Path, wanted, limit: int) -> Dict[str, str]:
    """Text of the zip members whose name satisfies `wanted`, refusing archives that expand past `limit` bytes."""
    out: Dict[str, str] = {}
    with zipfile.ZipFile(path) as zf:
        infos = [i for i in zf.infolist() if wanted(i.filename)]
        if sum(i.file_size for i in infos) > limit:
            raise ValueError("archive expands too much")
        for info in infos:
            out[info.filename] = zf.read(info).decode("utf-8", errors="replace")
    return out


def _numbered(name: str) -> int:
    digits = re.findall(r"\d+", name)
    return int(digits[-1]) if digits else 0


def _paragraphs(xml: str, para_tag: str) -> List[str]:
    """One line per paragraph (`w:p` or `a:p`), runs joined, tabs as spaces."""
    lines = []
    for chunk in re.split(rf"</{para_tag}>", xml):
        chunk = re.sub(r"<(?:w:tab|w:br|a:br)\s*/>", "</w:t><w:t> </w:t>", chunk)
        text = "".join(_unescape(m) for m in _RUN.findall(chunk)).strip()
        if text:
            lines.append(text)
    return lines


def extract_docx(path: Path, limit: int) -> str:
    parts = _read_members(path, lambda n: re.fullmatch(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml", n) is not None, limit)
    ordered = sorted(parts, key=lambda n: (n != "word/document.xml", n))
    return "\n".join(line for name in ordered for line in _paragraphs(parts[name], "w:p"))


def extract_pptx(path: Path, limit: int) -> str:
    parts = _read_members(path, lambda n: re.fullmatch(r"ppt/(slides|notesSlides)/(slide|notesSlide)\d+\.xml", n) is not None, limit)
    ordered = sorted(parts, key=lambda n: (_numbered(n), "notes" in n))
    return "\n".join(line for name in ordered for line in _paragraphs(parts[name], "a:p"))


def _shared_strings(xml: str) -> List[str]:
    return [_unescape("".join(re.findall(r"<t(?:\s[^>]*)?>(.*?)</t>", si, re.S))) for si in re.findall(r"<si\b[^>]*>(.*?)</si>", xml, re.S)]


def _sheet_rows(xml: str, shared: List[str]) -> List[str]:
    rows = []
    for row in re.findall(r"<row\b[^>]*>(.*?)</row>", xml, re.S):
        cells = []
        for attrs, inner in re.findall(r"<c\b([^>]*?)(?:/>|>(.*?)</c>)", row, re.S):
            kind = re.search(r'\bt="(\w+)"', attrs)
            kind = kind.group(1) if kind else ""
            if kind == "inlineStr":
                value = _unescape("".join(re.findall(r"<t(?:\s[^>]*)?>(.*?)</t>", inner, re.S)))
            else:
                match = re.search(r"<v>(.*?)</v>", inner, re.S)
                value = match.group(1) if match else ""
                if kind == "s":
                    value = shared[int(value)] if value.isdigit() and int(value) < len(shared) else ""
                else:
                    value = _unescape(value)
            if value.strip():
                cells.append(value.strip())
        if cells:
            rows.append(" | ".join(cells))
    return rows


def extract_xlsx(path: Path, limit: int) -> str:
    parts = _read_members(path, lambda n: n == "xl/sharedStrings.xml" or re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n) is not None, limit)
    shared = _shared_strings(parts.get("xl/sharedStrings.xml", ""))
    sheets = sorted((n for n in parts if n.startswith("xl/worksheets/")), key=_numbered)
    return "\n".join(row for name in sheets for row in _sheet_rows(parts[name], shared))


def _spotlight_text(output: str) -> str:
    match = re.search(r'kMDItemTextContent\s*=\s*"(.*?)";?\s*\n', output, re.S)
    return match.group(1).replace('\\"', '"').replace("\\n", "\n") if match else ""


def extract_pdf(path: Path, timeout: int = 20) -> str:
    """pdftotext, else `mdimport -t -d2`, else the Spotlight text. '' when none gives text."""
    exe = shutil.which("pdftotext")
    attempts = []
    if exe:
        attempts.append(([exe, "-q", "-enc", "UTF-8", str(path), "-"], lambda r: r.stdout))
    if sys.platform == "darwin":
        attempts.append((["mdimport", "-t", "-d2", str(path)], lambda r: _spotlight_text((r.stdout or "") + "\n" + (r.stderr or ""))))
        attempts.append((["mdls", "-raw", "-name", "kMDItemTextContent", str(path)], lambda r: "" if (r.stdout or "").strip() == "(null)" else r.stdout))
    for argv, pick in attempts:
        try:
            res = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            continue
        text = pick(res) if res.returncode == 0 else ""
        if text and text.strip():
            return text
    return ""


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(style|script|head)\b.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def extract_emlx(path: Path, limit: int) -> str:
    """Headers (subject, from, to, date) then the body: plain text preferred, else HTML stripped. Read only."""
    if path.stat().st_size > limit:
        raise ValueError("message too large")
    data = path.read_bytes()
    first, _, rest = data.partition(b"\n")
    raw = rest[: int(first)] if first.strip().isdigit() and int(first) <= len(rest) else rest  # trailing plist is not mail
    msg = email.message_from_bytes(raw, policy=policy.default)
    head = [f"{k}: {msg.get(k, '')}" for k in ("Subject", "From", "To", "Cc", "Date") if msg.get(k)]
    part = msg.get_body(("plain", "html"))
    body = ""
    if part is not None:
        try:
            body = part.get_content()
        except (LookupError, ValueError, UnicodeError):
            body = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
        if part.get_content_type() == "text/html":
            body = strip_html(body)
    return "\n".join(head + [ln.rstrip() for ln in str(body).splitlines()])


def extract(path: Path, max_bytes: int) -> Optional[str]:
    """Plain text of a document, or None (unsupported, too big, broken). Never raises."""
    ext = path.suffix.lower()
    try:
        if path.stat().st_size > max_bytes:
            return None
        if ext == ".pdf":
            text = extract_pdf(path)
        elif ext in OFFICE_EXT:
            text = {".docx": extract_docx, ".pptx": extract_pptx, ".xlsx": extract_xlsx}[ext](path, max_bytes * 4)
        else:
            return None
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError, EOFError):
        return None
    return text[:MAX_TEXT_CHARS] if text and text.strip() else None


# ------------------------------------------------------------------ cache (opt in)

def _cache_file(cache_dir: Path, path: Path) -> Path:
    return cache_dir / (hashlib.sha256(str(path).encode("utf-8", "replace")).hexdigest()[:40] + ".json")


def cache_get(cache_dir: Path, path: Path, mtime: float, size: int) -> Optional[str]:
    try:
        data = json.loads(_cache_file(cache_dir, path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ok = isinstance(data, dict) and data.get("v") == CACHE_VERSION and data.get("path") == str(path) \
        and data.get("mtime") == mtime and data.get("size") == size
    return str(data.get("text", "")) if ok else None


def cache_size(cache_dir: Path) -> int:
    try:
        return sum(p.stat().st_size for p in cache_dir.glob("*.json"))
    except OSError:
        return 0


def cache_put(cache_dir: Path, path: Path, mtime: float, size: int, text: str) -> int:
    """Store already redacted text, private to the user (0600 in a 0700 folder). Returns bytes written, 0 on failure."""
    target = _cache_file(cache_dir, path)
    payload = json.dumps({"v": CACHE_VERSION, "path": str(path), "mtime": mtime, "size": size, "text": text}, ensure_ascii=False)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(cache_dir, 0o700)
        tmp = target.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp, target)
    except OSError:
        return 0
    return len(payload)


def cache_clear(cache_dir: Path) -> int:
    """Delete the cache entries (only our own `*.json` files in that folder). Returns how many."""
    count = 0
    for entry in cache_dir.glob("*.json"):
        try:
            entry.unlink()
            count += 1
        except OSError:
            continue
    return count
