"""Module discovery, install and removal for the `carlo` CLI.

A module lives in `<repo>/modules/<name>/` with a `module.toml`, a `src/` folder (copied to
`~/.carlo-brain/<name>/`) and optional `install.sh` / `uninstall.sh`. See CONTRACT.md.
"""
from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import carlo_config as cfg
import carlo_settings as settings_io
import carlo_toml

LAUNCHD_PREFIX = "com.carlo-brain"


class ModuleError(RuntimeError):
    """A module is missing, malformed or cannot be installed."""


@dataclass(frozen=True)
class Module:
    name: str
    summary: str
    version: str
    path: Path
    requires: tuple = ()
    deps: tuple = ()
    optional_deps: tuple = ()
    platforms: tuple = ()
    hooks: tuple = ()
    launchd: tuple = ()
    mcp: tuple = ()
    raw: dict = field(default_factory=dict)


def repo_root() -> Path:
    env = os.environ.get("CARLO_REPO") or cfg.get("repo")
    if env:
        return Path(str(env))
    return Path(__file__).resolve().parents[2]


def modules_dir(repo: Optional[Path] = None) -> Path:
    return (repo or repo_root()) / "modules"


def load_module(path: Path) -> Module:
    """Parse and validate `<path>/module.toml`."""
    toml_file = path / "module.toml"
    try:
        data = carlo_toml.loads(toml_file.read_text(encoding="utf-8"))
    except (OSError, carlo_toml.TomlError) as exc:
        raise ModuleError(f"{toml_file}: {exc}") from exc
    name = str(data.get("name") or "")
    if not name or name != path.name:
        raise ModuleError(f"{toml_file}: `name` must equal the folder name ({path.name!r})")
    hooks = tuple(data.get("hooks") or ())
    for hook in hooks:
        if not hook.get("event") or not hook.get("command"):
            raise ModuleError(f"{toml_file}: every [[hooks]] needs `event` and `command`")
    for job in data.get("launchd") or ():
        if not job.get("label") or not job.get("command"):
            raise ModuleError(f"{toml_file}: every [[launchd]] needs `label` and `command`")
    return Module(
        name=name, summary=str(data.get("summary", "")), version=str(data.get("version", "0.0.0")), path=path,
        requires=tuple(data.get("requires") or ()), deps=tuple(data.get("deps") or ()),
        optional_deps=tuple(data.get("optional_deps") or ()), platforms=tuple(data.get("platforms") or ()),
        hooks=hooks, launchd=tuple(data.get("launchd") or ()), mcp=tuple(data.get("mcp") or ()), raw=data,
    )


def discover(repo: Optional[Path] = None) -> dict:
    """All modules of the repo, by name. A broken module raises ModuleError."""
    base = modules_dir(repo)
    found = {}
    for child in sorted(base.iterdir()) if base.is_dir() else []:
        if (child / "module.toml").exists():
            found[child.name] = load_module(child)
    return found


def code_dir(name: str) -> Path:
    return cfg.home() / name


def render(template: str, module: str) -> str:
    """Fill {PY} {CODE} {BRAIN} {HOME} in a hook or launchd command (paths are shell-quoted)."""
    values = {
        "PY": shlex.quote(str(cfg.get("python") or sys.executable or "python3")), "CODE": shlex.quote(str(code_dir(module))),
        "BRAIN": shlex.quote(str(cfg.home())), "HOME": shlex.quote(str(Path.home())),
    }
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return out


def installed() -> dict:
    """Installed modules: {name: {"version": ..., "installed_at": ...}}."""
    return dict(cfg.get("modules", {}) or {})


def missing_deps(module: Module) -> list:
    return [d for d in module.deps if shutil.which(d) is None]


def _script_env() -> dict:
    return {**os.environ, "CARLO_BRAIN_HOME": str(cfg.home()), "CARLO_VAULT": str(cfg.vault() or "")}


