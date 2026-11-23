"""Checks run after a change, by file type. Every function returns a list of error strings (empty = fine)."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import List, Optional, Sequence

try:
    import tomllib
except ImportError:  # Python < 3.11: .toml files are not parse-checked
    tomllib = None  # type: ignore[assignment]

# Same idea as `env -u`: unattended code must not inherit billed credentials by accident.
SENSITIVE_ENV = re.compile(r"(API_KEY|_KEY$|SECRET|PASSWORD|PASSWD)", re.IGNORECASE)
KEEP_ENV = {"CLAUDE_CODE_OAUTH_TOKEN"}
FRONTMATTER_KEY = re.compile(r"^[A-Za-z0-9_.-]+:(\s|$)")
MD_LINK = re.compile(r"\]\(([^)#\s]+\.md)\)")


def clean_env(extra: Optional[dict] = None) -> dict:
    """Environment without key-like variables (the login token of the subscription is kept)."""
    env = {k: v for k, v in os.environ.items() if k in KEEP_ENV or not SENSITIVE_ENV.search(k)}
    env.update(extra or {})
    return env


def added_lines(old: str, new: str) -> List[str]:
    """Lines present in `new` and absent from `old` (multiset difference)."""
    left = Counter(old.splitlines())
    added: List[str] = []
    for line in new.splitlines():
        if left[line] > 0:
            left[line] -= 1
        else:
            added.append(line)
    return added


def frontmatter_errors(text: str) -> List[str]:
    """Light YAML front matter check (no YAML library in the standard library)."""
    lines = text.split("\n")
    if lines[0].rstrip() != "---":
        return []
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].rstrip() == "---")
    except StopIteration:
        return ["front matter not closed (second '---' missing)"]
    errors = []
    for number, line in enumerate(lines[1:end], start=2):
        if not line.strip() or line.lstrip().startswith("#") or line[0] in " \t-":
            continue
        if not FRONTMATTER_KEY.match(line):
            errors.append(f"front matter line {number} invalid: {line[:40]!r}")
    return errors


def broken_links(path: Path, text: str) -> set:
    """Local [x](y.md) links whose target does not exist."""
    return {link for link in MD_LINK.findall(text) if "://" not in link and not (path.parent / link).exists()}


def check_markdown(path: Path, old: str, new: str, forbidden: Sequence[str] = ()) -> List[str]:
    """Forbidden characters in added lines (configurable), front matter, new broken links in an index."""
    errors = [f"forbidden character in added line: {line[:60]!r}"
              for line in added_lines(old, new) if any(c in line for c in forbidden)]
    errors += frontmatter_errors(new)
    if path.name.upper() == "MEMORY.MD":
        errors += [f"broken index link: {link}" for link in sorted(broken_links(path, new) - broken_links(path, old))]
    return errors


def run(cmd: List[str], timeout: int, cwd: Optional[Path] = None, env_extra: Optional[dict] = None) -> Optional[str]:
    """Run without a shell, without key variables, with a timeout. Error message or None."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=clean_env(env_extra))
    except subprocess.TimeoutExpired:
        return f"timeout ({timeout}s): {' '.join(cmd[:3])}"
    except OSError as err:
        return f"cannot run: {err}"
    if res.returncode != 0:
        return f"failed ({res.returncode}) {' '.join(cmd[:3])}: {(res.stdout + res.stderr)[-300:]}"
    return None


def pytest_command() -> List[str]:
    exe = shutil.which("pytest")
    return [exe] if exe else [sys.executable, "-m", "pytest"]


def check_python(path: Path, timeout: int) -> List[str]:
    """py_compile, then pytest if a test_*.py sits next to the file."""
    with tempfile.TemporaryDirectory() as cache:
        errors = [run([sys.executable, "-m", "py_compile", str(path)], timeout, env_extra={"PYTHONPYCACHEPREFIX": cache})]
        if list(path.parent.glob("test_*.py")):
            errors.append(run(pytest_command() + ["-q", "-x", "-p", "no:cacheprovider", str(path.parent)], timeout,
                              cwd=path.parent, env_extra={"PYTHONPYCACHEPREFIX": cache}))
    return [e for e in errors if e]


def check_data(path: Path, text: str) -> List[str]:
    """Parse .json (and .toml when tomllib exists)."""
    try:
        if path.suffix == ".json":
            json.loads(text)
        elif tomllib is not None:
            tomllib.loads(text)
    except ValueError as err:  # JSONDecodeError and TOMLDecodeError both derive from ValueError
        return [f"invalid {path.suffix}: {err}"]
    return []


def check_file(path: Path, old: str, new: str, timeout: int, forbidden: Sequence[str] = ()) -> List[str]:
    """Checks of a file already written, by extension."""
    ext = path.suffix
    if ext == ".md":
        return check_markdown(path, old, new, forbidden)
    if ext == ".py":
        return check_python(path, timeout)
    if ext == ".sh":
        err = run(["bash", "-n", str(path)], timeout)
        return [err] if err else []
    if ext in (".json", ".toml"):
        return check_data(path, new)
    return []


def check_text(path: Path, old: str, new: str, forbidden: Sequence[str] = ()) -> List[str]:
    """Pure checks on proposed text (dry run: nothing is written)."""
    ext = path.suffix
    if ext == ".md":
        return check_markdown(path, old, new, forbidden)
    if ext in (".json", ".toml"):
        return check_data(path, new)
    if ext == ".py":
        try:
            compile(new, str(path), "exec")
        except SyntaxError as err:
            return [f"python syntax: {err}"]
    return []


def run_test_command(command: str, timeout: int) -> List[str]:
    """The proposal's own test command (no shell)."""
    try:
        parts = shlex.split(command)
    except ValueError as err:
        return [f"test command unparsable: {err}"]
    err = run(parts, timeout)
    return [err] if err else []
