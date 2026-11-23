#!/usr/bin/env python3
"""Make routing.json real inside Claude Code: `model:` fields and wrapper agents. Python stdlib only.

  route_sync.py status          each agent, its target model, and whether the installed files match
  route_sync.py sync            write what routing.json says (idempotent, takes a backup of the first original)
  route_sync.py sync --undo     put every `model:` field back and remove the wrappers and the routing skill

Entries of `agents` in ~/.carlo-brain/config.d/routing.json:
- `claude:<tier>` (sonnet, opus, haiku, inherit or a full model id): the `model:` line of
  <claude>/agents/<name>.md is set. Only that line changes; the original value is remembered for undo.
- `openrouter:<model id>`: a wrapper agent <name>-routed.md is generated (tools: Bash only). It sends the task,
  with the role prompt of <name>.md, to route.py. The original agent is left as it is.
- `claude` or no entry: nothing is touched.
Only agents named in routing.json are ever written. <claude> is $CARLO_CLAUDE_DIR or ~/.claude.
State (manifest, backups, role prompts): ~/.carlo-brain/state/route-sync/.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import route  # noqa: E402

MARKER = "<!-- carlo-brain:route-sync -->"
NAME_RE = re.compile(r"[A-Za-z0-9][\w.\-]*")
SKILL = "carlo-routing"
MAX_ROLE = 6000


def claude_dir() -> Path:
    return Path(os.environ.get("CARLO_CLAUDE_DIR") or Path.home() / ".claude")


def state_dir() -> Path:
    return route.oa.brain_home() / "state" / "route-sync"


def agents_dir() -> Path:
    return claude_dir() / "agents"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- frontmatter (pure)

def split_front(text: str) -> Optional[Tuple[List[str], str]]:
    """(frontmatter lines, body) of a file that starts with `---`, else None."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index], "\n".join(lines[index + 1:])
    return None


def get_field(text: str, field: str) -> Optional[str]:
    parts = split_front(text)
    for line in parts[0] if parts else []:
        match = re.match(rf"{field}:\s*(.*?)\s*$", line)
        if match:
            return match.group(1).strip("\"'")
    return None


def with_model(text: str, model: Optional[str]) -> str:
    """Copy of the agent file with its `model:` line set (or removed when model is None)."""
    parts = split_front(text)
    if parts is None:
        raise ValueError("no frontmatter")
    front, body = parts
    position = next((i for i, line in enumerate(front) if re.match(r"model:", line)), len(front))
    kept = [line for line in front if not re.match(r"model:", line)]
    if model is not None:
        kept.insert(min(position, len(kept)), f"model: {model}")
    head = "---\n" + "\n".join(kept) + "\n---\n"
    return head + body


# ---------------------------------------------------------------- plan

def wrapper_name(name: str) -> str:
    return f"{name}-routed"


def role_prompt(name: str) -> Tuple[str, str]:
    """(description, role text) of the original agent, or generic ones when it is not installed."""
    path = agents_dir() / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return f"the {name} role", f"You are the {name} agent. Do the task you are given and answer in plain text."
    parts = split_front(text)
    body = (parts[1] if parts else text).strip()
    return (get_field(text, "description") or f"the {name} role")[:300], body[:MAX_ROLE]


def render_wrapper(name: str, target: str, description: str, role_file: Path) -> str:
    model = target.split(":", 1)[1]
    script = route.oa.brain_home() / "connectors" / "openrouter" / "route.py"
    desc = (f"Routed copy of {name}: same role, answered by {model} through route.py (text in, text out, no file or tool "
            f"access). Prefer it over {name} for bulk or cheap text work. The text you pass it leaves the machine; never "
            f"pass secrets, mail or chat content the user did not ask you to send. Original: {description}")
    return (f"---\nname: {wrapper_name(name)}\ndescription: {json.dumps(desc, ensure_ascii=False)}\ntools: Bash\nmodel: haiku\n---\n"
            f"{MARKER}\n"
            f"Write the task, with all the text it needs, to a temporary file (mktemp), then run\n\n"
            f"`python3 -I {script} ask --agent {name} --system-file {role_file} < <file>`\n\n"
            f"and return the answer unchanged. If the command prints a `route:` line on stderr, tell the caller in one "
            f"line which model answered. Do nothing else: no other tool, no file edits.\n")


