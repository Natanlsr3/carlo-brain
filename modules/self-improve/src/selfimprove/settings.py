"""Paths and settings of the self-improve module. Everything derives from `home` so tests use a temp dir."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Tiers. The CODE classifies a path, never the model. Most restrictive wins: manual > review > auto.
# A path that matches nothing is "review". "{VAULT}" and "~" are expanded. "*" = one path segment, "**" = any depth.
DEFAULT_TIERS: Dict[str, List[str]] = {
    "auto": [
        "{VAULT}/00_System/memory/**",
        "{VAULT}/00_System/skills/**",
        "~/.claude/agents/*.md",
        "~/.claude/skills/**",
        "~/.carlo-brain/config.d/*.json",
    ],
    "review": [
        "{VAULT}/00_System/*.md",
        "~/.claude/CLAUDE.md",
        "~/.claude/settings.json",
        "~/.claude/settings.local.json",
        "**/*mail*",
        "**/*whatsapp*",
        "**/*slack*",
        "**/*telegram*",
        "**/*linkedin*",
        "**/*send*",
    ],
}

# Not configurable on purpose: a config file (which an automated proposal could try to edit) can never
# lower these to a weaker tier.
HARD_MANUAL: List[str] = [
    "~/.carlo-brain/keys/**",
    "~/.carlo-brain/security/**",
    "~/.carlo-brain/self-improve/**",
    "~/.carlo-brain/config.json",
    "~/.carlo-brain/config.d/self-improve*",
    "~/.carlo-brain/config.d/telegram*",
    "~/.carlo-brain/config.d/*vault_mcp*",
    "~/.ssh/**",
    "~/.claude/.credentials*",
    "~/.claude/hooks/**",
]
# File names containing any of these are always manual.
SENSITIVE_NAMES: List[str] = ["secret", "token", "password", ".env", "key", "credential"]
# Note: the bench cases live under ~/.carlo-brain/self-improve/, which is manual. The bench is the judge of
# every automatic change, so an automatic change must never be able to edit the judge.


@dataclass(frozen=True)
class Settings:
    """Everything a run needs. `home` is the user's home directory (tests: tmp_path)."""

    home: Path = field(default_factory=Path.home)
    brain: Optional[Path] = None
    vault_path: Optional[Path] = None
    tiers: Dict[str, List[str]] = field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_TIERS.items()})
    forbidden_in_markdown: List[str] = field(default_factory=list)
    test_timeout: int = 60

    @property
    def brain_dir(self) -> Path:
        return self.brain or (self.home / ".carlo-brain")

    @property
    def state(self) -> Path:
        return self.brain_dir / "state" / "self-improve"

    @property
    def archives(self) -> Path:
        return self.state / "archives"

    @property
    def improvement(self) -> Path:
        """Where reviewable output lives: the vault if there is one, else the state folder."""
        return (self.vault_path / "00_System" / "improvement") if self.vault_path else self.state

    @property
    def to_review(self) -> Path:
        return self.improvement / "to_review"

    @property
    def proposals(self) -> Path:
        return self.improvement / "proposals"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load(home: Optional[Path] = None) -> Settings:
    """Settings from the environment and ~/.carlo-brain/config.d/self-improve.json (missing = defaults)."""
    home = home or Path.home()
    brain = Path(os.environ["CARLO_BRAIN_HOME"]).expanduser() if os.environ.get("CARLO_BRAIN_HOME") else home / ".carlo-brain"
    core = _read_json(brain / "config.json")
    vault = core.get("vault")
    own = _read_json(brain / "config.d" / "self-improve.json")
    tiers = {k: list(v) for k, v in DEFAULT_TIERS.items()}
    for tier in ("auto", "review"):
        extra = own.get("tiers", {}).get(tier)
        if isinstance(extra, list) and all(isinstance(x, str) for x in extra):
            tiers[tier] = extra
    verify = own.get("verify", {}) if isinstance(own.get("verify"), dict) else {}
    forbidden = verify.get("forbidden_in_markdown", [])
    timeout = verify.get("test_timeout_s", 60)
    return Settings(
        home=home,
        brain=brain,
        vault_path=Path(str(vault)).expanduser() if vault else None,
        tiers=tiers,
        forbidden_in_markdown=[x for x in forbidden if isinstance(x, str)] if isinstance(forbidden, list) else [],
        test_timeout=timeout if isinstance(timeout, int) and 5 <= timeout <= 600 else 60,
    )
