"""other-agents: `carlo context`, `carlo connect codex|gemini`, the guard adapter and the boot hook.

Fake HOME (support.BrainEnv), no network, fake `codex`, `gemini` and clipboard executables on PATH.
"""
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
import support  # noqa: E402

SRC = Path(support.module_src("other-agents"))
import agents_connect  # noqa: E402
import context  # noqa: E402
import guard_adapter  # noqa: E402
import carlo_cli  # noqa: E402

FAKE_TOOL = """#!/bin/sh
echo "$@" >> "$FAKE_LOG"
if [ "$2" = "list" ]; then [ -f "$FAKE_STATE" ] && echo playwright; exit 0; fi
if [ "$2" = "add" ]; then touch "$FAKE_STATE"; fi
if [ "$2" = "remove" ]; then rm -f "$FAKE_STATE"; fi
exit 0
"""
FAKE_CLIP = """#!/bin/sh
cat > "$FAKE_CLIP_OUT"
"""
DASHES = (chr(0x2014), chr(0x2013))


class Base(unittest.TestCase):
    def setUp(self):
        self.env = support.BrainEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        self.saved = {k: os.environ.get(k) for k in ("CODEX_HOME", "PATH", "FAKE_LOG", "FAKE_STATE", "FAKE_CLIP_OUT")}
        os.environ.pop("CODEX_HOME", None)
        self.addCleanup(self.restore_env)
        self.bin = self.env.root / "bin"
        self.bin.mkdir()
        os.environ.update(PATH=f"{self.bin}{os.pathsep}{Path(sys.executable).parent}{os.pathsep}/usr/bin{os.pathsep}/bin",
                          FAKE_LOG=str(self.env.root / "log"), FAKE_STATE=str(self.env.root / "registered"),
                          FAKE_CLIP_OUT=str(self.env.root / "clip"))
        self.codex_dir, self.gemini_dir = self.env.home / ".codex", self.env.home / ".gemini"

    def restore_env(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def fake(self, name, body=FAKE_TOOL):
        (self.bin / name).write_text(body)
        (self.bin / name).chmod(0o755)

    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = carlo_cli.main(list(argv))
        return code, out.getvalue()

    def install(self, *modules):
        code, out = self.run_cli("add", *modules)
        self.assertEqual(code, 0, out)

    def system_file(self, name):
        return self.env.vault / "00_System" / name


class ContextTest(Base):
    def test_paste_prompt_has_everything_and_respects_cap(self):
        self.system_file("SYSTEM_PROMPT.md").write_text("RULE-ALPHA " + "x" * 50000, encoding="utf-8")
        self.system_file("MAP.md").write_text("MAP-BETA person", encoding="utf-8")
        log = self.system_file("SESSION_LOG.md")
        log.write_text(log.read_text(encoding="utf-8") + "\n### 2026-11-20 ~10h00 (cli) [demo]\nShipped the demo.\n", encoding="utf-8")
        text = context.paste_prompt(max_chars=6000)
        self.assertLessEqual(len(text), 6000)
        for needle in ("RULE-ALPHA", "MAP-BETA", "RECENT SESSIONS", "Shipped the demo", "cut to fit"):
            self.assertIn(needle, text)

    def test_cli_context_boot_and_copy(self):
        code, out = self.run_cli("context")
        self.assertEqual(code, 0, out)
        self.assertIn("=== SYSTEM PROMPT ===", out)
        code, out = self.run_cli("context", "--boot")
        self.assertEqual(code, 0, out)
        self.assertIn("# Context (injected by the carlo-brain memory module)", out)
        self.fake("pbcopy", FAKE_CLIP)
        code, out = self.run_cli("context", "--copy")
        self.assertEqual(code, 0, out)
        self.assertIn("copied", out)
        self.assertIn("=== MAP ===", (self.env.root / "clip").read_text(encoding="utf-8"))

    def test_copy_without_clipboard_tool_prints_instead(self):
        self.assertIsNone(context.copy_to_clipboard("x", which=lambda _t: None))

    def test_no_vault_message(self):
        self.system_file("SYSTEM_PROMPT.md").unlink()
        code, out = self.run_cli("context")
        self.assertEqual(code, 1)
        self.assertIn("no vault found", out)

    def test_no_dash_characters_in_generated_text(self):
        text = context.paste_prompt() + context.instruction_block(False) + context.instruction_block(True)
        self.assertFalse(any(d in text for d in DASHES))


class ConnectCodexTest(Base):
    def setUp(self):
        super().setUp()
        self.install("memory", "security", "agents-skills")

    def connect(self, *extra):
        code, out = self.run_cli("connect", "codex", *extra)
        self.assertEqual(code, 0, out)
        return out

    def test_connect_writes_block_hooks_and_skills_then_removes_only_ours(self):
        self.codex_dir.mkdir()
        agents_md = self.codex_dir / "AGENTS.md"
        agents_md.write_text("# My own rules\nBe kind.\n", encoding="utf-8")
        hooks_json = self.codex_dir / "hooks.json"
        hooks_json.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}), encoding="utf-8")
        own = self.env.home / ".agents" / "skills" / "carlo-cto"
        own.mkdir(parents=True)
        (own / "SKILL.md").write_text("mine", encoding="utf-8")
        out = self.connect()
        self.assertIn("/hooks", out)
        text = agents_md.read_text(encoding="utf-8")
        self.assertIn("Be kind.", text)
        self.assertIn("<!-- carlo-brain:begin -->", text)
        self.assertIn("## SYSTEM_PROMPT.md", text)
        self.assertNotIn("@" + str(self.env.vault), text, "Codex has no import syntax: the copy must be inline")
        self.assertIn("carlo context --boot", text)
        self.assertLess(len(text.encode("utf-8")), 32 * 1024)
        hooks = json.loads(hooks_json.read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(sorted(hooks), ["PreToolUse", "SessionStart", "Stop"])
        self.assertEqual(len(hooks["PreToolUse"]), 2)
        self.assertEqual(hooks["PreToolUse"][0]["hooks"][0]["timeout"], 10)
        self.assertIn("session_start.py codex", hooks["SessionStart"][0]["hooks"][0]["command"])
        skill = self.env.home / ".agents" / "skills" / "carlo-researcher" / "SKILL.md"
        self.assertTrue(skill.is_file())
        self.assertTrue(skill.read_text(encoding="utf-8").startswith("---\nname: carlo-researcher\ndescription: "))
        self.assertTrue((self.env.home / ".agents" / "skills" / "carlo-explainer" / "references" / "rules.md").is_file())
        self.assertEqual((own / "SKILL.md").read_text(encoding="utf-8"), "mine", "a skill that is not ours is never touched")
        self.assertTrue(list(self.codex_dir.glob("AGENTS.md.bak-carlo-*")))
        code, out = self.run_cli("connect", "codex", "--remove")
        self.assertEqual(code, 0, out)
        self.assertEqual(agents_md.read_text(encoding="utf-8").strip(), "# My own rules\nBe kind.")
        hooks = json.loads(hooks_json.read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(list(hooks), ["Stop"])
        self.assertFalse(skill.exists())
        self.assertEqual((own / "SKILL.md").read_text(encoding="utf-8"), "mine")

    def test_connect_is_idempotent(self):
        self.connect()
        before = {p: p.read_text(encoding="utf-8") for p in (self.codex_dir / "AGENTS.md", self.codex_dir / "hooks.json")}
        backups = sorted(self.codex_dir.glob("*.bak-carlo-*"))
        self.connect()
        self.assertEqual(before, {p: p.read_text(encoding="utf-8") for p in before})
        self.assertEqual(backups, sorted(self.codex_dir.glob("*.bak-carlo-*")), "no change means no new backup")
        self.assertEqual(before[self.codex_dir / "AGENTS.md"].count("carlo-brain:begin"), 1)

    def test_file_created_by_us_is_deleted_on_remove(self):
        self.connect()
        self.run_cli("connect", "codex", "--remove")
        self.assertFalse((self.codex_dir / "AGENTS.md").exists())

    def test_status_and_doctor(self):
        code, out = self.run_cli("connect", "codex", "--status")
        self.assertEqual(code, 1)
        self.assertIn("not connected", out)
        self.assertEqual(agents_connect.check(), [])
        self.connect()
        code, out = self.run_cli("connect", "codex", "--status")
        self.assertEqual(code, 0, out)
        self.assertIn("3/3 hooks", out)
        code, out = self.run_cli("doctor")
        self.assertIn("codex: instruction block", out)
        self.assertNotIn("[FAIL] codex", out)
        (self.codex_dir / "hooks.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.run_cli("connect", "codex", "--status")[0], 1)

    def test_codex_home_variable_is_honoured(self):
        os.environ["CODEX_HOME"] = str(self.env.root / "elsewhere")
        self.connect("--no-agents")
        self.assertTrue((self.env.root / "elsewhere" / "AGENTS.md").is_file())
        self.assertFalse(self.codex_dir.exists())

    def test_override_file_is_flagged(self):
        self.codex_dir.mkdir()
        (self.codex_dir / "AGENTS.override.md").write_text("override", encoding="utf-8")
        self.assertIn("AGENTS.override.md", self.connect())

    def test_broken_hooks_file_changes_nothing(self):
        self.codex_dir.mkdir()
        (self.codex_dir / "hooks.json").write_text("{not json", encoding="utf-8")
        code, out = self.run_cli("connect", "codex")
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", out)
        self.assertFalse((self.codex_dir / "AGENTS.md").exists())
        self.assertEqual((self.codex_dir / "hooks.json").read_text(encoding="utf-8"), "{not json")

    def test_no_hooks_and_no_agents_flags(self):
        self.connect("--no-hooks", "--no-agents")
        self.assertTrue((self.codex_dir / "AGENTS.md").is_file())
        self.assertFalse((self.codex_dir / "hooks.json").exists())
        self.assertFalse((self.env.home / ".agents").exists())

    def test_refresh_follows_the_vault(self):
        self.connect("--no-agents")
        self.system_file("SYSTEM_PROMPT.md").write_text("BRAND-NEW-RULE " + "y" * 40000, encoding="utf-8")
        code, out = self.run_cli("context", "--refresh")
        self.assertEqual(code, 0, out)
        self.assertIn("codex: block regenerated", out)
        text = (self.codex_dir / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("BRAND-NEW-RULE", text)
        self.assertLess(len(text.encode("utf-8")), 24000, "the copy is capped")
        self.assertIn("cut to fit", text)
        self.assertIn("block already up to date", self.run_cli("context", "--refresh")[1])

    def test_mcp_needs_the_browser_marker_and_the_binary(self):
        self.fake("codex")
        self.assertIn("run `carlo connect browser` first", self.connect("--mcp", "--no-agents"))
        marker = self.env.brain / "config.d" / "browser.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"server": "playwright", "version": "0.0.30"}), encoding="utf-8")
        self.assertIn("registered the playwright MCP server in codex", self.connect("--mcp", "--no-agents"))
        log = (self.env.root / "log").read_text(encoding="utf-8")
        self.assertIn("mcp add playwright -- npx @playwright/mcp@0.0.30", log)
        self.assertIn("already registered", self.connect("--mcp", "--no-agents"))
        self.assertEqual(log.count("mcp add"), 1)
        out = self.run_cli("connect", "codex", "--remove")[1]
        self.assertIn("delete its [mcp_servers.playwright] table yourself", out)

    def test_removing_the_module_disconnects(self):
        self.install("other-agents")
        self.connect()
        self.assertTrue((self.codex_dir / "hooks.json").exists())
        code, out = self.run_cli("remove", "other-agents")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.codex_dir / "AGENTS.md").exists())
        self.assertNotIn("SessionStart", (self.codex_dir / "hooks.json").read_text(encoding="utf-8"))

    def test_guards_are_skipped_without_the_security_module(self):
        self.run_cli("remove", "security")
        self.connect("--no-agents")
        hooks = json.loads((self.codex_dir / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(list(hooks), ["SessionStart"])


class ConnectGeminiTest(Base):
    def setUp(self):
        super().setUp()
        self.install("memory", "security", "agents-skills")

    def connect(self, *extra):
        code, out = self.run_cli("connect", "gemini", *extra)
        self.assertEqual(code, 0, out)
        return out

    def test_connect_uses_imports_and_gemini_hooks_and_commands(self):
        self.gemini_dir.mkdir()
        settings = self.gemini_dir / "settings.json"
        settings.write_text(json.dumps({"theme": "dark", "mcpServers": {"x": {"command": "x"}}}), encoding="utf-8")
        self.connect()
        text = (self.gemini_dir / "GEMINI.md").read_text(encoding="utf-8")
        self.assertIn(f"@{self.env.vault}/00_System/SYSTEM_PROMPT.md", text)
        self.assertIn(f"@{self.env.vault}/00_System/MAP.md", text)
        data = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(data["theme"], "dark")
        self.assertIn("x", data["mcpServers"])
        self.assertEqual(sorted(data["hooks"]), ["BeforeTool", "SessionStart"])
        first = data["hooks"]["BeforeTool"][0]
        self.assertIn("read_file", first["matcher"])
        self.assertEqual(first["hooks"][0]["timeout"], 10000, "Gemini timeouts are milliseconds")
        command = self.gemini_dir / "commands" / "carlo" / "cto.toml"
        body = command.read_text(encoding="utf-8")
        self.assertIn("{{args}}", body)
        self.assertIn("carlo-brain:managed", body)
        try:
            import tomllib
        except ImportError:
            tomllib = None
        if tomllib:
            parsed = tomllib.loads(body)
            self.assertIn("prompt", parsed)
            self.assertTrue(parsed["description"])
        self.run_cli("connect", "gemini", "--remove")
        data = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(data, {"theme": "dark", "mcpServers": {"x": {"command": "x"}}})
        self.assertFalse((self.gemini_dir / "commands" / "carlo").exists())
        self.assertFalse((self.gemini_dir / "GEMINI.md").exists())

    def test_inline_option_copies_instead_of_importing(self):
        self.connect("--inline", "--no-agents")
        text = (self.gemini_dir / "GEMINI.md").read_text(encoding="utf-8")
        self.assertNotIn("@" + str(self.env.vault), text)
        self.assertIn("## MAP.md", text)

    def test_injection_syntax_in_a_prompt_is_defused(self):
        text = agents_connect.gemini_command_text("t", {"description": "d"}, "run !{rm -rf x} and @{secret} and '''")
        self.assertNotIn("!{", text)
        self.assertNotIn("@{", text)
        self.assertEqual(text.count("'''"), 2)

    def test_user_command_with_same_name_is_kept(self):
        mine = self.gemini_dir / "commands" / "carlo" / "cto.toml"
        mine.parent.mkdir(parents=True)
        mine.write_text('prompt = "mine"\n', encoding="utf-8")
        self.connect()
        self.assertEqual(mine.read_text(encoding="utf-8"), 'prompt = "mine"\n')
        self.run_cli("connect", "gemini", "--remove")
        self.assertTrue(mine.exists())

    def test_mcp_registration_and_removal(self):
        self.fake("gemini")
        marker = self.env.brain / "config.d" / "browser.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"server": "playwright", "version": "latest"}), encoding="utf-8")
        self.connect("--mcp", "--no-agents")
        self.assertIn("mcp add -s user playwright npx @playwright/mcp@latest", (self.env.root / "log").read_text(encoding="utf-8"))
        self.assertIn("playwright MCP removed", self.run_cli("connect", "gemini", "--remove")[1])
        self.assertIn("mcp remove -s user playwright", (self.env.root / "log").read_text(encoding="utf-8"))


class AdapterAndHookTest(Base):
    def setUp(self):
        super().setUp()
        self.install("memory", "security", "other-agents")

    def guard(self, agent, script, payload, *args):
        result = subprocess.run([sys.executable, "-I", str(self.env.brain / "other-agents" / "guard_adapter.py"), agent, script, *args],
                                input=json.dumps(payload), capture_output=True, text=True)
        return result.returncode, result.stderr

    def test_normalize_gemini_and_codex(self):
        self.assertEqual(guard_adapter.normalize("gemini", {"tool_name": "run_shell_command", "tool_input": {"command": "ls"}})["tool_name"], "Bash")
        read = guard_adapter.normalize("gemini", {"tool_name": "read_file", "tool_input": {"file_path": "a.txt"}})
        self.assertEqual((read["tool_name"], read["tool_input"]["file_path"]), ("Read", "a.txt"))
        patch = guard_adapter.normalize("codex", {"tool_name": "apply_patch", "tool_input": {"command": "*** Update File: x"}})
        self.assertEqual(patch["tool_name"], "Write")
        same = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        self.assertEqual(guard_adapter.normalize("codex", same), same)

    def test_secret_reads_are_blocked_for_both_tools(self):
        code, why = self.guard("gemini", "block_secret_reads.py", {"tool_name": "read_file", "tool_input": {"file_path": "/home/me/.env"}})
        self.assertEqual(code, 2)
        self.assertIn("Blocked by block_secret_reads.py", why)
        self.assertEqual(self.guard("gemini", "block_secret_reads.py", {"tool_name": "run_shell_command", "tool_input": {"command": "cat ~/.zshrc"}})[0], 2)
        self.assertEqual(self.guard("codex", "block_secret_reads.py", {"tool_name": "Bash", "tool_input": {"command": "cat .env"}})[0], 2)
        patch = {"tool_name": "apply_patch", "tool_input": {"command": "*** Update File: /x/.env\n+A=1"}}
        self.assertEqual(self.guard("codex", "block_secret_reads.py", patch)[0], 2)

    def test_harmless_calls_pass(self):
        self.assertEqual(self.guard("gemini", "block_secret_reads.py", {"tool_name": "read_file", "tool_input": {"file_path": "README.md"}})[0], 0)
        self.assertEqual(self.guard("codex", "block_secret_reads.py", {"tool_name": "Bash", "tool_input": {"command": "ls -la"}})[0], 0)
        self.assertEqual(self.guard("codex", "send_guard.py", {"tool_name": "Bash", "tool_input": {"command": "ls"}}, "tool")[0], 0)

    def test_adapter_refuses_unknown_scripts_and_missing_guard(self):
        self.assertEqual(self.guard("codex", "../evil.py", {})[0], 0)
        code, _ = self.guard("codex", "block_secret_reads.py", {"tool_name": "Bash", "tool_input": {"command": "cat .env"}})
        self.assertEqual(code, 2)
        self.run_cli("remove", "security")
        code, why = self.guard("codex", "block_secret_reads.py", {"tool_name": "Bash", "tool_input": {"command": "cat .env"}})
        self.assertEqual(code, 0)
        self.assertIn("guard skipped", why)

    def test_session_start_hook_prints_boot_context(self):
        for tool in ("codex", "gemini"):
            result = subprocess.run([sys.executable, "-I", str(self.env.brain / "other-agents" / "session_start.py"), tool],
                                    input=json.dumps({"source": "startup", "cwd": str(self.env.root)}), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)["hookSpecificOutput"]
            self.assertIn("# Context (injected by the carlo-brain memory module)", payload["additionalContext"])

    def test_session_start_survives_garbage_input(self):
        result = subprocess.run([sys.executable, "-I", str(self.env.brain / "other-agents" / "session_start.py"), "codex"],
                                input="not json", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
