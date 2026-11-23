#!/usr/bin/env python3
"""A tiny self-hosted MCP server that exposes your Obsidian vault over HTTP (beta). Python stdlib only.

Why: lets Claude (phone app, claude.ai, a remote Claude Code session, another machine) read and
write the same notes as your laptop, through one authenticated endpoint on a server you control.

Tools: vault_list, vault_read, vault_search, vault_write, vault_append. There is no delete tool.
Transport: MCP streamable HTTP, JSON responses, POST /mcp. GET /health answers "ok" without data.

Security model (read this before exposing it):
- Bearer token, read from a file (VAULT_MCP_TOKEN_FILE, chmod 600), compared in constant time.
- Every path is resolved with symlinks and must stay inside the vault. Hidden folders (.git,
  .obsidian) and names matching VAULT_MCP_DENY are invisible and unreadable (default: secrets,
  .env files, key files). Writes are limited to text extensions and a size cap.
- It binds to 127.0.0.1 by default. For remote use put a TLS reverse proxy in front (Caddy,
  Tailscale serve, Cloudflare Tunnel). Never expose the plain HTTP port to the internet.
- VAULT_MCP_READONLY=1 disables the write tools.

Environment: VAULT_MCP_VAULT (vault folder, required), VAULT_MCP_TOKEN_FILE (required),
VAULT_MCP_HOST (127.0.0.1), VAULT_MCP_PORT (8765), VAULT_MCP_READONLY, VAULT_MCP_DENY
(comma separated fnmatch patterns on file names), VAULT_MCP_WRITE_EXT (default .md,.txt,.csv,.json).
"""
from __future__ import annotations

import fnmatch
import hmac
import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_BODY = 1_000_000
MAX_READ = 200_000
MAX_WRITE = 500_000
DEFAULT_DENY = ("secret*", "*secret*", ".env*", "*.pem", "*_key*", "*.key", "id_rsa*", "*password*", "*token*")

TOOLS: List[Dict[str, Any]] = [
    {"name": "vault_list", "description": "List files and folders in a vault folder (non recursive).",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "folder, '' for the root"}}}},
    {"name": "vault_read", "description": "Read a text file of the vault.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "vault_search", "description": "Case-insensitive text search across the vault's text files.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                     "required": ["query"]}},
    {"name": "vault_write", "description": "Create or overwrite a text file (atomic). Disabled in read-only mode.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                     "required": ["path", "content"]}},
    {"name": "vault_append", "description": "Append text to a file (created if missing). Disabled in read-only mode.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "text": {"type": "string"}},
                     "required": ["path", "text"]}},
]
WRITE_TOOLS = {"vault_write", "vault_append"}


class ToolError(Exception):
    """A tool call failed for a reason the caller should see (bad path, denied, too large)."""


