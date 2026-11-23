"""OpenRouter connector: the HTTP call is mocked, no network, no real key."""
import io
import json
import os
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "openrouter"))
import openrouter_ask as oa  # noqa: E402

FAKE_KEY = "test-key-not-real"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def key_file(tmp_path, mode=0o600, text=FAKE_KEY):
    path = tmp_path / "key"
    path.write_text(text)
    os.chmod(path, mode)
    return path


def test_read_key_uses_file_and_checks_permissions(tmp_path):
    assert oa.read_key({"OPENROUTER_KEY_FILE": str(key_file(tmp_path))}) == FAKE_KEY
    with pytest.raises(SystemExit, match="chmod 600"):
        oa.read_key({"OPENROUTER_KEY_FILE": str(key_file(tmp_path, 0o644))})
    with pytest.raises(SystemExit, match="empty"):
        oa.read_key({"OPENROUTER_KEY_FILE": str(key_file(tmp_path, text="  \n"))})
    with pytest.raises(SystemExit, match="not found"):
        oa.read_key({"OPENROUTER_KEY_FILE": str(tmp_path / "nope")})


def test_default_key_location_is_the_brain_keys_folder(tmp_path, brain_home):
    (brain_home / "keys").mkdir(parents=True)
    path = brain_home / "keys" / "openrouter"
    path.write_text(FAKE_KEY)
    os.chmod(path, 0o600)
    assert oa.read_key({}) == FAKE_KEY


def test_ask_sends_bearer_key_and_returns_text(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen.update(url=request.full_url, auth=request.get_header("Authorization"),
                    body=json.loads(request.data), method=request.get_method())
        return FakeResponse(json.dumps({"choices": [{"message": {"content": "hello back"}}]}).encode())

    monkeypatch.setattr(oa.urllib.request, "urlopen", fake_urlopen)
    out = oa.ask("some/model", "hi", FAKE_KEY, system="be brief", max_tokens=50)
    assert out == "hello back"
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions" and seen["method"] == "POST"
    assert seen["auth"] == f"Bearer {FAKE_KEY}"
    assert seen["body"] == {"model": "some/model", "max_tokens": 50,
                            "messages": [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]}


def test_errors_never_contain_the_key(monkeypatch):
    def http_error(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "bad", {}, None)

    monkeypatch.setattr(oa.urllib.request, "urlopen", http_error)
    with pytest.raises(RuntimeError, match="HTTP 401") as err:
        oa.ask("m", "hi", FAKE_KEY)
    assert FAKE_KEY not in str(err.value)
    monkeypatch.setattr(oa.urllib.request, "urlopen", lambda r, timeout: FakeResponse(b'{"nope": 1}'))
    with pytest.raises(RuntimeError, match="unexpected answer"):
        oa.ask("m", "hi", FAKE_KEY)


def test_base_url_must_be_https_or_local():
    assert oa.check_base_url("https://example.org/v1/") == "https://example.org/v1"
    assert oa.check_base_url("http://localhost:11434/v1") == "http://localhost:11434/v1"
    for bad in ("http://example.org/v1", "ftp://x", "example.org"):
        with pytest.raises(SystemExit):
            oa.check_base_url(bad)


def test_main_prints_answer_and_rejects_empty_prompt(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_KEY_FILE", str(key_file(tmp_path)))
    monkeypatch.setattr(oa.urllib.request, "urlopen",
                        lambda r, timeout: FakeResponse(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()))
    assert oa.main(["--model", "m", "question"]) == 0
    assert capsys.readouterr().out.strip() == "ok"
    monkeypatch.setattr(sys, "stdin", io.StringIO("  "))
    assert oa.main(["--model", "m"]) == 2
