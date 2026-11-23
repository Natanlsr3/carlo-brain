#!/usr/bin/env python3
"""Guardrails, no LLM (zero tokens except the reminders they inject).

Three modes, one hook each:
  prompt  (UserPromptSubmit)  a long request gets a short alignment reminder.
  post    (PostToolUse)       loops (same file edited 5 times, same command run 3 times) get a reminder;
                              also tracks whether code changed since the last test run.
  stop    (Stop)              code changed and no test ran since: block ONCE and ask for tests or a reason.

Turn parts off with `carlo config set security.guardrails_off '["alignment", "loops", "tests"]'`.
Never raises: a crashing hook must not block the session. Trigger log: state/logs/guardrails.log.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _lib in (os.environ.get("CARLO_LIB"), str(Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain") / "lib")):
    if _lib:
        sys.path.insert(0, _lib)
import carlo_config as cfg  # noqa: E402

FILE_THRESHOLD = 5
COMMAND_THRESHOLD = 3
PROMPT_THRESHOLD = 300
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
CODE = re.compile(r"\.(py|ts|tsx|js|jsx|mjs|go|rs|swift|rb|java|kt|c|cpp|cs|php|sh)$")
TEST = re.compile(r"\b(pytest|unittest|vitest|jest|npm (run )?test|pnpm test|yarn test|node --test|go test|cargo test"
                  r"|make test|rspec|mvn test|gradle test|dotnet test)\b|test_\w+\.py")

ALIGNMENT = ("Alignment guardrail: before acting, restate in one line what the user wants, what is out of scope, "
             "and how we will know it worked. If a point is unclear, ask 1 to 3 short questions.")


def off(part: str) -> bool:
    return part in (cfg.get("security.guardrails_off", []) or [])


def state_file(session: str) -> Path:
    return cfg.state_dir() / "guardrails" / (re.sub(r"[^A-Za-z0-9_-]", "", session) or "unknown")


def load(session: str) -> dict:
    try:
        return json.loads(state_file(session).read_text())
    except (OSError, ValueError):
        return {"files": {}, "commands": {}, "reminded": [], "code_without_test": False, "stop_asked": False}


def save(session: str, state: dict) -> None:
    cfg.atomic_write(state_file(session), json.dumps(state))


def note(session: str, what: str) -> None:
    try:
        log = cfg.state_dir() / "logs" / "guardrails.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M')}\t{session[:8]}\t{what}\n")
    except OSError:
        pass


def mode_prompt(event: dict):
    """Alignment reminder for long prompts, as hook output (dict) or None."""
    if off("alignment") or len(event.get("prompt") or "") < PROMPT_THRESHOLD:
        return None
    note(str(event.get("session_id", "?")), "alignment")
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ALIGNMENT}}


def _edit_reminders(path: str, state: dict) -> list:
    count = state["files"].get(path, 0) + 1
    state["files"] = {**state["files"], path: count}
    if CODE.search(path):
        state["code_without_test"], state["stop_asked"] = True, False
    key = f"file:{path}"
    if count >= FILE_THRESHOLD and key not in state["reminded"] and not off("loops"):
        state["reminded"] = state["reminded"] + [key]
        return [f"Loop guardrail: {Path(path).name} was edited {count} times. Stop: is the method right, and is this still "
                "in scope? Otherwise change approach or ask the user."]
    return []


def _command_reminders(command: str, state: dict) -> list:
    command = re.sub(r"\s+", " ", command).strip()[:300]
    if TEST.search(command):
        state["code_without_test"] = False
    count = state["commands"].get(command, 0) + 1
    state["commands"] = {**state["commands"], command: count}
    key = f"command:{command}"
    if count >= COMMAND_THRESHOLD and key not in state["reminded"] and not off("loops"):
        state["reminded"] = state["reminded"] + [key]
        return [f"Loop guardrail: the same command ran {count} times. Two tries per method: change method or propose "
                "a one minute action to the user."]
    return []


def mode_post(event: dict, state: dict):
    tool, data = event.get("tool_name") or "", event.get("tool_input") or {}
    reminders: list = []
    if tool in EDIT_TOOLS:
        reminders = _edit_reminders(str(data.get("file_path") or data.get("notebook_path") or ""), state)
    elif tool == "Bash":
        reminders = _command_reminders(str(data.get("command") or ""), state)
    if not reminders:
        return None
    for text in reminders:
        note(str(event.get("session_id", "?")), text[:70])
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "\n".join(reminders)}}


def mode_stop(event: dict, state: dict):
    """Reason to block the stop, or None."""
    if off("tests") or event.get("stop_hook_active") or not state.get("code_without_test") or state.get("stop_asked"):
        return None
    state["stop_asked"] = True
    note(str(event.get("session_id", "?")), "stop without test")
    return ("End-of-task guardrail: code changed since the last test run. Run the relevant tests, or say in one line "
            "why that is not needed, before concluding.")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(event, dict):
        return 0
    session = str(event.get("session_id") or "unknown")
    if mode == "prompt":
        out = mode_prompt(event)
        if out:
            print(json.dumps(out, ensure_ascii=False))
        return 0
    state = load(session)
    if mode == "post":
        out = mode_post(event, state)
        save(session, state)
        if out:
            print(json.dumps(out, ensure_ascii=False))
        return 0
    if mode == "stop":
        reason = mode_stop(event, state)
        save(session, state)
        if reason:
            print(reason, file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        cfg.log_error("security.guardrails", exc)
        sys.exit(0)
