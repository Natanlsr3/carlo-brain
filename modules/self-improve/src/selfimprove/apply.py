"""Apply a proposal: validate, classify, back up, write, verify, restore for real if a check fails.

A proposal is a JSON file:
  {"id": "2026-03-01-short-name", "title": "...", "reason": "...", "source": "report or evidence",
   "changes": [{"file": "~/.claude/agents/x.md", "old": "exact text, present once", "new": "replacement"},
               {"file": "~/vault/00_System/skills/y.md", "content": "whole new file"}],
   "test_command": "python3 /path/to/check.py"}      # optional, no shell, no `~`, no `&&`
The tier of the files decides: auto = applied (with backup and checks), review = a readable diff is
written for you and nothing changes, manual = refused.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import journal, verify
from .settings import Settings
from .tiers import real_path, tier_of_all

Contents = Dict[Path, Tuple[Optional[str], str]]  # path -> (old text or None if absent, new text)
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}")


def validate(proposal: Any) -> None:
    """Shape check of an external input. Raises ValueError."""
    if not isinstance(proposal, dict):
        raise ValueError("a proposal must be a JSON object")
    for key in ("id", "title", "reason", "source"):
        if not isinstance(proposal.get(key), str) or not proposal[key].strip():
            raise ValueError(f"field '{key}' missing or empty")
    if not ID_PATTERN.fullmatch(proposal["id"]) or ".." in proposal["id"]:
        raise ValueError("invalid id (letters, digits, _ . - only)")
    changes = proposal.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError("'changes' must be a non-empty list")
    for change in changes:
        if not isinstance(change, dict) or not isinstance(change.get("file"), str):
            raise ValueError("every change needs a 'file'")
        whole = "content" in change
        replace = "old" in change and "new" in change
        if whole == replace or not all(isinstance(change.get(k, ""), str) for k in ("content", "old", "new")):
            raise ValueError("every change is either 'content' or 'old' + 'new' (strings)")
        if replace and not change["old"]:
            raise ValueError("'old' cannot be empty")
    if "test_command" in proposal and not isinstance(proposal["test_command"], str):
        raise ValueError("'test_command' must be a string")


def compute(proposal: Dict[str, Any], cfg: Settings) -> Contents:
    """New content of every file, in memory only. Raises ValueError, never touches the disk."""
    state: Contents = {}
    for change in proposal["changes"]:
        path = real_path(change["file"], cfg)
        if path not in state:
            if path.is_dir():
                raise ValueError(f"{path} is a folder")
            try:
                old = path.read_bytes().decode("utf-8") if path.exists() else None
            except UnicodeDecodeError:
                raise ValueError(f"{path} is not UTF-8 text") from None
            state[path] = (old, old or "")
        origin, current = state[path]
        if "content" in change:
            state[path] = (origin, change["content"])
            continue
        count = current.count(change["old"])
        if count != 1:
            raise ValueError(f"text 'old' {'not found' if count == 0 else f'ambiguous ({count} matches)'} in {path}")
        state[path] = (origin, current.replace(change["old"], change["new"], 1))
    return state


def readable_diff(path: Path, old: Optional[str], new: str) -> str:
    """'Current line / proposed line' blocks."""
    if old is None:
        return f"### {path}\n\nFile does not exist. Proposed content:\n\n```\n{new}\n```\n"
    a, b = old.splitlines(), new.splitlines()
    blocks = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if op == "equal":
            continue
        blocks.append(f"Current (line {i1 + 1}):\n```\n{chr(10).join(a[i1:i2]) or '(none)'}\n```\n"
                      f"Proposed:\n```\n{chr(10).join(b[j1:j2]) or '(removed)'}\n```\n")
    return f"### {path}\n\n" + "\n".join(blocks)


def write_atomic(path: Path, text: str) -> None:
    """Write through a temp file then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".selfimprove-tmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


def restore(manifest: Dict[str, Any], folder: Path) -> None:
    """Put every file back byte for byte from the archive (files this run created are removed)."""
    for item in manifest["files"]:
        target = Path(item["path"])
        if item["archive"] is None:
            target.unlink(missing_ok=True)
        else:
            shutil.copyfile(folder / item["archive"], target)


