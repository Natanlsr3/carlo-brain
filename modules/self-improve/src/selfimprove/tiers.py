"""Classify a path as auto, review or manual. The table decides, never the model."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, List, Union

from .settings import HARD_MANUAL, SENSITIVE_NAMES, Settings

ORDER = {"auto": 0, "review": 1, "manual": 2}
UNKNOWN = "review"


def glob_to_regex(glob: str) -> "re.Pattern[str]":
    """Anchored regex for a glob: `**` any depth, `*` inside one segment, `?` one character."""
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif glob.startswith("**", i):
            out += ".*"
            i += 2
        elif glob[i] == "*":
            out += "[^/]*"
            i += 1
        elif glob[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(glob[i])
            i += 1
    return re.compile(out + r"\Z")


def real_path(path: Union[str, Path], cfg: Settings) -> Path:
    """Expand ~ to cfg.home, make absolute and resolve symlinks (a link cannot hide its real location)."""
    text = str(path)
    if text == "~" or text.startswith("~/"):
        text = str(cfg.home) + text[1:]
    return Path(os.path.realpath(text))


def _expand(pattern: str, cfg: Settings) -> str:
    """Pattern with ~ and {VAULT} expanded; "" when it needs a vault that is not configured."""
    if "{VAULT}" in pattern:
        if cfg.vault_path is None:
            return ""
        pattern = pattern.replace("{VAULT}", str(os.path.realpath(cfg.vault_path)))
    if pattern.startswith("~"):
        pattern = str(os.path.realpath(cfg.home)) + pattern[1:]
    return pattern


def _matches(path: str, patterns: Iterable[str], cfg: Settings) -> bool:
    for pattern in patterns:
        expanded = _expand(pattern, cfg)
        if expanded and glob_to_regex(expanded).match(path):
            return True
    return False


def tier_of(path: Union[str, Path], cfg: Settings) -> str:
    """Tier of one path: the most restrictive rule wins, a sensitive file name is always manual."""
    target = str(real_path(path, cfg))
    found: List[str] = []
    if _matches(target, HARD_MANUAL, cfg):
        found.append("manual")
    if any(s in Path(target).name.lower() for s in SENSITIVE_NAMES):
        found.append("manual")
    for tier in ("review", "auto"):
        if _matches(target, cfg.tiers.get(tier, []), cfg):
            found.append(tier)
    return max(found, key=ORDER.__getitem__) if found else UNKNOWN


def tier_of_all(paths: Iterable[Union[str, Path]], cfg: Settings) -> str:
    """Tier of a batch: the most restrictive, applied to the whole batch."""
    tiers = [tier_of(p, cfg) for p in paths]
    return max(tiers, key=ORDER.__getitem__) if tiers else UNKNOWN

