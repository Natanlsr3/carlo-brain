"""`carlo` command line: init, add, remove, list, status, doctor, connect, context, search, health, config, uninstall.

Python 3.9+, standard library only. Nothing here reads shell profiles, .env files or key contents.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import carlo_config as cfg
import carlo_modules as mods
import carlo_settings as settings_io

DEFAULT_MODULES = ("memory", "security")
TEXT_SUFFIXES = {".md", ".tmpl", ".txt", ".toml", ".json"}
OK, WARN, FAIL = "[ok]  ", "[warn]", "[FAIL]"


def say(message: str = "") -> None:
    print(message)


# ---------------------------------------------------------------- init

def render_text(text: str, values: dict) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def copy_template(source: Path, target: Path, values: dict) -> list:
    """Copy the vault template, never overwriting an existing file. Returns created files."""
    created = []
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        dest = target / rel
        if path.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix in TEXT_SUFFIXES:
                dest.write_text(render_text(path.read_text(encoding="utf-8"), values), encoding="utf-8")
            else:
                shutil.copy2(path, dest)
            created.append(str(rel))
    return created


def ask(question: str, default: str, interactive: bool) -> str:
    if not interactive:
        return default
    answer = input(f"{question} [{default}]: ").strip()
    return answer or default


def link_cli(repo: Path) -> Optional[Path]:
    """Symlink ~/.local/bin/carlo to the launcher of this checkout. Never replaces a real file."""
    link = Path.home() / ".local" / "bin" / "carlo"
    target = repo / "carlo"
    if not target.exists():
        return None
    if link.is_symlink():
        link.unlink()
    if link.exists():
        return None
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    return link


NEUTRAL_USER = "the user"  # used in the templates when no first name is given


def cmd_init(args: argparse.Namespace) -> int:
    repo = mods.repo_root()
    interactive = sys.stdin.isatty() and not args.yes
    default_vault = str(cfg.vault() or Path.home() / "carlo-vault")
    vault = Path(args.vault or ask("Vault folder", default_vault, interactive)).expanduser().resolve()
    name = args.name or ask("Assistant name", str(cfg.get("assistant_name") or "Carlo"), interactive)
    user = (args.user or ask("Your first name (optional)", str(cfg.get("user_name") or ""), interactive)).strip() or NEUTRAL_USER
    wanted = [m for m in (args.modules or ",".join(DEFAULT_MODULES)).split(",") if m and m != "none"]
    values = {"ASSISTANT_NAME": name, "USER_NAME": user, "VAULT": str(vault)}
    settings_io.load_settings()  # abort early on a broken settings.json
    for sub in ("lib", "state/boot.d", "state/runs", "state/logs"):
        (cfg.home() / sub).mkdir(parents=True, exist_ok=True)
    (cfg.home() / "keys").mkdir(exist_ok=True, mode=0o700)
    for file in (repo / "core" / "lib").glob("*.py"):
        shutil.copy2(file, cfg.home() / "lib" / file.name)
    config = {**cfg.load_config(), "vault": str(vault), "assistant_name": name, "user_name": user, "repo": str(repo)}
    cfg.save_config(config)
    created = copy_template(repo / "core" / "vault-template", vault, values)
    block = render_text((repo / "core" / "CLAUDE.md.tmpl").read_text(encoding="utf-8"), values)
    made_md = settings_io.install_block(block)
    cfg.save_config({**cfg.load_config(), "claude_md_created": bool(made_md or cfg.get("claude_md_created"))})
    say(f"Vault ready at {vault} ({len(created)} new files). CLAUDE.md block installed in {settings_io.claude_md_path()}.")
    link = link_cli(repo)
    say(f"CLI linked at {link}" if link else "CLI link skipped (a file already exists there).")
    if link and str(Path(link).parent) not in os.environ.get("PATH", "").split(os.pathsep):
        rc = "~/.zshrc" if os.environ.get("SHELL", "").endswith("zsh") else "~/.bashrc"
        say("`carlo` is not on your PATH yet. Run this once, then open a new terminal:\n"
            f"  echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> {rc}")
    status = install_many(wanted, force=args.force) if wanted else 0
    if status == 0:
        say(f"Next: fill {vault / '00_System' / 'MAP.md'} (5 min), then run claude")
    return status


# ---------------------------------------------------------------- add / remove / list

def install_many(names: list, force: bool = False) -> int:
    available = mods.discover()
    try:
        order = mods.resolve_install_order(names, available)
    except mods.ModuleError as exc:
        say(f"{FAIL} {exc}")
        return 1
    status = 0
    for name in order:
        try:
            notes = mods.install_module(available[name], force=force)
            say(f"{OK} installed {name} {available[name].version}")
            for note in notes:
                say(f"       {note}")
        except (mods.ModuleError, settings_io.SettingsError) as exc:
            say(f"{FAIL} {name}: {exc}")
            status = 1
            break
    return status


def cmd_add(args: argparse.Namespace) -> int:
    if not cfg.vault():
        say(f"{FAIL} not initialised: run ./install.sh (or `carlo init`) first")
        return 1
    return install_many(args.modules, force=args.force)


def cmd_remove(args: argparse.Namespace) -> int:
    available = mods.discover()
    status = 0
    for name in args.modules:
        try:
            notes = mods.remove_module(name, force=args.force, module=available.get(name))
            say(f"{OK} removed {name}")
            for note in notes:
                say(f"       {note}")
        except (mods.ModuleError, settings_io.SettingsError) as exc:
            say(f"{FAIL} {name}: {exc}")
            status = 1
    return status


def cmd_list(_args: argparse.Namespace) -> int:
    have = mods.installed()
    for name, module in mods.discover().items():
        mark = "installed" if name in have else "available"
        say(f"{name:<14} {mark:<10} {module.summary}")
    return 0


# ---------------------------------------------------------------- status / doctor

def cmd_status(_args: argparse.Namespace) -> int:
    say(f"home:   {cfg.home()}")
    say(f"vault:  {cfg.vault()}")
    say(f"claude: {settings_io.claude_dir()}")
    try:
        settings = settings_io.load_settings()
    except settings_io.SettingsError as exc:
        say(f"{FAIL} {exc}")
        return 1
    have = mods.installed()
    say(f"modules installed: {', '.join(have) or 'none'}")
    for name in have:
        say(f"  {name}: {len(settings_io.installed_commands(settings, name))} hook(s) in settings.json")
    for name, module in mods.discover().items():
        for note in module.mcp:
            if name in have:
                say(f"  mcp ({name}): {note.get('name', '?')}: {note.get('note', '')}")
    return 0


def check_environment() -> list:
    rows = []
    ok = sys.version_info >= (3, 9)
    rows.append((OK if ok else FAIL, f"python {sys.version.split()[0]} (3.9+ needed)"))
    for tool, level in (("git", WARN), ("claude", WARN)):
        found = shutil.which(tool)
        rows.append((OK if found else level, f"{tool}: {found or 'not found'}"))
    bin_dir = str(Path.home() / ".local" / "bin")
    on_path = bin_dir in os.environ.get("PATH", "").split(os.pathsep)
    rows.append((OK if on_path else WARN, f"{bin_dir} on PATH" if on_path else f"{bin_dir} is not on PATH (add it to run `carlo`)"))
    return rows


def check_core() -> list:
    rows = []
    vault = cfg.vault()
    prompt = vault / "00_System" / "SYSTEM_PROMPT.md" if vault else None
    rows.append((OK if prompt and prompt.exists() else FAIL, f"SYSTEM_PROMPT.md in vault ({prompt})"))
    md = settings_io.claude_md_path()
    has_block = md.exists() and settings_io.BEGIN in md.read_text(encoding="utf-8")
    rows.append((OK if has_block else FAIL, f"CLAUDE.md managed block ({md})"))
    rows += check_keys()
    return rows


def check_keys() -> list:
    """Key files: presence and permissions only, names never contents."""
    folder = cfg.keys_dir()
    files = sorted(f for f in folder.iterdir() if f.is_file()) if folder.is_dir() else []
    if not files:
        return [(OK, "keys/: empty (nothing configured)")]
    rows = []
    for f in files:
        size_ok = f.stat().st_size > 0
        loose = f.stat().st_mode & 0o077
        level = FAIL if not size_ok else (WARN if loose else OK)
        detail = "empty" if not size_ok else ("permissions too open, run chmod 600" if loose else "present, chmod ok")
        rows.append((level, f"key file {f.name}: {detail}"))
    return rows


def check_module(name: str, settings: dict, available: dict) -> list:
    rows = []
    module = available.get(name)
    if module is None:
        return [(WARN, f"{name}: installed but not found in the repo (moved or deleted?)")]
    for dep in mods.missing_deps(module):
        rows.append((FAIL, f"{name}: dependency {dep} not found"))
    for dep in module.optional_deps:
        if shutil.which(dep) is None:
            rows.append((WARN, f"{name}: optional tool {dep} not found (feature reduced)"))
    commands = settings_io.installed_commands(settings, name)
    rows.append((OK if len(commands) == len(module.hooks) else FAIL,
                 f"{name}: {len(commands)}/{len(module.hooks)} hooks in settings.json"))
    for hook in module.hooks:
        for token in shlex.split(mods.render(hook["command"], name).split(" # ")[0]):
            if token.startswith(str(mods.code_dir(name))) and not Path(token).exists():
                rows.append((FAIL, f"{name}: missing script {token}"))
    return rows


def check_audit() -> list:
    script = mods.code_dir("security") / "audit.py"
    if not script.exists():
        return []
    res = subprocess.run([sys.executable, "-I", str(script), "verify"], capture_output=True, text=True,
                         env={**os.environ, "CARLO_BRAIN_HOME": str(cfg.home())})
    return [(OK if res.returncode == 0 else FAIL, f"audit chain: {res.stdout.strip() or res.stderr.strip()}")]


def check_runs() -> list:
    rows = []
    for name, stamp in cfg.last_runs().items():
        try:
            age = datetime.now().astimezone() - datetime.fromisoformat(stamp)
            rows.append((OK, f"last run {name}: {stamp} ({age.days}d {age.seconds // 3600}h ago)"))
        except ValueError:
            rows.append((WARN, f"last run {name}: unreadable timestamp"))
    errors = cfg.state_dir() / "errors.log"
    if errors.exists() and errors.stat().st_size:
        last = errors.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1]
        rows.append((WARN, f"errors.log last line: {last[:120]}"))
    return rows or [(WARN, "no hook has run yet (start a Claude Code session)")]


def load_connector_script(connector: str, script: str):
    """Import a script of the connectors module (installed copy), or None when it is not installed."""
    import importlib.util
    path = mods.code_dir("connectors") / connector / script
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_browser() -> list:
    """Doctor rows for the browser connector (none until `carlo connect browser` was run)."""
    try:
        module = load_connector_script("browser", "browser_setup.py")
    except Exception as exc:  # noqa: BLE001 - a broken optional script must not break doctor
        return [(WARN, f"browser: setup script unreadable ({exc.__class__.__name__})")]
    levels = {"ok": OK, "warn": WARN, "fail": FAIL}
    return [(levels[level], text) for level, text in module.check()] if module else []


AGENT_TOOLS = ("codex", "gemini")


def cmd_connect(args: argparse.Namespace) -> int:
    """`carlo connect browser|codex|gemini [--remove|--status] ...` (codex and gemini: see the other-agents module)."""
    if args.name in AGENT_TOOLS:
        return connect_agent_tool(args)
    module = load_connector_script(args.name, "browser_setup.py") if args.name == "browser" else None
    if module is None:
        say(f"{FAIL} nothing to wire for '{args.name}' (known: browser, codex, gemini; the connectors module must be installed: carlo add connectors)")
        return 1
    action = "remove" if args.remove else ("status" if args.status else "setup")
    return module.run_cli([action] + (["--version", args.version] if args.version else []), out=lambda m: say(f"{OK} {m}"))


def connect_agent_tool(args: argparse.Namespace) -> int:
    """Codex or Gemini: installs the other-agents module on first use, then hands over to its script."""
    if not cfg.vault():
        say(f"{FAIL} not initialised: run ./install.sh (or `carlo init`) first")
        return 1
    if "other-agents" not in mods.installed():
        if args.remove or args.status:
            say(f"{OK} {args.name}: not connected (the other-agents module is not installed)")
            return 0 if args.remove else 1
        if install_many(["other-agents"]):
            return 1
    flags = [f for f, on in (("--remove", args.remove), ("--status", args.status), ("--no-hooks", args.no_hooks),
                             ("--no-agents", args.no_agents), ("--mcp", args.mcp), ("--inline", args.inline)) if on]
    return hand_over([str(mods.code_dir("other-agents") / "agents_connect.py"), args.name, *flags])


def hand_over(script_and_args: list) -> int:
    """Run a module script with this interpreter and relay its output through `say` (so it can be captured)."""
    res = subprocess.run([sys.executable, "-I", *script_and_args], capture_output=True, text=True,
                         env={**os.environ, "CARLO_BRAIN_HOME": str(cfg.home())})
    if res.stdout:
        say(res.stdout.rstrip("\n"))
    if res.stderr:
        print(res.stderr.rstrip("\n"), file=sys.stderr)
    return res.returncode


def check_other_agents() -> list:
    """Doctor rows for the tools connected with `carlo connect codex|gemini` (none until one was)."""
    script = mods.code_dir("other-agents") / "agents_connect.py"
    if "other-agents" not in mods.installed() or not script.exists():
        return []
    try:
        res = subprocess.run([sys.executable, "-I", "-c",
                              "import sys, json; sys.path.insert(0, sys.argv[1]); import agents_connect; print(json.dumps(agents_connect.check()))",
                              str(script.parent)], capture_output=True, text=True, timeout=30,
                             env={**os.environ, "CARLO_BRAIN_HOME": str(cfg.home())})
        levels = {"ok": OK, "warn": WARN, "fail": FAIL}
        return [(levels[level], text) for level, text in json.loads(res.stdout)]
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return [(WARN, "other-agents: check failed")]


def cmd_context(args: argparse.Namespace) -> int:
    """Paste-ready memory for any LLM. Uses the installed other-agents script, or the repo copy before it is installed."""
    script = mods.code_dir("other-agents") / "context.py"
    if not script.exists():
        script = mods.modules_dir() / "other-agents" / "src" / "context.py"
    if not script.exists():
        say(f"{FAIL} other-agents module not found in {mods.modules_dir()}")
        return 1
    flags = [f for f, on in (("--copy", args.copy), ("--boot", args.boot), ("--refresh", args.refresh)) if on]
    return hand_over([str(script), *flags, "--max", str(args.max)])


def check_routing() -> list:
    """Doctor rows: routing.json against the installed agents (silent until an agent is routed)."""
    try:
        module = load_connector_script("openrouter", "route_sync.py")
        levels = {"ok": OK, "warn": WARN, "fail": FAIL}
        return [(levels[level], text) for level, text in module.check()] if module else []
    except Exception as exc:  # noqa: BLE001 - a broken optional script must not break doctor
        return [(WARN, f"routing: check failed ({exc.__class__.__name__})")]


def cmd_route(args: argparse.Namespace) -> int:
    """`carlo route status` and `carlo route sync [--undo]`."""
    module = load_connector_script("openrouter", "route_sync.py")
    if module is None:
        say(f"{FAIL} the connectors module is not installed: run `carlo add connectors`")
        return 1
    return module.run_cli([args.action] + (["--undo"] if args.undo else []), out=lambda m: say(f"{OK} {m}" if args.action == "sync" else m))


def check_health() -> list:
    """Status from the health module's watchdog (jobs on time, connectors alive), same as its boot note."""
    script = mods.code_dir("health") / "healthcheck.py"
    if "health" not in mods.installed() or not script.exists():
        return []
    try:
        res = subprocess.run([sys.executable, "-I", str(script), "check", "--json"], capture_output=True, text=True,
                             timeout=120, env={**os.environ, "CARLO_BRAIN_HOME": str(cfg.home())})
        items = json.loads(res.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return [(WARN, "health: watchdog did not answer")]
    levels = {"ok": OK, "warn": WARN, "fail": FAIL}
    return [(levels[i["level"]], i["text"]) for i in items if i.get("level") in levels]


def cmd_doctor(_args: argparse.Namespace) -> int:
    rows = check_environment()
    try:
        settings = settings_io.load_settings()
        rows.append((OK, f"settings.json parses ({settings_io.settings_path()})"))
    except settings_io.SettingsError as exc:
        settings = {}
        rows.append((FAIL, str(exc)))
    rows += check_core()
    available = mods.discover()
    for name in mods.installed():
        rows += check_module(name, settings, available)
    rows += check_browser() + check_other_agents() + check_routing() + check_audit() + check_runs() + check_health()
    for level, text in rows:
        say(f"{level} {text}")
    failed = sum(1 for level, _ in rows if level == FAIL)
    say(f"\n{failed} failure(s), {sum(1 for l, _ in rows if l == WARN)} warning(s).")
    return 1 if failed else 0


# ---------------------------------------------------------------- health

def cmd_health(args: argparse.Namespace) -> int:
    """Hand over to the health module: `carlo health status`, `carlo health repair [--dry-run]`, `check`, `catchup`."""
    script = mods.code_dir("health") / "healthcheck.py"
    if "health" not in mods.installed() or not script.exists():
        say(f"{FAIL} the health module is not installed: run `carlo add health`")
        return 1
    rest = args.rest or ["status"]
    return subprocess.run([sys.executable, "-I", str(script), *rest],
                          env={**os.environ, "CARLO_BRAIN_HOME": str(cfg.home())}).returncode


# ---------------------------------------------------------------- search

def cmd_search(args: argparse.Namespace) -> int:
    """Hand over to the search module (read only, local)."""
    script = mods.code_dir("search") / "search.py"
    if "search" not in mods.installed() or not script.exists():
        say(f"{FAIL} the search module is not installed: run `carlo add search`")
        return 1
    return subprocess.run([sys.executable, "-I", str(script), *args.rest],
                          env={**os.environ, "CARLO_BRAIN_HOME": str(cfg.home())}).returncode


# ---------------------------------------------------------------- config / uninstall

def cmd_config(args: argparse.Namespace) -> int:
    if args.action == "get":
        value = cfg.get(args.key)
        say(json.dumps(value, ensure_ascii=False) if value is not None else "")
        return 0 if value is not None else 1
    try:
        value = json.loads(args.value)
    except ValueError:
        value = args.value
    cfg.save_config(cfg.with_value(cfg.load_config(), args.key, value))
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    available = mods.discover()
    for name in list(mods.installed()):
        try:
            mods.remove_module(name, force=True, module=available.get(name))
            say(f"{OK} removed {name}")
        except (mods.ModuleError, settings_io.SettingsError) as exc:
            say(f"{FAIL} {name}: {exc}")
            return 1
    removed = settings_io.remove_block(delete_if_empty=bool(cfg.get("claude_md_created")))
    say(f"{OK} CLAUDE.md block removed" if removed else f"{OK} no CLAUDE.md block found")
    link = Path.home() / ".local" / "bin" / "carlo"
    if link.is_symlink() and str(mods.repo_root()) in str(link.resolve()):
        link.unlink()
    if args.purge:
        shutil.rmtree(cfg.home(), ignore_errors=True)
        say(f"{OK} {cfg.home()} deleted (your vault is untouched)")
    else:
        shutil.rmtree(cfg.home() / "lib", ignore_errors=True)
        say(f"{OK} state, keys and config kept in {cfg.home()} (use --purge to delete them; the vault is never deleted)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="carlo", description="Carlo Brain: manage your Chief of Staff modules.")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="set up vault, CLAUDE.md block and default modules")
    init.add_argument("--vault")
    init.add_argument("--name")
    init.add_argument("--user")
    init.add_argument("--modules", help="comma list, or 'none' (default: memory,security)")
    init.add_argument("--yes", action="store_true", help="no prompts, use defaults")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)
    for name, func, help_ in (("add", cmd_add, "install modules"), ("remove", cmd_remove, "remove modules")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("modules", nargs="+")
        p.add_argument("--force", action="store_true")
        p.set_defaults(func=func)
    for name, func, help_ in (("list", cmd_list, "list modules"), ("status", cmd_status, "show what is installed"),
                              ("doctor", cmd_doctor, "check the installation")):
        sub.add_parser(name, help=help_).set_defaults(func=func)
    conn = sub.add_parser("connect", help="wire a tool: browser (Playwright MCP for Claude Code), codex, gemini")
    conn.add_argument("name", choices=["browser", *AGENT_TOOLS])
    conn.add_argument("--remove", action="store_true")
    conn.add_argument("--status", action="store_true")
    conn.add_argument("--version", default="", help="browser: pin the server version (default: latest)")
    conn.add_argument("--no-hooks", action="store_true", help="codex, gemini: instructions block only, no hooks")
    conn.add_argument("--no-agents", action="store_true", help="codex, gemini: do not export the agents and skills")
    conn.add_argument("--mcp", action="store_true", help="codex, gemini: also register the Playwright MCP server")
    conn.add_argument("--inline", action="store_true", help="gemini: copy the prompt and map instead of importing them")
    conn.set_defaults(func=cmd_connect)
    ctx = sub.add_parser("context", help="print or copy a prompt that gives any LLM your memory",
                         description="System prompt, map, recent sessions and briefing in one capped, paste-ready text.")
    ctx.add_argument("--copy", action="store_true", help="copy to the clipboard (pbcopy, wl-copy, xclip, xsel)")
    ctx.add_argument("--boot", action="store_true", help="only the boot context (what the Claude hook injects)")
    ctx.add_argument("--refresh", action="store_true", help="regenerate the block of every connected tool")
    ctx.add_argument("--max", type=int, default=24000, help="character cap (default 24000)")
    ctx.set_defaults(func=cmd_context)
    rt = sub.add_parser("route", help="apply routing.json to Claude Code: model fields and routed wrapper agents")
    rt.add_argument("action", choices=["status", "sync"])
    rt.add_argument("--undo", action="store_true", help="with sync: restore the original model fields, remove wrappers")
    rt.set_defaults(func=cmd_route)
    find = sub.add_parser("search", help="read-only search: vault, folders, Notes, Messages, Mail",
                          description="Arguments go to the search module: carlo search \"words\" [--source a,b] [--max N] [--json] [--spotlight] [--rebuild-cache]")
    find.add_argument("rest", nargs=argparse.REMAINDER)
    find.set_defaults(func=cmd_search)
    care = sub.add_parser("health", help="watchdog: status, repair [--dry-run], check, catchup",
                          description="Arguments go to the health module: carlo health status | repair [--dry-run] | check [--json] | catchup [--dry-run]")
    care.add_argument("rest", nargs=argparse.REMAINDER)
    care.set_defaults(func=cmd_health)
    conf = sub.add_parser("config", help="get or set a config value (dotted key)")
    conf.add_argument("action", choices=["get", "set"])
    conf.add_argument("key")
    conf.add_argument("value", nargs="?", default="")
    conf.set_defaults(func=cmd_config)
    un = sub.add_parser("uninstall", help="remove every module and the CLAUDE.md block")
    un.add_argument("--purge", action="store_true", help="also delete ~/.carlo-brain (never the vault)")
    un.set_defaults(func=cmd_uninstall)
    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    if extra:  # `carlo search --rebuild-cache`: argparse leaves a leading option out of REMAINDER
        if hasattr(args, "rest"):
            args.rest = [*extra, *args.rest]
        else:
            parser.error(f"unrecognized arguments: {' '.join(extra)}")
    try:
        return int(args.func(args) or 0)
    except settings_io.SettingsError as exc:
        say(f"{FAIL} {exc}")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
