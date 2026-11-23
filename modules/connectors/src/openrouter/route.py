#!/usr/bin/env python3
"""Route a bulk or cheap task to the model configured for it, with a fallback to Claude. Python stdlib only.

  route.py resolve [--agent NAME] [--kind KIND]          print the target ("claude", "claude:<tier>" or "openrouter:<model>")
  route.py ask [--agent NAME] [--kind KIND] [--system TEXT | --system-file PATH] [PROMPT]
                                                         run the task on the target; the answer goes to stdout

Config: ~/.carlo-brain/config.d/routing.json (a missing file means "everything on Claude"):

  {"default": "claude",
   "agents": {"researcher": "openrouter:<model id>"},
   "kinds": {"summarise": "openrouter:<model id>", "classify": "openrouter:<model id>", "translate": "openrouter:<model id>"},
   "fallback": "claude", "max_tokens": 1024, "base_url": "https://openrouter.ai/api/v1"}

Lookup order: agent, then kind, then default. A target is `claude`, `claude:<tier>` (sonnet, opus, haiku,
inherit or a full model id; `ask` runs `claude -p --model <tier>`) or `openrouter:<model id>`.
`carlo route sync` turns these entries into `model:` fields and `<name>-routed` wrapper agents (route_sync.py).
On any error of the other provider (no key, HTTP error, bad answer) the same prompt is run on Claude
with `claude -p` in a clean environment (no API key variables, your login is used), unless "fallback" is "none".
When the target is `claude`, `ask` runs `claude -p` too, so a caller can use one command for every route.
The key is read from a file by openrouter_ask (never printed, never an argument). What you send to a
non-Claude target leaves your machine: only route text you would paste into that provider's website.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openrouter_ask as oa  # noqa: E402

KEY_LIKE = re.compile(r"(API_KEY|_KEY$|SECRET|PASSWORD|PASSWD)", re.I)
CLAUDE = "claude"
DEFAULTS: Dict[str, object] = {"default": CLAUDE, "agents": {}, "kinds": {}, "fallback": CLAUDE, "max_tokens": 1024,
                               "base_url": oa.DEFAULT_BASE_URL}


def config_path() -> Path:
    return oa.brain_home() / "config.d" / "routing.json"


def load_config(path: Optional[Path] = None) -> Dict[str, object]:
    """Routing config merged over the defaults. A missing or broken file gives the defaults (all Claude)."""
    try:
        data = json.loads((path or config_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULTS)
    return {**DEFAULTS, **data} if isinstance(data, dict) else dict(DEFAULTS)


TIER_RE = re.compile(r"claude:(sonnet|opus|haiku|inherit|claude-[\w.\-]+)")


def valid_target(target: object) -> bool:
    return target == CLAUDE or (isinstance(target, str) and re.fullmatch(r"openrouter:\S+|" + TIER_RE.pattern, target) is not None)


def claude_tier(target: str) -> str:
    """Model flag for a `claude:<tier>` target, "" for plain claude or `inherit`."""
    tier = target.split(":", 1)[1] if target.startswith("claude:") else ""
    return "" if tier == "inherit" else tier


def resolve(config: Dict[str, object], agent: str = "", kind: str = "") -> str:
    """Target for this agent or kind. An invalid entry is ignored, never guessed."""
    agents, kinds = config.get("agents") or {}, config.get("kinds") or {}
    for table, name in ((agents, agent), (kinds, kind)):
        target = table.get(name) if isinstance(table, dict) and name else None
        if valid_target(target):
            return str(target)
    default = config.get("default")
    return str(default) if valid_target(default) else CLAUDE


def clean_env() -> Dict[str, str]:
    """Environment without key-like variables, so `claude -p` uses the user's login."""
    return {k: v for k, v in os.environ.items() if not KEY_LIKE.search(k) or k == "CLAUDE_CODE_OAUTH_TOKEN"}


def run_claude(prompt: str, system: str = "", run: Optional[Callable] = None, timeout: int = 300, model: str = "") -> str:
    """Answer with `claude -p`. Raises RuntimeError with a short reason."""
    run = run or subprocess.run
    command: List[str] = (["claude", "-p"] + (["--model", model] if model else [])
                          + (["--append-system-prompt", system] if system else []))
    try:
        res = run(command, input=prompt, capture_output=True, text=True, timeout=timeout, env=clean_env())
    except (OSError, subprocess.TimeoutExpired) as err:
        raise RuntimeError(f"claude failed ({type(err).__name__})") from err
    if res.returncode != 0 or not (res.stdout or "").strip():
        raise RuntimeError(f"claude exited {res.returncode}")
    return str(res.stdout).strip()


def route(prompt: str, config: Dict[str, object], agent: str = "", kind: str = "", system: str = "",
          ask: Optional[Callable] = None, run: Optional[Callable] = None) -> Dict[str, str]:
    """Run the task. Returns {"answer", "target", "note"}; note says why Claude answered instead of the target."""
    target = resolve(config, agent, kind)
    if target == CLAUDE or target.startswith("claude:"):
        return {"answer": run_claude(prompt, system, run, model=claude_tier(target)), "target": target, "note": ""}
    try:
        key = oa.read_key()
        answer = (ask or oa.ask)(target.split(":", 1)[1], prompt, key, str(config.get("base_url") or oa.DEFAULT_BASE_URL), system,
                     int(config.get("max_tokens") or 1024))
        return {"answer": answer, "target": target, "note": ""}
    except (RuntimeError, SystemExit, ValueError) as err:
        reason = str(err) if not isinstance(err, SystemExit) else str(err.code)
        if config.get("fallback") == "none":
            raise RuntimeError(f"{target} failed: {reason}") from err
        return {"answer": run_claude(prompt, system, run), "target": CLAUDE, "note": f"{target} failed ({reason}), answered by claude"}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Route a task to the configured model, fallback to Claude.")
    parser.add_argument("action", choices=["resolve", "ask"])
    parser.add_argument("prompt", nargs="?")
    parser.add_argument("--agent", default="")
    parser.add_argument("--kind", default="")
    parser.add_argument("--system", default="")
    parser.add_argument("--system-file", default="", help="read the system text from a file (long role prompts)")
    args = parser.parse_intermixed_args(argv)
    config = load_config()
    if args.action == "resolve":
        print(resolve(config, args.agent, args.kind))
        return 0
    prompt = args.prompt if args.prompt is not None else sys.stdin.read()
    if not prompt.strip():
        print("empty prompt", file=sys.stderr)
        return 2
    system = args.system
    if args.system_file:
        try:
            system = Path(args.system_file).read_text(encoding="utf-8")
        except OSError as err:
            print(f"route: cannot read --system-file ({err.__class__.__name__})", file=sys.stderr)
            return 2
    try:
        result = route(prompt, config, args.agent, args.kind, system)
    except RuntimeError as err:
        print(f"route: {err}", file=sys.stderr)
        return 1
    if result["note"]:
        print(f"route: {result['note']}", file=sys.stderr)
    print(result["answer"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
