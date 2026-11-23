#!/usr/bin/env python3
"""Ask a model behind an OpenAI-compatible endpoint (OpenRouter by default). Python stdlib only.

  openrouter_ask.py --model MODEL [--system TEXT] [--base-url URL] [--max-tokens N] [PROMPT]

The prompt comes from the argument or from stdin. The answer goes to stdout. The key is read from a
file (never from an argument, never printed): $OPENROUTER_KEY_FILE, else ~/.carlo-brain/keys/openrouter.
Point --base-url (or $OPENAI_COMPAT_BASE_URL) at any other OpenAI-compatible server, for example a local one.

What you send goes to that provider: do not pipe in anything you would not paste into their website.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def brain_home() -> Path:
    return Path(os.environ.get("CARLO_BRAIN_HOME") or Path.home() / ".carlo-brain")


def read_key(env: Optional[Dict[str, str]] = None) -> str:
    """API key from the key file. Refuses a missing, empty or group/world-readable file."""
    env = os.environ if env is None else env
    file = Path(env.get("OPENROUTER_KEY_FILE") or brain_home() / "keys" / "openrouter").expanduser()
    if not file.is_file():
        raise SystemExit(f"key file not found: {file} (save the key there, chmod 600)")
    if file.stat().st_mode & 0o077:
        raise SystemExit(f"{file} must not be readable by others (chmod 600)")
    key = file.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit(f"key file is empty: {file}")
    return key


def check_base_url(url: str) -> str:
    """Only https, or http on this machine: a key must not travel in clear over a network."""
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.hostname:
        return url.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname in LOCAL_HOSTS:
        return url.rstrip("/")
    raise SystemExit(f"refusing base URL {url!r}: use https (http only for localhost)")


def build_payload(model: str, prompt: str, system: str = "", max_tokens: int = 1024) -> dict:
    messages: List[dict] = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    return {"model": model, "messages": messages, "max_tokens": max_tokens}


def ask(model: str, prompt: str, key: str, base_url: str = DEFAULT_BASE_URL, system: str = "",
        max_tokens: int = 1024, timeout: int = 120) -> str:
    """One chat completion. Raises RuntimeError with a short reason (never including the key)."""
    request = urllib.request.Request(
        f"{check_base_url(base_url)}/chat/completions",
        data=json.dumps(build_payload(model, prompt, system, max_tokens)).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"provider answered HTTP {err.code}") from err
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise RuntimeError(f"request failed ({type(err).__name__})") from err
    try:
        return str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as err:
        raise RuntimeError("unexpected answer format from the provider") from err


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ask an OpenAI-compatible model (OpenRouter by default).")
    parser.add_argument("prompt", nargs="?", help="prompt text (default: read stdin)")
    parser.add_argument("--model", required=True, help="model id as the provider names it")
    parser.add_argument("--system", default="")
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_COMPAT_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--max-tokens", type=int, default=1024)
    args = parser.parse_args(argv)
    prompt = args.prompt if args.prompt is not None else sys.stdin.read()
    if not prompt.strip():
        print("empty prompt", file=sys.stderr)
        return 2
    try:
        print(ask(args.model, prompt, read_key(), args.base_url, args.system, args.max_tokens))
    except RuntimeError as err:
        print(f"openrouter_ask: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