def _run_script(module: Module, script: str) -> None:
    path = module.path / script
    if not path.exists():
        return
    env = {**_script_env(), "CARLO_MODULE_DIR": str(code_dir(module.name))}
    result = subprocess.run(["bash", str(path)], env=env, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise ModuleError(f"{module.name}/{script} failed: {(result.stderr or result.stdout).strip()[:300]}")


def _copy_src(module: Module) -> None:
    target = code_dir(module.name)
    if target.exists():
        shutil.rmtree(target)
    src = module.path / "src"
    if src.is_dir():
        shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    else:
        target.mkdir(parents=True)
    for script in target.rglob("*.sh"):
        script.chmod(script.stat().st_mode | 0o755)


def _platform_ok(module: Module) -> bool:
    aliases = {"macos": "darwin", "darwin": "darwin", "linux": "linux"}
    wanted = {aliases.get(p.lower(), p.lower()) for p in module.platforms}
    return not wanted or sys.platform in wanted


def install_module(module: Module, force: bool = False, use_launchd: bool = True) -> list:
    """Install one module. Returns human readable notes (warnings, actions)."""
    if not _platform_ok(module):
        raise ModuleError(f"{module.name} supports {', '.join(module.platforms)} only (this is {sys.platform})")
    absent = missing_deps(module)
    if absent and not force:
        raise ModuleError(f"{module.name} needs: {', '.join(absent)} (install them or use --force)")
    notes = [f"missing dependency {d} (forced)" for d in absent]
    notes += [f"optional tool not found: {d}" for d in module.optional_deps if shutil.which(d) is None]
    # Parse settings first: a broken settings.json must abort before anything is touched.
    current = settings_io.load_settings()
    _copy_src(module)
    entries = [{**h, "command": render(h["command"], module.name)} for h in module.hooks]
    backup = settings_io.write_settings(settings_io.add_module_hooks(current, module.name, entries))
    if backup:
        notes.append(f"settings.json backed up to {backup}")
    _run_script(module, "install.sh")
    if use_launchd:
        notes += install_launchd(module)
    record = {"version": module.version, "installed_at": cfg.now_iso()}
    cfg.save_config(cfg.with_value(cfg.load_config(), f"modules.{module.name}", record))
    return notes


def remove_module(module_name: str, force: bool = False, module: Optional[Module] = None) -> list:
    """Remove hooks, launchd jobs and code of a module. State and keys are kept."""
    config = cfg.load_config()
    if module_name not in (config.get("modules") or {}):
        raise ModuleError(f"{module_name} is not installed")
    dependants = [n for n in installed() if n != module_name and module_name in _requires_of(n)]
    if dependants and not force:
        raise ModuleError(f"{', '.join(dependants)} requires {module_name} (use --force)")
    notes = remove_launchd(module_name)
    current = settings_io.load_settings()
    backup = settings_io.write_settings(settings_io.remove_module_hooks(current, module_name))
    if backup:
        notes.append(f"settings.json backed up to {backup}")
    if module is not None:
        try:
            _run_script(module, "uninstall.sh")
        except (ModuleError, subprocess.SubprocessError) as exc:
            notes.append(f"uninstall.sh problem: {exc}")
    shutil.rmtree(code_dir(module_name), ignore_errors=True)
    modules = {k: v for k, v in (config.get("modules") or {}).items() if k != module_name}
    cfg.save_config({**config, "modules": modules})
    return notes


def _requires_of(name: str) -> tuple:
    try:
        return load_module(modules_dir() / name).requires
    except ModuleError:
        return ()


def plist_path(module: str, label: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_PREFIX}.{module}.{label}.plist"


def build_plist(module: Module, job: dict) -> dict:
    """launchd definition. `interval` (seconds) or `hour`/`minute` for a daily run."""
    label = f"{LAUNCHD_PREFIX}.{module.name}.{job['label']}"
    logs = cfg.state_dir() / "logs"
    data = {"Label": label, "ProgramArguments": ["/bin/bash", "-c", render(job["command"], module.name)],
            "RunAtLoad": False,
            "StandardOutPath": str(logs / f"{module.name}.{job['label']}.log"),
            "StandardErrorPath": str(logs / f"{module.name}.{job['label']}.err")}
    if "interval" in job:
        data["StartInterval"] = int(job["interval"])
    else:
        data["StartCalendarInterval"] = {"Hour": int(job.get("hour", 3)), "Minute": int(job.get("minute", 0))}
    return data


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def _real_home() -> bool:
    """True when HOME is the login user's home. A throwaway HOME (tests, trials) must not load jobs
    into the user's real launchd session, where they would outlive the temporary folder."""
    try:
        import pwd
        return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve() == Path.home().resolve()
    except (ImportError, KeyError, OSError):
        return True


def install_launchd(module: Module) -> list:
    """macOS only: write plists and load them (skipped when CARLO_NO_LAUNCHD=1)."""
    if not module.launchd:
        return []
    if sys.platform != "darwin":
        cmds = "; ".join(render(j["command"], module.name) for j in module.launchd)
        return [f"{module.name}: scheduled jobs use launchd (macOS only). On Linux schedule with cron: {cmds}"]
    notes = []
    (cfg.state_dir() / "logs").mkdir(parents=True, exist_ok=True)
    for job in module.launchd:
        path = plist_path(module.name, job["label"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plistlib.dumps(build_plist(module, job)))
        notes.append(f"launchd job written: {path.name}")
        if not os.environ.get("CARLO_NO_LAUNCHD") and not _real_home():
            notes.append(f"{path.name} not loaded: HOME is not your login home (test install)")
        elif not os.environ.get("CARLO_NO_LAUNCHD"):
            domain = f"gui/{os.getuid()}"
            _launchctl("bootout", domain, str(path))
            res = _launchctl("bootstrap", domain, str(path))
            if res.returncode != 0:
                notes.append(f"launchctl bootstrap failed for {path.name}: {res.stderr.strip()[:200]}")
    return notes


def remove_launchd(module_name: str) -> list:
    folder = Path.home() / "Library" / "LaunchAgents"
    notes = []
    for path in sorted(folder.glob(f"{LAUNCHD_PREFIX}.{module_name}.*.plist")) if folder.is_dir() else []:
        if sys.platform == "darwin" and not os.environ.get("CARLO_NO_LAUNCHD"):
            _launchctl("bootout", f"gui/{os.getuid()}", str(path))
        path.unlink()
        notes.append(f"launchd job removed: {path.name}")
    return notes


def resolve_install_order(names: list, available: dict) -> list:
    """Requested modules plus their `requires`, dependencies first."""
    order: list = []

    def visit(name: str, trail: tuple) -> None:
        if name in order:
            return
        if name not in available:
            raise ModuleError(f"unknown module: {name} (try `carlo list`)")
        if name in trail:
            raise ModuleError(f"circular requires: {' -> '.join(trail + (name,))}")
        for dep in available[name].requires:
            visit(dep, trail + (name,))
        order.append(name)

    for name in names:
        visit(name, ())
    return order