def _apply_auto(proposal: Dict[str, Any], cfg: Settings, contents: Contents) -> Tuple[str, str, Dict[str, Any]]:
    """Archive, write, verify, restore on failure. Returns (verdict, reason, manifest)."""
    folder = cfg.archives / proposal["id"]
    folder.mkdir(parents=True)
    stamp = journal.now().replace(" ", "_").replace(":", "h")
    items = []
    for i, path in enumerate(contents):
        name = None
        if path.exists():
            name = f"{stamp}__{i}_{path.name}"
            shutil.copyfile(path, folder / name)
        items.append({"path": str(path), "archive": name, "sha_before": journal.file_sha(path)})
    manifest: Dict[str, Any] = {"id": proposal["id"], "status": "in progress", "files": items}
    errors: List[str] = []
    try:
        for path, (_, new) in contents.items():
            write_atomic(path, new)
        for path, (old, new) in contents.items():
            errors += verify.check_file(path, old or "", new, cfg.test_timeout, cfg.forbidden_in_markdown)
        if proposal.get("test_command"):
            errors += verify.run_test_command(proposal["test_command"], cfg.test_timeout)
    except Exception as err:  # noqa: BLE001 - a failed write or check must still restore
        errors.append(f"unexpected error: {err}")
    if errors:
        restore(manifest, folder)
        manifest["status"] = "restored"
        verdict, reason = "restored", "; ".join(errors)
    else:
        manifest["status"] = "applied"
        verdict, reason = "applied", "checks passed"
    for item in manifest["files"]:
        item["sha_after"] = journal.file_sha(Path(item["path"]))
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return verdict, reason, manifest


def _to_review(proposal: Dict[str, Any], cfg: Settings, contents: Contents, done: Callable[..., Dict[str, Any]]) -> Dict[str, Any]:
    """Review tier: write the diff for the user, change nothing."""
    target = cfg.to_review / f"{proposal['id']}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    head = (f"# {proposal['title']}\n\n- id: {proposal['id']}\n- source: {proposal['source']}\n"
            f"- reason: {proposal['reason']}\n- tier: review (needs your approval; nothing was changed)\n\n")
    target.write_text(head + "\n".join(readable_diff(p, o, n) for p, (o, n) in contents.items()), encoding="utf-8")
    return done("to review", f"diff written to {target}")


def process(proposal: Dict[str, Any], cfg: Settings, dry_run: bool = False) -> Dict[str, Any]:
    """Process one proposal and return its journal entry (written unless dry_run)."""
    validate(proposal)
    paths = [real_path(c["file"], cfg) for c in proposal["changes"]]
    tier = tier_of_all(paths, cfg)
    files = list(dict.fromkeys(paths))

    def done(verdict: str, reason: str, **extra: Any) -> Dict[str, Any]:
        entry = {"id": proposal["id"], "title": proposal["title"], "date": journal.now(), "tier": tier,
                 "files": [str(f) for f in files], "hash_before": extra.get("before", {}), "hash_after": extra.get("after", {}),
                 "verdict": verdict, "reason": reason}
        if not dry_run:
            journal.write(cfg, entry)
        return entry

    if tier == "manual":
        return done("refused", "manual tier: at least one file is reserved for you")
    try:
        contents = compute(proposal, cfg)
    except ValueError as err:
        return done("refused", str(err))
    if (cfg.archives / proposal["id"]).exists() or (cfg.to_review / f"{proposal['id']}.md").exists():
        return done("refused", "id already used (archive or review file exists)")
    problems = [e for p, (o, n) in contents.items() for e in verify.check_text(p, o or "", n, cfg.forbidden_in_markdown)]
    if dry_run:
        will = "would go to review" if tier == "review" else "would be applied"
        return done("dry run", f"DRY RUN, nothing written ({will}). " + (f"checks failed: {'; '.join(problems)}" if problems else "text checks passed"))
    if tier == "review":
        return _to_review(proposal, cfg, contents, done)
    verdict, reason, manifest = _apply_auto(proposal, cfg, contents)
    return done(verdict, reason, before={i["path"]: i["sha_before"] for i in manifest["files"]},
                after={i["path"]: i["sha_after"] for i in manifest["files"]})