class VaultTools:
    """The tool implementations. Pure Python, no HTTP, easy to test."""

    def __init__(self, vault: Path, deny: Sequence[str] = DEFAULT_DENY, readonly: bool = False,
                 write_ext: Sequence[str] = (".md", ".txt", ".csv", ".json")) -> None:
        self.root = Path(os.path.realpath(vault))
        if not self.root.is_dir():
            raise ValueError(f"vault is not a folder: {vault}")
        self.deny = tuple(p.lower() for p in deny)
        self.readonly = readonly
        self.write_ext = tuple(e.lower() for e in write_ext)

    # ----- path safety -----
    def _hidden_or_denied(self, relative: Path) -> bool:
        for part in relative.parts:
            low = part.lower()
            if part.startswith(".") and part not in (".", ".."):
                return True
            if any(fnmatch.fnmatch(low, pattern) for pattern in self.deny):
                return True
        return False

    def resolve(self, raw: str, must_exist: bool = True) -> Path:
        """Absolute path inside the vault, or ToolError. Symlinks are resolved before the check."""
        if not isinstance(raw, str) or "\x00" in raw:
            raise ToolError("invalid path")
        candidate = Path(os.path.realpath(self.root / raw.lstrip("/")))
        try:
            relative = candidate.relative_to(self.root)
        except ValueError:
            raise ToolError("path is outside the vault") from None
        if self._hidden_or_denied(relative):
            raise ToolError("path is not available")
        if must_exist and not candidate.exists():
            raise ToolError("not found")
        return candidate

    def _inside(self, path: Path) -> bool:
        """True if the real location of `path` (symlinks resolved) is inside the vault and not hidden/denied."""
        try:
            relative = Path(os.path.realpath(path)).relative_to(self.root)
        except ValueError:
            return False
        return not self._hidden_or_denied(relative)

    def _rel(self, path: Path) -> str:
        return str(path.relative_to(self.root))

    # ----- tools -----
    def vault_list(self, path: str = "") -> str:
        folder = self.resolve(path)
        if not folder.is_dir():
            raise ToolError("not a folder")
        rows = []
        for child in sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if self._hidden_or_denied(Path(child.name)):
                continue
            rows.append(child.name + ("/" if child.is_dir() else ""))
        return "\n".join(rows) or "(empty)"

    def vault_read(self, path: str) -> str:
        file = self.resolve(path)
        if not file.is_file():
            raise ToolError("not a file")
        if file.stat().st_size > MAX_READ:
            raise ToolError(f"file larger than {MAX_READ} bytes")
        return file.read_text(encoding="utf-8", errors="replace")

    def vault_search(self, query: str, max_results: int = 20) -> str:
        needle = (query or "").strip().lower()
        if not needle:
            raise ToolError("empty query")
        limit = max(1, min(int(max_results), 100))
        hits: List[str] = []
        for folder, dirs, names in os.walk(self.root):
            dirs[:] = sorted(d for d in dirs if not self._hidden_or_denied(Path(d)))
            for name in sorted(names):
                file = Path(folder) / name
                if self._hidden_or_denied(Path(name)) or file.suffix.lower() not in (".md", ".txt", ".csv", ".json"):
                    continue
                try:
                    if not self._inside(file) or file.stat().st_size > MAX_READ:
                        continue  # a symlink that leads outside the vault is never followed
                    for number, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                        if needle in line.lower():
                            hits.append(f"{self._rel(file)}:{number}: {line.strip()[:200]}")
                            break  # one hit per file keeps results diverse
                except OSError:
                    continue
                if len(hits) >= limit:
                    return "\n".join(hits)
        return "\n".join(hits) or "no match"

    def _writable(self, path: str) -> Path:
        if self.readonly:
            raise ToolError("server is read-only")
        file = self.resolve(path, must_exist=False)
        if file.suffix.lower() not in self.write_ext:
            raise ToolError(f"only {', '.join(self.write_ext)} files can be written")
        if file == self.root or file.is_dir():
            raise ToolError("not a file path")
        return file

    def vault_write(self, path: str, content: str) -> str:
        file = self._writable(path)
        if len(content.encode("utf-8")) > MAX_WRITE:
            raise ToolError(f"content larger than {MAX_WRITE} bytes")
        file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=file.parent, prefix=".vault-mcp-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.replace(tmp, file)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return f"wrote {self._rel(file)}"

    def vault_append(self, path: str, text: str) -> str:
        file = self._writable(path)
        if len(text.encode("utf-8")) > MAX_WRITE:
            raise ToolError(f"text larger than {MAX_WRITE} bytes")
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8") as handle:
            handle.write(text)
        return f"appended to {self._rel(file)}"

    def call(self, name: str, arguments: Dict[str, Any]) -> str:
        """Dispatch a tools/call. Raises ToolError for caller-visible problems."""
        if name not in {t["name"] for t in TOOLS}:
            raise ToolError(f"unknown tool: {name}")
        if name in WRITE_TOOLS and self.readonly:
            raise ToolError("server is read-only")
        try:
            return getattr(self, name)(**arguments)
        except TypeError as err:
            raise ToolError(f"bad arguments: {err}") from err


