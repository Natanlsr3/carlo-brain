#!/usr/bin/env python3
"""Paste-ready context for any LLM, and the text blocks `carlo connect codex|gemini` writes.

  context.py [--copy] [--max N]   one prompt: system prompt, map, recent sessions and briefing (default cap 24,000 characters)
  context.py --boot               only the boot context (what the Claude Code SessionStart hook injects)
  context.py --refresh            regenerate the instruction block of every connected tool (Codex copy of the prompt)

Python 3.9+, standard library only. Read only on the vault. The boot context comes from the memory module's
`boot.py`, so it is the same text, capped the same way, as in Claude Code.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _lib in (os.environ.get("CARLO_LIB"), str(Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain") / "lib")):
    if _lib:
        sys.path.insert(0, _lib)
import carlo_config as cfg  # noqa: E402

PASTE_MAX = 24000      # characters, fits a chat box and a small local model
INLINE_PROMPT = 11000  # bytes of SYSTEM_PROMPT.md copied into a Codex block (Codex reads 32 KiB in all)
INLINE_MAP = 4000      # bytes of MAP.md copied into a Codex block
NEUTRAL_USER = "the user"


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def clip(text: str, limit: int, source: str = "", by_bytes: bool = False) -> str:
    """`text` cut to `limit` (characters, or UTF-8 bytes) with a note saying where the full file is."""
    size = len(text.encode("utf-8")) if by_bytes else len(text)
    if size <= limit:
        return text
    note = f"\n[...] (cut to fit, full file: {source})" if source else "\n[...] (cut to fit)"
    room = max(limit - (len(note.encode("utf-8")) if by_bytes else len(note)), 0)
    head = text.encode("utf-8")[:room].decode("utf-8", "ignore") if by_bytes else text[:room]
    return head.rstrip() + note


def identity() -> Tuple[str, str, str]:
    """(assistant name, user name, vault path) from config.json."""
    vault = cfg.vault()
    return str(cfg.get("assistant_name") or "Carlo"), str(cfg.get("user_name") or NEUTRAL_USER), str(vault or "")


def vault_files() -> Tuple[str, str]:
    """(SYSTEM_PROMPT.md, MAP.md) texts; empty strings when missing."""
    system = cfg.system_dir()
    return (read(system / "SYSTEM_PROMPT.md"), read(system / "MAP.md")) if system else ("", "")


def source_hash(*texts: str) -> str:
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()[:10]


def memory_boot_script() -> Optional[Path]:
    """The memory module's boot.py: installed copy first, then the repo checkout."""
    candidates = [cfg.home() / "memory" / "boot.py"]
    repo = os.environ.get("CARLO_REPO") or cfg.get("repo")
    if repo:
        candidates.append(Path(str(repo)) / "modules" / "memory" / "src" / "boot.py")
    candidates.append(Path(__file__).resolve().parents[2] / "memory" / "src" / "boot.py")
    return next((p for p in candidates if p.is_file()), None)


def boot_context(cwd: Optional[Path] = None) -> str:
    """The capped boot context of the memory module (recent sessions, signals, health, pending facts)."""
    script = memory_boot_script()
    if script is None:
        return ""
    spec = importlib.util.spec_from_file_location("carlo_memory_boot", script)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(script.parent))
    try:
        spec.loader.exec_module(module)
        return module.build_context({"cwd": str(cwd or Path.cwd()), "source": "startup"})
    except Exception as exc:  # noqa: BLE001 - a broken boot script must not break `carlo context`
        cfg.log_error("other-agents.context", exc)
        return ""


def rules(user: str, vault: str) -> str:
    """The behaviour rules, the same for every tool (a short copy of what the Claude Code block says)."""
    return "\n".join([
        "Rules (same as in Claude Code):",
        f"- Vault: `{vault}`. The MAP says who {user} is and which projects exist; the SYSTEM_PROMPT holds the working rules. "
        "Everything else in the vault is read on demand: open the entry file the MAP names before working on a project.",
        "- Start of session: if you do not see a section titled \"Context (injected by the carlo-brain memory module)\", "
        "run `carlo context --boot` first and read it (recent sessions, what needs attention).",
        "- Search before asking: `carlo search \"<words>\"` looks through the vault and the user's files (read only). Try it before you ask the user for something.",
        "- Log: every session ends with an entry in `00_System/SESSION_LOG.md`, right under the \"NEW ENTRIES HERE\" marker "
        "(never inside the format blocks). A corrected behaviour goes to `00_System/CORRECTIONS.md`.",
        "- Sends: nothing leaves the machine (mail, message, post, payment, shared file) without a \"go\" from the user on the exact text. "
        "Show the draft first. If the user edits one word, show it again.",
        "- Secrets: never read or copy `.env` files, shell profiles, key files, `~/.carlo-brain/keys/` or this tool's own login files. "
        "To know whether a key exists use `test -s <file>`; pass its path to programs through a `*_KEY_FILE` variable.",
        "- If you cannot see the SYSTEM_PROMPT and MAP content in your context, read both files first.",
    ])


