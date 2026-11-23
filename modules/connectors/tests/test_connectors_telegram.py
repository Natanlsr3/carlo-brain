import json
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "remote-control"))
import telegram_bridge as tb  # noqa: E402

BOT = "123456:ABC-fake-bot-credential"


class FakeTelegram:
    """A tiny local Bot API: scripted updates in, recorded calls out."""

    def __init__(self, updates):
        self.updates, self.calls = list(updates), []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                size = int(self.headers["Content-Length"])
                params = dict(urllib.parse.parse_qsl(self.rfile.read(size).decode()))
                method = self.path.rsplit("/", 1)[1]
                outer.calls.append((method, params))
                if not self.path.startswith(f"/bot{BOT}/"):
                    body = {"ok": False, "description": "unauthorized"}
                elif method == "getUpdates":
                    offset = int(params.get("offset", 0))
                    body = {"ok": True, "result": [u for u in outer.updates if u["update_id"] >= offset]}
                else:
                    body = {"ok": True, "result": {}}
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def sent(self):
        return [p["text"] for m, p in self.calls if m == "sendMessage"]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def update(uid, text, user=111, chat_type="private"):
    return {"update_id": uid, "message": {"from": {"id": user, "first_name": "Me"}, "chat": {"id": user, "type": chat_type}, "text": text}}


@pytest.fixture
def cfg(tmp_path):
    return {**tb.DEFAULTS, "allowed_user_ids": [111], "workdir": str(tmp_path), "keep_session": True}


class FakeRun:
    """Stands in for subprocess.run: records the command, stdin and env."""

    def __init__(self, out="the answer", code=0, err=""):
        self.calls, self.out, self.code, self.err = [], out, code, err

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, self.code, self.out, self.err)


def test_config_requires_integer_ids_and_sane_timeout(tmp_path):
    f = tmp_path / "c.json"
    f.write_text('{"allowed_user_ids": ["111"]}')
    with pytest.raises(ValueError):
        tb.load_config(f)
    f.write_text('{"allowed_user_ids": [true]}')
    with pytest.raises(ValueError):
        tb.load_config(f)
    f.write_text('{"allowed_user_ids": [1], "timeout": 1}')
    with pytest.raises(ValueError):
        tb.load_config(f)
    f.write_text('{"allowed_user_ids": [1]}')
    assert tb.load_config(f)["allowed_tools"] == "Read,Grep,Glob,WebSearch,WebFetch"  # read only, no shell by default
    assert tb.load_config(tmp_path / "missing.json")["allowed_user_ids"] == []


def test_token_file_rules(tmp_path):
    f = tmp_path / "bot"
    f.write_text(BOT)
    f.chmod(0o644)
    with pytest.raises(SystemExit):
        tb.read_token({"TELEGRAM_BOT_TOKEN_FILE": str(f)})
    f.chmod(0o600)
    assert tb.read_token({"TELEGRAM_BOT_TOKEN_FILE": str(f)}) == BOT
    f.write_text("not-a-bot-credential")
    with pytest.raises(SystemExit):
        tb.read_token({"TELEGRAM_BOT_TOKEN_FILE": str(f)})
    with pytest.raises(SystemExit):
        tb.read_token({"TELEGRAM_BOT_TOKEN_FILE": str(tmp_path / "none")})


def test_clean_env_drops_key_like_variables_but_keeps_subscription_login():
    env = {"PATH": "/bin", "ANTHROPIC_API_KEY": "x", "OPENAI_API_KEY": "x", "MY_SECRET": "x", "TELEGRAM_BOT_TOKEN": "x",
           "CLAUDE_CODE_OAUTH_TOKEN": "keep", "HOME": "/h"}
    assert tb.clean_env(env) == {"PATH": "/bin", "CLAUDE_CODE_OAUTH_TOKEN": "keep", "HOME": "/h"}


def test_split_message_respects_limit_and_loses_nothing():
    text = ("para one " * 30 + "\n\n") * 6
    parts = tb.split_message(text, 400)
    assert all(len(p) <= 400 for p in parts)
    assert "".join(p.replace(" ", "").replace("\n", "") for p in parts) == text.replace(" ", "").replace("\n", "")
    assert tb.split_message("  ", 100) == ["(empty answer)"]
    assert tb.split_message("x" * 1000, 300)[0] == "x" * 300  # no break point: hard cut


