#!/usr/bin/env python3
"""Connect the brain to OpenAI Codex CLI or Google Gemini CLI. Standard library only.

  agents_connect.py <codex|gemini> [--remove | --status] [--no-hooks] [--no-agents] [--mcp] [--inline]
  agents_connect.py remove-all        (used by `carlo remove other-agents`)
  agents_connect.py refresh           regenerate the instruction blocks

Also reachable as `carlo connect codex|gemini`; `carlo doctor` calls check(). Everything written is tagged and
backed up (`<file>.bak-carlo-<time>`), and `--remove` takes out only what this script added. Facts used (checked
against the vendors' docs on 2026-11-23, URLs in the module README): Codex reads `$CODEX_HOME/AGENTS.md` (default
~/.codex) with no import syntax, hooks in `$CODEX_HOME/hooks.json`, skills in `~/.agents/skills`; Gemini reads
`~/.gemini/GEMINI.md` with `@file` imports, hooks in `~/.gemini/settings.json`, commands in `~/.gemini/commands`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _lib in (os.environ.get("CARLO_LIB"), str(Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain") / "lib")):
    if _lib:
        sys.path.insert(0, _lib)
import carlo_config as cfg  # noqa: E402
import carlo_settings as settings_io  # noqa: E402
import context  # noqa: E402

MODULE = "other-agents"
MANAGED = "carlo-brain:managed"
TOOLS = ("codex", "gemini")
Row = Tuple[str, str]  # level (ok / warn / fail), text

SECRET_TOOLS = {"codex": "Bash|apply_patch", "gemini": "run_shell_command|read_file|read_many_files|glob|grep_search|list_directory|write_file|replace"}
SEND_TOOLS = {"codex": "Bash|mcp__.*", "gemini": "run_shell_command"}
GUARDS = (("block_secret_reads.py", SECRET_TOOLS, ""), ("send_guard.py", SEND_TOOLS, " tool"))


def codex_dir() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def gemini_dir() -> Path:
    return Path.home() / ".gemini"


def tool_dir(tool: str) -> Path:
    return codex_dir() if tool == "codex" else gemini_dir()


def instructions_path(tool: str) -> Path:
    return tool_dir(tool) / ("AGENTS.md" if tool == "codex" else "GEMINI.md")


def hooks_path(tool: str) -> Path:
    return tool_dir(tool) / ("hooks.json" if tool == "codex" else "settings.json")


def exports_dir(tool: str) -> Path:
    return Path.home() / ".agents" / "skills" if tool == "codex" else gemini_dir() / "commands" / "carlo"


def hook_tag(tool: str) -> str:
    return f"{MODULE}-{tool}"


def code_dir(name: str = MODULE) -> Path:
    return cfg.home() / name


def python_cmd() -> str:
    return shlex.quote(str(cfg.get("python") or sys.executable or "python3"))


# ---------------------------------------------------------------- hooks

def hook_entries(tool: str) -> List[dict]:
    """Hook definitions for a tool. Codex timeouts are seconds, Gemini milliseconds (both 10 s)."""
    here, py = shlex.quote(str(code_dir())), python_cmd()
    timeout = 10 if tool == "codex" else 10000
    event = "PreToolUse" if tool == "codex" else "BeforeTool"
    entries = [{"event": "SessionStart", "command": f"{py} -I {here}/session_start.py {tool}", "timeout": timeout}]
    if (code_dir("security") / "block_secret_reads.py").is_file():
        for script, matchers, extra in GUARDS:
            entries.append({"event": event, "matcher": matchers[tool], "timeout": timeout,
                            "command": f"{py} -I {here}/guard_adapter.py {tool} {script}{extra}"})
    return entries


def write_hooks(tool: str) -> Tuple[int, Optional[Path]]:
    """Merge our hooks into the tool's JSON file. Returns (hook count, backup path)."""
    path = hooks_path(tool)
    current = settings_io.load_settings(path)  # a broken file aborts before anything is touched
    entries = hook_entries(tool)
    backup = settings_io.write_settings(settings_io.add_module_hooks(current, hook_tag(tool), entries), path)
    return len(entries), backup


def drop_hooks(tool: str) -> bool:
    path = hooks_path(tool)
    if not path.exists():
        return False
    current = settings_io.load_settings(path)
    if not settings_io.installed_commands(current, hook_tag(tool)):
        return False
    settings_io.write_settings(settings_io.remove_module_hooks(current, hook_tag(tool)), path)
    return True