def paste_prompt(max_chars: int = PASTE_MAX, cwd: Optional[Path] = None) -> str:
    """One prompt for a chat or an agent that cannot read the vault: instructions, map, boot context. Never above max_chars."""
    name, user, vault = identity()
    system, mapping = vault_files()
    boot = boot_context(cwd)
    header = (f"You are {name}, the personal chief of staff of {user}. Everything between the markers below is your standing "
              "memory for this conversation: follow the SYSTEM PROMPT, use the MAP to know the person, use the RECENT SESSIONS to pick up where "
              "we stopped. You may not be able to open files: when you need a note that is not shown, say which one and ask me to paste it. "
              "Nothing is sent anywhere without my \"go\" on the exact text.")
    budget = max(max_chars - len(header) - 400, 1000)
    mapping = clip(mapping, min(len(mapping), budget // 5), "00_System/MAP.md")
    boot = clip(boot, min(len(boot), budget * 35 // 100), "carlo context --boot")
    system = clip(system, max(budget - len(mapping) - len(boot), 500), "00_System/SYSTEM_PROMPT.md")
    parts = [header, "=== SYSTEM PROMPT ===\n" + system.strip(), "=== MAP ===\n" + mapping.strip()]
    if boot:
        parts.append("=== RECENT SESSIONS AND BRIEFING ===\n" + boot.strip())
    parts.append("=== END OF MEMORY. Reply \"ready\" in one line, then wait for my first request. ===")
    return clip("\n\n".join(parts), max_chars)


def instruction_block(imports: bool) -> str:
    """Managed block for a tool's global instructions file.

    imports=True (Gemini): the prompt and map are `@file` imports, always fresh, no size limit.
    imports=False (Codex): a capped, generated copy, refreshed by `carlo context --refresh` and at every session start.
    """
    name, user, vault = identity()
    system, mapping = vault_files()
    lines = [f"# {name} (Chief of Staff for {user}): always on", ""]
    if imports:
        lines += [f"The system prompt and the map of {user} are imported below.", "",
                  f"@{vault}/00_System/SYSTEM_PROMPT.md", "", f"@{vault}/00_System/MAP.md", ""]
    else:
        lines += [f"Generated copy of the vault's system prompt and map (source hash {source_hash(system, mapping)}); "
                  "it is capped, the files in the vault are the reference. Refresh it with `carlo context --refresh`.", "",
                  "## SYSTEM_PROMPT.md", clip(system, INLINE_PROMPT, f"{vault}/00_System/SYSTEM_PROMPT.md", True).strip(), "",
                  "## MAP.md", clip(mapping, INLINE_MAP, f"{vault}/00_System/MAP.md", True).strip(), ""]
    return "\n".join(lines + [rules(user, vault)])


def copy_to_clipboard(text: str, which: Callable = shutil.which, run: Callable = subprocess.run) -> Optional[str]:
    """Name of the tool used (pbcopy, wl-copy, xclip, xsel), None when none is available."""
    for tool, args in (("pbcopy", ["pbcopy"]), ("wl-copy", ["wl-copy"]), ("xclip", ["xclip", "-selection", "clipboard"]),
                       ("xsel", ["xsel", "--clipboard", "--input"])):
        if which(tool):
            try:
                if run(args, input=text, text=True, timeout=10).returncode == 0:
                    return tool
            except (OSError, subprocess.SubprocessError):
                continue
    return None


def refresh_connected(out: Callable[[str], None] = print) -> int:
    """Re-render the instruction block of every connected tool (needs the connect script next to this file)."""
    import agents_connect
    done = agents_connect.refresh_all()
    for tool, changed in done:
        out(f"{tool}: {'block regenerated' if changed else 'block already up to date'}")
    if not done:
        out("no tool connected (carlo connect codex | gemini)")
    return 0


def main(argv: Optional[List[str]] = None, out: Callable[[str], None] = print) -> int:
    parser = argparse.ArgumentParser(prog="carlo context", description="Print (or copy) a prompt that gives any LLM your memory.")
    parser.add_argument("--copy", action="store_true", help="copy to the clipboard (pbcopy, wl-copy, xclip or xsel) instead of printing")
    parser.add_argument("--max", type=int, default=PASTE_MAX, help=f"character cap (default {PASTE_MAX})")
    parser.add_argument("--boot", action="store_true", help="print only the boot context")
    parser.add_argument("--refresh", action="store_true", help="regenerate the block of every connected tool")
    args = parser.parse_args(argv)
    if args.refresh:
        return refresh_connected(out)
    if not cfg.vault() or not (cfg.system_dir() / "SYSTEM_PROMPT.md").is_file():
        out("no vault found: run ./install.sh (or `carlo init`) first")
        return 1
    text = boot_context() if args.boot else paste_prompt(max(args.max, 2000))
    if args.copy:
        tool = copy_to_clipboard(text)
        if tool:
            out(f"copied {len(text)} characters with {tool}; paste it as the first message of your chat")
            return 0
        print("no clipboard tool found (pbcopy, wl-copy, xclip, xsel): printing instead", file=sys.stderr)
    out(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