def plan(config: Dict[str, object]) -> List[Dict[str, object]]:
    """One row per agent entry: name, target, mode (tier, wrapper, claude, invalid), expected content."""
    rows: List[Dict[str, object]] = []
    agents = config.get("agents") or {}
    for name, target in sorted(agents.items() if isinstance(agents, dict) else []):
        row: Dict[str, object] = {"name": name, "target": target, "mode": "invalid", "tier": None}
        if not NAME_RE.fullmatch(str(name)) or not route.valid_target(target):
            rows.append(row)
        elif str(target).startswith("openrouter:"):
            rows.append({**row, "mode": "wrapper"})
        elif str(target).startswith("claude:"):
            rows.append({**row, "mode": "tier", "tier": str(target).split(":", 1)[1]})
        else:
            rows.append({**row, "mode": "claude"})
    return rows


def routed_kinds(config: Dict[str, object]) -> List[str]:
    kinds = config.get("kinds") or {}
    return sorted(k for k, v in kinds.items() if isinstance(kinds, dict) and str(v).startswith("openrouter:"))


def render_skill(config: Dict[str, object], wrappers: List[str]) -> str:
    kinds = routed_kinds(config)
    kind_text = ", ".join(kinds) or "none listed"
    agent_text = ", ".join(wrappers) or "none"
    return (f"---\nname: {SKILL}\ndescription: \"Use before delegating bulk or cheap text work (task kinds: {kind_text}) or when "
            f"a routed agent exists for the role: picks the routed agent so the task runs on the model the user chose in routing.json.\"\n"
            f"---\n{MARKER}\n# Model routing\n\n"
            f"The user routes some work to other models (`carlo route status` shows how). When you delegate:\n\n"
            f"- Routed agents (`*-routed`): {agent_text}. Prefer one over its original when the task is text in, text out "
            f"(summary, classification, translation, extraction, a first draft). It has no file or tool access, so give it all the text.\n"
            f"- Task kinds sent to another model: {kind_text}. If no routed agent fits, run "
            f"`route.py ask --kind <kind>` yourself through Bash.\n"
            f"- Keep the original agent for anything that needs files, tools, the web or judgement over the user's data.\n"
            f"- The text goes to a third-party provider: never include secrets, mail or chat content the user did not ask you to send.\n")


# ---------------------------------------------------------------- state and files

def manifest_path() -> Path:
    return state_dir() / "manifest.json"