def hook_count(tool: str) -> int:
    try:
        return len(settings_io.installed_commands(settings_io.load_settings(hooks_path(tool)), hook_tag(tool)))
    except settings_io.SettingsError:
        return 0


# ---------------------------------------------------------------- instruction block

def has_block(tool: str) -> bool:
    path = instructions_path(tool)
    return path.is_file() and settings_io.BEGIN in path.read_text(encoding="utf-8", errors="replace")


def write_block(tool: str, inline: bool = False) -> Tuple[bool, bool]:
    """Install or refresh the managed block. Returns (file was created now, content changed)."""
    path = instructions_path(tool)
    before = path.read_text(encoding="utf-8") if path.exists() else None
    block = context.instruction_block(imports=(tool == "gemini" and not inline))
    created = settings_io.install_block(block, path)
    return created, (path.read_text(encoding="utf-8") != before)


def refresh_all() -> List[Tuple[str, bool]]:
    """Regenerate the block of every connected tool whose copy can go stale (Codex, or Gemini with --inline)."""
    done = []
    for tool in TOOLS:
        state = cfg.get(f"other_agents.{tool}")
        if state and has_block(tool):
            done.append((tool, write_block(tool, bool(state.get("inline")))[1]))
    return done


# ---------------------------------------------------------------- exported prompts (agents and skills)

def parse_prompt(text: str) -> Tuple[dict, str]:
    """(front matter name/description, body) of an agent or skill Markdown file."""
    match = re.match(r"---\n(.*?)\n---\n?(.*)\Z", text, re.S)
    if not match:
        return {}, text
    meta = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in ("name", "description"):
            value = value.strip()
            meta[key.strip()] = json.loads(value) if value.startswith('"') and value.endswith('"') else value
    return meta, match.group(2).lstrip("\n")


def prompt_sources() -> List[Tuple[str, dict, str, Optional[Path]]]:
    """(name, meta, body, skill folder or None) for the installed agents and skills."""
    base, found = code_dir("agents-skills"), []
    for path in sorted((base / "agents").glob("*.md")) if (base / "agents").is_dir() else []:
        meta, body = parse_prompt(path.read_text(encoding="utf-8"))
        found.append((meta.get("name", path.stem), meta, body, None))
    folders = [base / "skills", cfg.home() / "core-skills"]  # module skills, then the core skills (setup)
    for path in sorted(p for folder in folders if folder.is_dir() for p in folder.glob("*/SKILL.md")):
        meta, body = parse_prompt(path.read_text(encoding="utf-8"))
        found.append((meta.get("name", path.parent.name), meta, body, path.parent))
    return found


PREFACE = ("Exported from Carlo Brain. The original was written for Claude Code: ignore tool names and model hints, "
           "and if it says to delegate to another agent, do that work yourself.")


def codex_skill_text(name: str, meta: dict, body: str) -> str:
    return (f"---\nname: carlo-{name}\ndescription: {json.dumps(meta.get('description', name))}\n---\n"
            f"<!-- {MANAGED} -->\n\n{PREFACE}\n\n{body.strip()}\n")


def gemini_command_text(name: str, meta: dict, body: str) -> str:
    """TOML command. `@{` and `!{` would be injected by Gemini, so they are defused; `'''` cannot appear in a literal string."""
    safe = body.strip().replace("@{", "@ {").replace("!{", "! {").replace("'''", "' ' '")
    desc = json.dumps(str(meta.get("description", name))[:200])
    return f"# {MANAGED}\ndescription = {desc}\nprompt = '''\n{PREFACE}\n\n{safe}\n\nRequest: {{{{args}}}}\n'''\n"


def export_prompts(tool: str) -> List[str]:
    """Write the managed copies; a file or folder of the same name that is not ours is never touched."""
    target, names = exports_dir(tool), []
    for name, meta, body, folder in prompt_sources():
        if tool == "codex":
            names += _export_codex(target / f"carlo-{name}", name, meta, body, folder)
        else:
            file = target / f"{name}.toml"
            if file.exists() and MANAGED not in file.read_text(encoding="utf-8", errors="replace"):
                continue
            target.mkdir(parents=True, exist_ok=True)
            file.write_text(gemini_command_text(name, meta, body), encoding="utf-8")
            names.append(name)
    return names