def handle_rpc(message: Any, tools: VaultTools) -> Optional[Dict[str, Any]]:
    """One JSON-RPC message in, response dict out (None for notifications)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    method, ident, params = message.get("method"), message.get("id"), message.get("params") or {}
    if ident is None:  # notification
        return None

    def ok(result: Any) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": ident, "result": result}

    if method == "initialize":
        wanted = params.get("protocolVersion")
        return ok({"protocolVersion": wanted if wanted in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0],
                   "capabilities": {"tools": {}}, "serverInfo": {"name": "carlo-vault", "version": "0.1.0"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        listed = [t for t in TOOLS if not (tools.readonly and t["name"] in WRITE_TOOLS)]
        return ok({"tools": listed})
    if method == "tools/call":
        try:
            text = tools.call(str(params.get("name")), params.get("arguments") or {})
            return ok({"content": [{"type": "text", "text": text}], "isError": False})
        except ToolError as err:
            return ok({"content": [{"type": "text", "text": f"Error: {err}"}], "isError": True})
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"method not found: {method}"}}


def make_handler(tools: VaultTools, token: str):
    """Build the request handler class bound to the tools and the token."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "carlo-vault/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # no content in logs, only status lines
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

        def _send(self, status: int, payload: Optional[Dict[str, Any]] = None, text: Optional[str] = None) -> None:
            body = (json.dumps(payload) if payload is not None else (text or "")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json" if payload is not None else "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorised(self) -> bool:
            header = self.headers.get("Authorization", "")
            given = header[7:] if header.startswith("Bearer ") else ""
            return hmac.compare_digest(given.encode(), token.encode())

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                return self._send(200, text="ok")
            self._send(405, text="use POST /mcp")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/mcp":
                return self._send(404, text="not found")
            if not self._authorised():
                return self._send(401, text="unauthorised")
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self._send(400, text="bad length")
            if size <= 0 or size > MAX_BODY:
                return self._send(413 if size > MAX_BODY else 400, text="bad body size")
            try:
                message = json.loads(self.rfile.read(size))
            except ValueError:
                return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            if isinstance(message, list):  # batch
                replies = [r for r in (handle_rpc(m, tools) for m in message) if r is not None]
                return self._send(200, replies) if replies else self._send(202, text="")
            reply = handle_rpc(message, tools)
            if reply is None:
                return self._send(202, text="")
            self._send(200, reply)

    return Handler


def read_token(path: str) -> str:
    """Token from a file. Refuses empty or group/world readable files."""
    file = Path(path).expanduser()
    if not file.is_file():
        raise SystemExit(f"token file not found: {file}")
    if file.stat().st_mode & 0o077:
        raise SystemExit(f"token file {file} must not be readable by others (chmod 600)")
    token = file.read_text(encoding="utf-8").strip()
    if len(token) < 24:
        raise SystemExit("token must be at least 24 characters (python3 -c 'import secrets;print(secrets.token_urlsafe(32))')")
    return token


def main() -> int:
    vault = os.environ.get("VAULT_MCP_VAULT")
    token_file = os.environ.get("VAULT_MCP_TOKEN_FILE")
    if not vault or not token_file:
        print("set VAULT_MCP_VAULT and VAULT_MCP_TOKEN_FILE (see the header of this file)", file=sys.stderr)
        return 2
    deny = tuple(p.strip() for p in os.environ.get("VAULT_MCP_DENY", "").split(",") if p.strip()) or DEFAULT_DENY
    ext = tuple(e.strip() for e in os.environ.get("VAULT_MCP_WRITE_EXT", ".md,.txt,.csv,.json").split(",") if e.strip())
    tools = VaultTools(Path(vault).expanduser(), deny, os.environ.get("VAULT_MCP_READONLY") == "1", ext)
    host, port = os.environ.get("VAULT_MCP_HOST", "127.0.0.1"), int(os.environ.get("VAULT_MCP_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), make_handler(tools, read_token(token_file)))
    print(f"vault MCP on http://{host}:{port}/mcp (vault: {tools.root}, {'read-only' if tools.readonly else 'read-write'})", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
