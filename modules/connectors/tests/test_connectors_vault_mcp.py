import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import server

TOKEN = "t" * 40


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "Projects").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / ".obsidian").mkdir()
    (root / "Projects" / "plan.md").write_text("# Plan\nship the beta on Friday\n")
    (root / "notes.md").write_text("Remember the milk\n")
    (root / "SECRETS.md").write_text("fake-secret-value\n")
    (root / ".git" / "config.md").write_text("ship the beta (git)\n")
    (root / "api_key.txt").write_text("fake\n")
    outside = tmp_path / "outside.md"
    outside.write_text("outside content")
    os.symlink(outside, root / "link.md")
    return root


@pytest.fixture
def tools(vault):
    return server.VaultTools(vault)


def test_list_hides_hidden_and_denied_files(tools):
    listing = tools.vault_list("")
    assert "Projects/" in listing and "notes.md" in listing
    for hidden in (".git", ".obsidian", "SECRETS.md", "api_key.txt"):
        assert hidden not in listing


def test_read_ok_and_blocked_paths(tools):
    assert "ship the beta" in tools.vault_read("Projects/plan.md")
    for bad in ("../outside.md", "/etc/passwd", "SECRETS.md", ".git/config.md", "link.md", "api_key.txt", "nope.md", "a\x00b"):
        with pytest.raises(server.ToolError):
            tools.vault_read(bad)


def test_traversal_variants_stay_blocked(tools):
    for bad in ("Projects/../../outside.md", "Projects/../../../etc/passwd", "//etc/passwd"):
        with pytest.raises(server.ToolError):
            tools.vault_read(bad)


def test_search_skips_hidden_denied_and_symlink_escape(tools):
    result = tools.vault_search("ship the beta")
    assert "Projects/plan.md:2" in result and ".git" not in result
    assert tools.vault_search("fake-secret-value") == "no match"
    assert tools.vault_search("outside content") == "no match"
    with pytest.raises(server.ToolError):
        tools.vault_search("  ")


def test_write_append_atomic_and_extension_rules(tools, vault):
    assert "wrote" in tools.vault_write("Inbox/new.md", "hello")
    assert (vault / "Inbox" / "new.md").read_text() == "hello"
    tools.vault_append("Inbox/new.md", "\nmore")
    assert (vault / "Inbox" / "new.md").read_text() == "hello\nmore"
    assert not list((vault / "Inbox").glob(".vault-mcp-*"))  # no temp file left behind
    for bad in ("script.py", "../escape.md", ".git/x.md", "SECRETS.md", "Projects"):
        with pytest.raises(server.ToolError):
            tools.vault_write(bad, "x")


def test_write_size_cap(tools):
    with pytest.raises(server.ToolError):
        tools.vault_write("big.md", "x" * (server.MAX_WRITE + 1))


def test_readonly_mode_blocks_writes_and_hides_tools(vault):
    ro = server.VaultTools(vault, readonly=True)
    with pytest.raises(server.ToolError):
        ro.call("vault_write", {"path": "a.md", "content": "x"})
    listed = server.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, ro)["result"]["tools"]
    names = [t["name"] for t in listed]
    assert "vault_write" not in names and "vault_read" in names


def test_rpc_initialize_list_call_and_errors(tools):
    init = server.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}, tools)
    assert init["result"]["protocolVersion"] == "2025-03-26" and "tools" in init["result"]["capabilities"]
    old = server.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999"}}, tools)
    assert old["result"]["protocolVersion"] == server.SUPPORTED_PROTOCOLS[0]
    assert server.handle_rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, tools) is None
    call = server.handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                              "params": {"name": "vault_read", "arguments": {"path": "notes.md"}}}, tools)
    assert call["result"]["isError"] is False and "milk" in call["result"]["content"][0]["text"]
    bad = server.handle_rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                             "params": {"name": "vault_read", "arguments": {"path": "../x"}}}, tools)
    assert bad["result"]["isError"] is True
    wrong_args = server.handle_rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                    "params": {"name": "vault_read", "arguments": {"nope": 1}}}, tools)
    assert wrong_args["result"]["isError"] is True
    unknown = server.handle_rpc({"jsonrpc": "2.0", "id": 5, "method": "wat"}, tools)
    assert unknown["error"]["code"] == -32601
    assert server.handle_rpc("garbage", tools)["error"]["code"] == -32600


@pytest.fixture
def running(tools):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(tools, TOKEN))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def post(url, body, token=TOKEN, raw=None):
    data = raw if raw is not None else json.dumps(body).encode()
    req = urllib.request.Request(url + "/mcp", data=data, method="POST", headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def test_http_requires_the_token(running):
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    assert post(running, msg, token=None)[0] == 401
    assert post(running, msg, token="wrong" * 8)[0] == 401
    status, body = post(running, msg)
    assert status == 200 and len(json.loads(body)["result"]["tools"]) == 5


def test_http_notification_gets_202_and_bad_json_400(running):
    assert post(running, {"jsonrpc": "2.0", "method": "notifications/initialized"})[0] == 202
    status, body = post(running, None, raw=b"{not json")
    assert status == 400 and json.loads(body)["error"]["code"] == -32700


def test_http_health_is_open_and_other_paths_404(running):
    assert urllib.request.urlopen(running + "/health", timeout=5).read() == b"ok"
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(running + "/mcp", timeout=5)
    assert err.value.code == 405
    req = urllib.request.Request(running + "/other", data=b"{}", method="POST", headers={"Authorization": f"Bearer {TOKEN}"})
    with pytest.raises(urllib.error.HTTPError) as err2:
        urllib.request.urlopen(req, timeout=5)
    assert err2.value.code == 404


def test_http_rejects_oversized_body(running):
    try:
        status, _ = post(running, None, raw=b"x" * (server.MAX_BODY + 10))
    except urllib.error.URLError:
        return  # the server refused early and closed the connection while we were still sending
    assert status == 413


def test_token_file_rules(tmp_path):
    f = tmp_path / "tok"
    f.write_text("short")
    f.chmod(0o600)
    with pytest.raises(SystemExit):
        server.read_token(str(f))
    f.write_text(TOKEN + "\n")
    f.chmod(0o644)
    with pytest.raises(SystemExit):
        server.read_token(str(f))
    f.chmod(0o600)
    assert server.read_token(str(f)) == TOKEN
    with pytest.raises(SystemExit):
        server.read_token(str(tmp_path / "missing"))