def _export_codex(dest: Path, name: str, meta: dict, body: str, folder: Optional[Path]) -> List[str]:
    if dest.exists() and not (dest / ".carlo-managed").exists():
        return []
    if folder is not None:
        shutil.copytree(folder, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("SKILL.md", "__pycache__"))
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "SKILL.md").write_text(codex_skill_text(name, meta, body), encoding="utf-8")
    (dest / ".carlo-managed").write_text("exported by carlo-brain, removed by `carlo connect --remove`\n", encoding="utf-8")
    return [name]


def drop_exports(tool: str) -> int:
    """Remove only what carries our marker."""
    target, removed = exports_dir(tool), 0
    if not target.is_dir():
        return 0
    for item in sorted(target.iterdir()):
        if tool == "codex" and item.is_dir() and (item / ".carlo-managed").exists():
            shutil.rmtree(item)
            removed += 1
        elif tool == "gemini" and item.suffix == ".toml" and MANAGED in item.read_text(encoding="utf-8", errors="replace"):
            item.unlink()
            removed += 1
    if tool == "gemini" and target.is_dir() and not any(target.iterdir()):
        target.rmdir()
    return removed


# ---------------------------------------------------------------- MCP (Playwright only)

def playwright_version() -> Optional[str]:
    """Version recorded by `carlo connect browser`; None when the browser connector was never set up."""
    try:
        data = json.loads((cfg.home() / "config.d" / "browser.json").read_text(encoding="utf-8"))
        return str(data.get("version") or "latest")
    except (OSError, ValueError, AttributeError):
        return None


def mcp_add_command(tool: str, version: str) -> List[str]:
    package = f"@playwright/mcp@{version}"
    if tool == "codex":
        return ["codex", "mcp", "add", "playwright", "--", "npx", package]
    return ["gemini", "mcp", "add", "-s", "user", "playwright", "npx", package]