def test_only_allowed_private_text_messages_are_accepted():
    allowed = [111]
    assert tb.accepted(update(1, "hi"), allowed)
    assert tb.accepted(update(1, "hi", user=999), allowed) is None          # stranger
    assert tb.accepted(update(1, "hi", chat_type="group"), allowed) is None  # group chat
    assert tb.accepted({"update_id": 1, "message": {"from": {"id": 111}, "chat": {"type": "private"}}}, allowed) is None  # no text
    assert tb.accepted({"update_id": 1}, allowed) is None


def test_ask_claude_command_env_and_resume(cfg):
    run = FakeRun()
    assert tb.ask_claude("question?", cfg, resume=True, runner=run) == "the answer"
    cmd, kw = run.calls[0]
    assert cmd[:3] == ["claude", "-p", "--continue"] and "--allowedTools" in cmd and "Bash" not in cmd[-1]
    assert kw["input"] == "question?" and kw["cwd"] == Path(cfg["workdir"])
    assert not any("KEY" in k for k in kw["env"])
    tb.ask_claude("q", cfg, resume=False, runner=run)
    assert "--continue" not in run.calls[1][0]


def test_ask_claude_failures_are_short_messages(cfg):
    assert tb.ask_claude("q", cfg, True, FakeRun(code=1, err="boom\n  trace")).startswith("claude failed: boom trace")

    def timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    assert "Timed out" in tb.ask_claude("q", cfg, True, timeout)

    def missing(cmd, **kw):
        raise FileNotFoundError("claude")

    assert "Could not start claude" in tb.ask_claude("q", cfg, True, missing)


def test_bridge_end_to_end_answers_only_allowed_and_persists_offset(tmp_path, cfg):
    fake = FakeTelegram([update(1, "what is on my plate?"), update(2, "give me secrets", user=999), update(3, "/status")])
    try:
        run = FakeRun(out="Three things.")
        bridge = tb.Bridge(tb.Telegram(BOT, fake.base), cfg, tmp_path / "state", run)
        assert bridge.step(wait=1) == 2
        sent = fake.sent()
        assert sent[0] == "Three things." and sent[1].startswith("model=sonnet")
        assert len(run.calls) == 1                      # the stranger never reached claude
        assert (tmp_path / "state" / "telegram_offset").read_text() == "4"
        again = tb.Bridge(tb.Telegram(BOT, fake.base), cfg, tmp_path / "state", run)
        assert again.offset == 4 and again.step(wait=1) == 0   # restart does not replay old commands
        log = (tmp_path / "state" / "telegram_bridge.log").read_text()
        assert "what is on my plate" not in log and "user=111 chars=20 ok" in log   # no content in the log
    finally:
        fake.close()


def test_new_command_starts_a_fresh_conversation(tmp_path, cfg):
    fake = FakeTelegram([update(1, "first"), update(2, "/new"), update(3, "second")])
    try:
        run = FakeRun()
        bridge = tb.Bridge(tb.Telegram(BOT, fake.base), cfg, tmp_path / "s", run)
        bridge.step(wait=1)
        flags = ["--continue" in c[0] for c in run.calls]
        assert flags == [True, False]                    # after /new the next question starts fresh, then continues
    finally:
        fake.close()


def test_api_errors_never_leak_the_token(tmp_path):
    fake = FakeTelegram([])
    try:
        api = tb.Telegram("999:wrong-credential", fake.base)
        with pytest.raises(RuntimeError) as err:
            api.updates(0, wait=1)
        assert "wrong-credential" not in str(err.value) and "unauthorized" in str(err.value)
    finally:
        fake.close()
    dead = tb.Telegram(BOT, "http://127.0.0.1:9")
    with pytest.raises(RuntimeError) as err2:
        dead.updates(0, wait=1)
    assert BOT not in str(err2.value)


def test_discover_lists_senders(capsys, tmp_path):
    fake = FakeTelegram([update(1, "hello", user=42)])
    try:
        assert tb.discover(tb.Telegram(BOT, fake.base)) == 0
        assert capsys.readouterr().out.startswith("42\tMe")
    finally:
        fake.close()


def test_run_refuses_to_start_without_allow_list(tmp_path, monkeypatch, capsys):
    tokenfile = tmp_path / "bot"
    tokenfile.write_text(BOT)
    tokenfile.chmod(0o600)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(tokenfile))
    monkeypatch.setenv("CARLO_BRAIN_HOME", str(tmp_path / "home"))
    assert tb.main(["run"]) == 78
    assert "allowed_user_ids is empty" in capsys.readouterr().err
    assert tb.main([]) == 2
