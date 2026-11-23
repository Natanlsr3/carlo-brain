"""Undo an applied proposal from its archive. Refuses if a file changed since (unless forced)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Tuple

from . import journal
from .apply import ID_PATTERN
from .settings import Settings


def undo(proposal_id: str, cfg: Settings, force: bool = False) -> Tuple[bool, str]:
    """Restore the files of `proposal_id`. Returns (success, message)."""
    if not ID_PATTERN.fullmatch(proposal_id) or ".." in proposal_id:
        return False, "invalid id"
    folder = cfg.archives / proposal_id
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, f"no usable archive for {proposal_id}"
    if manifest.get("status") != "applied":
        return False, f"nothing to undo (status: {manifest.get('status')})"
    changed = [i["path"] for i in manifest["files"] if journal.file_sha(Path(i["path"])) != i["sha_after"]]
    if changed and not force:
        return False, f"refused: changed since it was applied: {', '.join(changed)} (use --force to override)"
    for item in manifest["files"]:
        target = Path(item["path"])
        if item["archive"] is None:
            target.unlink(missing_ok=True)
        else:
            shutil.copyfile(folder / item["archive"], target)
    manifest["status"] = "undone"
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    journal.write(cfg, {
        "id": proposal_id, "title": f"undo of {proposal_id}", "date": journal.now(), "tier": "auto",
        "files": [i["path"] for i in manifest["files"]],
        "hash_before": {i["path"]: i["sha_after"] for i in manifest["files"]},
        "hash_after": {i["path"]: journal.file_sha(Path(i["path"])) for i in manifest["files"]},
        "verdict": "restored", "reason": "manual undo" + (" (forced)" if force else "")})
    return True, "restored from the archive"