def register_mcp(tool: str, run: Callable = subprocess.run) -> Tuple[bool, str]:
    version = playwright_version()
    if version is None:
        return False, "no browser connector configured (run `carlo connect browser` first), MCP skipped"
    if shutil.which(tool) is None:
        return False, f"{tool} not found on PATH, MCP skipped"
    try:
        listed = run([tool, "mcp", "list"], capture_output=True, text=True, timeout=60)
        if listed.returncode == 0 and "playwright" in (listed.stdout or ""):
            return True, f"playwright MCP already registered in {tool}"
        result = run(mcp_add_command(tool, version), capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{tool} mcp add failed ({exc.__class__.__name__})"
    if result.returncode != 0:
        return False, f"{tool} mcp add failed: {(result.stderr or result.stdout).strip()[:160]}"
    return True, f"registered the playwright MCP server in {tool} (it drives its own browser profile)"


def unregister_mcp(tool: str, run: Callable = subprocess.run) -> str:
    if tool == "codex":  # Codex documents `mcp add`, `list` and `login` only: we do not guess a remove command
        return "playwright MCP stays in ~/.codex/config.toml: delete its [mcp_servers.playwright] table yourself (or `codex mcp --help`)"
    try:
        result = run(["gemini", "mcp", "remove", "-s", "user", "playwright"], capture_output=True, text=True, timeout=60)
        return "playwright MCP removed from gemini" if result.returncode == 0 else "gemini mcp remove did not succeed (already gone?)"
    except (OSError, subprocess.SubprocessError):
        return "gemini not found: remove the playwright MCP server yourself (`gemini mcp remove -s user playwright`)"


# ---------------------------------------------------------------- connect / remove / status / doctor

def connect(tool: str, out: Callable[[str], None], hooks: bool = True, agents: bool = True, mcp: bool = False,
            inline: bool = False) -> int:
    if not (cfg.system_dir() and (cfg.system_dir() / "SYSTEM_PROMPT.md").is_file()):
        out("no vault found: run ./install.sh (or `carlo init`) first")
        return 1
    if hooks:
        settings_io.load_settings(hooks_path(tool))  # a broken file aborts before anything is written
    created, _ = write_block(tool, inline)
    state = {"connected_at": cfg.now_iso(), "inline": inline, "created_file": created or bool(cfg.get(f"other_agents.{tool}.created_file")),
             "hooks": 0, "exported": [], "mcp": False}
    how = "imports" if tool == "gemini" and not inline else "inline copy (capped)"
    out(f"instructions: managed block in {instructions_path(tool)} ({how})")
    if tool == "codex" and (codex_dir() / "AGENTS.override.md").is_file() and (codex_dir() / "AGENTS.override.md").stat().st_size:
        out("warning: AGENTS.override.md exists and Codex then ignores AGENTS.md; move our block there or delete the override")
    if hooks:
        state["hooks"], _ = write_hooks(tool)
        out(f"hooks: {state['hooks']} in {hooks_path(tool)} (boot context" + (", secret and send guards)" if state["hooks"] > 1 else "; install `security` for guards)"))
        if tool == "codex":
            out("codex: new hooks are skipped until you trust them once: open codex and run /hooks")
    if agents:
        state["exported"] = export_prompts(tool)
        where = "skills in ~/.agents/skills (carlo-<name>)" if tool == "codex" else "commands /carlo:<name>"
        out(f"agents: {len(state['exported'])} exported as {where}" if state["exported"] else "agents: none exported (install `agents-skills`)")
    if mcp:
        state["mcp"], note = register_mcp(tool)
        out(f"mcp: {note}")
    cfg.save_config(cfg.with_value(cfg.load_config(), f"other_agents.{tool}", state))
    if shutil.which(tool) is None:
        out(f"note: `{tool}` is not on PATH here; the files are in place for when you install it")
    return 0


def disconnect(tool: str, out: Callable[[str], None]) -> int:
    state = cfg.get(f"other_agents.{tool}") or {}
    removed = settings_io.remove_block(instructions_path(tool), delete_if_empty=bool(state.get("created_file")))
    out("instructions: block removed" if removed else "instructions: no block found")
    out("hooks: removed" if drop_hooks(tool) else "hooks: none found")
    out(f"agents: {drop_exports(tool)} exported prompt(s) removed")
    if state.get("mcp"):
        out(f"mcp: {unregister_mcp(tool)}")
    config = cfg.load_config()
    cfg.save_config({**config, "other_agents": {k: v for k, v in (config.get("other_agents") or {}).items() if k != tool}})
    return 0


def status_rows(tool: str) -> List[Row]:
    """Doctor rows for one tool, empty when it was never connected."""
    state = cfg.get(f"other_agents.{tool}")
    if not state and not has_block(tool):
        return []
    rows: List[Row] = [("ok" if has_block(tool) else "fail", f"{tool}: instruction block in {instructions_path(tool)}")]
    wanted = len(hook_entries(tool)) if state and state.get("hooks") else 0
    have = hook_count(tool)
    if wanted:
        rows.append(("ok" if have == wanted else "fail", f"{tool}: {have}/{wanted} hooks in {hooks_path(tool)}"))
    if tool == "codex" and have:
        rows.append(("ok", "codex: hooks only run once trusted in Codex (/hooks); until then the block tells the agent to run `carlo context --boot`"))
    rows.append(("ok" if shutil.which(tool) else "warn", f"{tool}: " + (shutil.which(tool) or "not found on PATH")))
    return rows


def check() -> List[Row]:
    return [row for tool in TOOLS for row in status_rows(tool)]


def run_cli(argv: List[str], out: Callable[[str], None] = print) -> int:
    parser = argparse.ArgumentParser(prog="carlo connect")
    parser.add_argument("tool", choices=[*TOOLS, "remove-all", "refresh"])
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--no-hooks", action="store_true", help="instructions block only, no hooks")
    parser.add_argument("--no-agents", action="store_true", help="do not export the agents and skills")
    parser.add_argument("--mcp", action="store_true", help="also register the Playwright MCP server (needs `carlo connect browser`)")
    parser.add_argument("--inline", action="store_true", help="gemini: copy the prompt and map into the file instead of importing them")
    args = parser.parse_args(argv)
    try:
        if args.tool == "remove-all":
            return max(disconnect(tool, lambda _m: None) for tool in TOOLS)
        if args.tool == "refresh":
            refresh_all()
            return 0
        if args.status:
            rows = status_rows(args.tool)
            for level, text in rows or [("warn", f"{args.tool}: not connected (carlo connect {args.tool})")]:
                out(f"[{level}] {text}")
            return 0 if rows and all(level != "fail" for level, _ in rows) else 1
        if args.remove:
            return disconnect(args.tool, out)
        return connect(args.tool, out, hooks=not args.no_hooks, agents=not args.no_agents, mcp=args.mcp, inline=args.inline)
    except settings_io.SettingsError as exc:
        out(f"{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