def load_manifest() -> Dict[str, object]:
    try:
        data = json.loads(manifest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    base = {"models": {}, "wrappers": [], "skill": False}
    return {**base, **data} if isinstance(data, dict) else base


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def expected_wrapper(row: Dict[str, object]) -> Tuple[str, str]:
    """(wrapper text, role text) for a wrapper row."""
    name = str(row["name"])
    description, role = role_prompt(name)
    return render_wrapper(name, str(row["target"]), description, state_dir() / "roles" / f"{name}.txt"), role


def row_state(row: Dict[str, object]) -> Tuple[bool, str]:
    """(synced, detail) for one plan row, from the files on disk."""
    name, mode = str(row["name"]), row["mode"]
    if mode == "invalid":
        return False, "invalid entry in routing.json (ignored)"
    if mode == "claude":
        return True, "no change (plain Claude)"
    if mode == "tier":
        text = read(agents_dir() / f"{name}.md")
        if text is None:
            return False, "agent not installed, nothing to set"
        current = get_field(text, "model")
        return current == row["tier"], f"model: {current or 'unset'}"
    wrapper, role = expected_wrapper(row)
    on_disk = read(agents_dir() / f"{wrapper_name(name)}.md")
    if on_disk is None:
        return False, "wrapper missing"
    ok = on_disk == wrapper and read(state_dir() / "roles" / f"{name}.txt") == role
    return ok, "wrapper up to date" if ok else "wrapper differs from routing.json"


def stale(config: Dict[str, object]) -> List[str]:
    """Things a previous sync wrote that routing.json no longer asks for."""
    manifest, rows = load_manifest(), plan(config)
    tiers = {r["name"] for r in rows if r["mode"] == "tier"}
    wrappers = {wrapper_name(str(r["name"])) for r in rows if r["mode"] == "wrapper"}
    out = [f"{n} (model)" for n in manifest["models"] if n not in tiers]
    return out + [f"{w} (wrapper)" for w in manifest["wrappers"] if w not in wrappers]


# ---------------------------------------------------------------- sync and undo

def apply_tier(name: str, tier: str, manifest: Dict[str, object], out: Callable[[str], None]) -> None:
    path = agents_dir() / f"{name}.md"
    text = read(path)
    if text is None:
        out(f"skipped {name}: {path.name} is not installed")
        return
    if split_front(text) is None:
        out(f"skipped {name}: no frontmatter in {path.name}")
        return
    models: Dict[str, object] = manifest["models"]  # type: ignore[assignment]
    if name not in models:
        backup = state_dir() / "backup" / f"{name}.md"
        if not backup.exists():
            write_text(backup, text)
        models[name] = {"original": get_field(text, "model")}
    if get_field(text, "model") == tier:
        out(f"unchanged {name}: model {tier}")
        return
    write_text(path, with_model(text, tier))
    out(f"set {name}: model {tier}")


def revert_model(name: str, manifest: Dict[str, object], out: Callable[[str], None]) -> None:
    models: Dict[str, object] = manifest["models"]  # type: ignore[assignment]
    entry = models.pop(name, None)
    path = agents_dir() / f"{name}.md"
    text = read(path)
    if entry is None or text is None or split_front(text) is None:
        return
    original = entry.get("original") if isinstance(entry, dict) else None
    write_text(path, with_model(text, original))
    out(f"restored {name}: model {original or 'unset (removed)'}")


def remove_wrapper(file_stem: str, out: Callable[[str], None]) -> None:
    path = agents_dir() / f"{file_stem}.md"
    text = read(path)
    if text is not None and MARKER in text:
        path.unlink()
        out(f"removed {file_stem}")
    elif text is not None:
        out(f"kept {file_stem}: no longer ours (edited or replaced)")
    role = state_dir() / "roles" / f"{file_stem[:-len('-routed')]}.txt"
    if role.exists():
        role.unlink()


def sync(out: Callable[[str], None] = print) -> int:
    config = route.load_config()
    rows, manifest = plan(config), load_manifest()
    manifest = {**manifest, "models": dict(manifest["models"]), "wrappers": list(manifest["wrappers"])}  # type: ignore[call-overload]
    for row in rows:
        if row["mode"] == "invalid":
            out(f"ignored {row['name']}: invalid entry {row['target']!r}")
    tiers = {str(r["name"]): str(r["tier"]) for r in rows if r["mode"] == "tier"}
    wanted = [r for r in rows if r["mode"] == "wrapper"]
    for name in [n for n in manifest["models"] if n not in tiers]:  # type: ignore[attr-defined]
        revert_model(name, manifest, out)
    for name, tier in tiers.items():
        apply_tier(name, tier, manifest, out)
    names: List[str] = []
    for row in wanted:
        wrapper, role = expected_wrapper(row)
        stem = wrapper_name(str(row["name"]))
        path = agents_dir() / f"{stem}.md"
        existing = read(path)
        if existing is not None and MARKER not in existing:
            out(f"skipped {stem}: a file of yours with that name exists")
            continue
        names.append(stem)
        if existing == wrapper and read(state_dir() / "roles" / f"{row['name']}.txt") == role:
            out(f"unchanged {stem}")
            continue
        write_text(state_dir() / "roles" / f"{row['name']}.txt", role)
        write_text(path, wrapper)
        out(f"wrote {stem} ({row['target']})")
    for stem in [w for w in manifest["wrappers"] if w not in names]:  # type: ignore[attr-defined]
        remove_wrapper(stem, out)
    manifest["wrappers"] = names
    manifest["skill"] = sync_skill(config, names, out)
    write_text(manifest_path(), json.dumps(manifest, indent=1, sort_keys=True))
    return 0


def sync_skill(config: Dict[str, object], wrappers: List[str], out: Callable[[str], None]) -> bool:
    path = claude_dir() / "skills" / SKILL / "SKILL.md"
    existing = read(path)
    if existing is not None and MARKER not in existing:
        out(f"skipped skill {SKILL}: a skill of yours with that name exists")
        return False
    if not wrappers and not routed_kinds(config):
        if existing is not None:
            path.unlink()
            _prune(path.parent)
            out(f"removed skill {SKILL}")
        return False
    text = render_skill(config, wrappers)
    if existing != text:
        write_text(path, text)
        out(f"wrote skill {SKILL}")
    return True


def _prune(folder: Path) -> None:
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()


def undo(out: Callable[[str], None] = print) -> int:
    manifest = load_manifest()
    for name in list(manifest["models"]):  # type: ignore[call-overload]
        revert_model(name, manifest, out)
    for stem in manifest["wrappers"]:  # type: ignore[attr-defined]
        remove_wrapper(str(stem), out)
    skill = claude_dir() / "skills" / SKILL / "SKILL.md"
    text = read(skill)
    if text is not None and MARKER in text:
        skill.unlink()
        _prune(skill.parent)
        out(f"removed skill {SKILL}")
    write_text(manifest_path(), json.dumps({"models": {}, "wrappers": [], "skill": False}, indent=1))
    out(f"undone; first originals stay in {state_dir() / 'backup'}")
    return 0


# ---------------------------------------------------------------- status and doctor

def status_rows(config: Optional[Dict[str, object]] = None) -> List[Tuple[str, str, bool, str]]:
    """(agent, target, synced, detail) per routed agent, plus stale leftovers."""
    config = config if config is not None else route.load_config()
    rows = []
    for row in plan(config):
        synced, detail = row_state(row)
        rows.append((str(row["name"]), str(row["target"]), synced, detail))
    for item in stale(config):
        rows.append((item, "(not in routing.json)", False, "left by a previous sync, run `carlo route sync`"))
    return rows


def check() -> List[Tuple[str, str]]:
    """Doctor rows (level, text). Silent when routing.json has no agent entry and nothing was synced."""
    config = route.load_config()
    rows = status_rows(config)
    if not rows:
        return []
    bad = [r for r in rows if not r[2]]
    if not bad:
        return [("ok", f"routing: {len(rows)} agent(s) match routing.json")]
    return [("warn", f"routing: {name} ({target}) does not match: {detail}; run `carlo route sync`") for name, target, _, detail in bad]


def run_cli(argv: List[str], out: Callable[[str], None] = print) -> int:
    action = argv[0] if argv else "status"
    if action == "status":
        rows = status_rows()
        if not rows:
            out("no agent is routed (routing.json has no `agents` entry)")
        for name, target, synced, detail in rows:
            out(f"{name:<22} {target:<34} {'synced' if synced else 'NOT synced':<11} {detail}")
        return 0
    try:
        if action == "sync":
            return undo(out) if "--undo" in argv else sync(out)
    except (OSError, ValueError) as err:
        out(f"route sync failed: {err}")
        return 1
    out("usage: route status | route sync [--undo]")
    return 2


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
