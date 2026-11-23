"""Tests for the security module."""
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
import support  # noqa: E402

SRC = Path(support.module_src("security"))

import audit  # noqa: E402
import block_secret_reads as bsr  # noqa: E402
import detectors  # noqa: E402
import guardrails  # noqa: E402
import send_guard  # noqa: E402
import targets  # noqa: E402
import carlo_config as cfg  # noqa: E402

KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
IBAN = "GB82 WEST 1234 5698 7654 32"
CARD = "4111 1111 1111 1111"


class BlockSecretReadsTest(unittest.TestCase):
    def blocked(self, command):
        return bsr.blocked("Bash", {"command": command})

    def test_blocks_secret_files_and_env_dumps(self):
        for command in ("cat ~/.zshrc", "cat .env", "sed -n 1,5p ~/.zprofile", "cat .env.local", "cat ~/.ssh/id_rsa",
                        "grep TOKEN ~/.aws/credentials", "cat secrets.md", "env", "printenv", "export",
                        "echo $OPENAI_API_KEY", "cat server_key.pem", "cat ~/.carlo-brain/keys/anthropic",
                        "x=1; env | sort", "declare -x"):
            self.assertTrue(self.blocked(command), command)

    def test_allows_normal_commands(self):
        for command in ("ls -la", "git status", "cat README.md", "cat .env.example", "python3 -m pytest",
                        "test -s ~/.carlo-brain/keys/anthropic && echo present", "env FOO=1 python3 run.py",
                        "MY_KEY_FILE=~/.carlo-brain/keys/x python3 tool.py", "echo $HOME", "grep -r environment docs/"):
            self.assertFalse(self.blocked(command), command)

    def test_file_tools(self):
        self.assertTrue(bsr.blocked("Read", {"file_path": "/home/u/.env"}))
        self.assertTrue(bsr.blocked("Grep", {"path": "/home/u/.ssh/", "pattern": "x"}))
        self.assertTrue(bsr.blocked("Write", {"file_path": "/home/u/.npmrc"}))
        self.assertFalse(bsr.blocked("Read", {"file_path": "/home/u/project/main.py"}))

    def test_hook_exit_codes(self):
        with support.BrainEnv() as env:
            script = SRC / "block_secret_reads.py"
            res = support.run_script(script, json.dumps({"tool_name": "Bash", "tool_input": {"command": "cat .env"}}))
            self.assertEqual(res.returncode, 2)
            self.assertIn("Blocked", res.stderr)
            ok = support.run_script(script, json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}))
            self.assertEqual(ok.returncode, 0)

    def test_unreadable_input_fails_open_by_default_and_closed_on_request(self):
        script = SRC / "block_secret_reads.py"
        for raw in ("", "garbage", "[1]"):
            with support.BrainEnv() as env:
                res = support.run_script(script, raw, env=env.env())
                self.assertEqual(res.returncode, 0, raw)
                self.assertIn("unreadable input", res.stderr)
            with support.BrainEnv() as env:
                cfg.save_config({"security": {"fail_closed": True}})
                self.assertEqual(support.run_script(script, raw, env=env.env()).returncode, 2, raw)

    def test_bare_word_secret_is_not_blocked_but_secret_paths_are(self):
        for command in ("grep -r secret src/", "grep -rn secrets docs/ | head", "echo secret plan"):
            self.assertFalse(self.blocked(command), command)
        self.assertFalse(bsr.blocked("Grep", {"pattern": "secret", "path": "src/"}))
        for name in ("SECRET" + "S.md", "secrets.json", ".en" + "v", "server_key.pem"):
            self.assertTrue(self.blocked(f"cat {name}"), name)
        for command in ("ls ~/secrets/", "cat ~/secret", "cat ./secrets"):
            self.assertTrue(self.blocked(command), command)
        self.assertTrue(bsr.blocked("Read", {"file_path": "/home/u/SECRET" + "S.md"}))


class DetectorsTest(unittest.TestCase):
    def test_finds_keys_without_value(self):
        found = detectors.scan(f"line one\nmy key is {KEY} ok")
        self.assertEqual(found[0].type, "API key (sk-)")
        self.assertEqual((found[0].line, found[0].column), (2, 11))
        self.assertNotIn(KEY, repr(found))

    def test_iban_and_card_checksums(self):
        self.assertEqual([f.type for f in detectors.scan(f"pay to {IBAN}")], ["IBAN"])
        self.assertEqual(detectors.scan("pay to GB82 WEST 1234 5698 7654 33"), [])
        self.assertEqual([f.type for f in detectors.scan(f"card {CARD}")], ["payment card number"])
        self.assertEqual(detectors.scan("order 4111 1111 1111 1112"), [])

    def test_clean_text(self):
        self.assertEqual(detectors.scan("Hi, the meeting is at 3pm. Call 555-0100. Version 1.2.3"), [])

    def test_password_and_pem_and_extra(self):
        types = [f.type for f in detectors.scan("password: hunter22x\n-----BEGIN RSA PRIVATE KEY-----")]
        self.assertEqual(types, ["password", "private key (PEM)"])
        self.assertEqual(detectors.scan("id CUST-12345678", {"customer id": "CUST-[0-9]{8}"})[0].type, "customer id")
        self.assertEqual(detectors.scan("x", {"bad": "(unclosed"}), [])


class TargetsTest(unittest.TestCase):
    def test_is_send(self):
        self.assertTrue(targets.is_send("mcp__mail__send_message", {}))
        self.assertTrue(targets.is_send("mcp__chat__post_message", {}))
        self.assertTrue(targets.is_send("mcp__cal__create_event", {}))
        self.assertFalse(targets.is_send("mcp__mail__search_messages", {}))
        self.assertFalse(targets.is_send("mcp__chat__list_posts", {}))
        self.assertTrue(targets.is_send("Bash", {"command": "curl -X POST https://api.example.com/x -d 'a=1'"}))
        self.assertFalse(targets.is_send("Bash", {"command": "curl -X POST http://localhost:3000/x -d 'a=1'"}))
        self.assertFalse(targets.is_send("Bash", {"command": "curl https://example.com"}))
        self.assertTrue(targets.is_send("Bash", {"command": "gh issue comment 3 --body hi"}))
        self.assertTrue(targets.is_send("Custom", {}, extra_tools=("Custom",)))
        self.assertFalse(targets.is_send("Read", {"file_path": "x"}))


class SendGuardTest(unittest.TestCase):
    def event(self, body, session="s1"):
        return {"tool_name": "mcp__mail__send_message", "session_id": session, "tool_input": {"to": "a@b.example", "body": body}}

    def test_blocks_and_audits_without_leaking(self):
        with support.BrainEnv() as env:
            res = support.run_script(SRC / "send_guard.py", json.dumps(self.event(f"here is {KEY}")), ("tool",), env.env())
            self.assertEqual(res.returncode, 2)
            self.assertNotIn(KEY, res.stderr)
            self.assertIn("API key", res.stderr)
            log = (cfg.state_dir() / "audit.jsonl").read_text()
            self.assertIn('"status": "blocked"', log)
            self.assertNotIn(KEY, log)

    def test_clean_send_passes(self):
        with support.BrainEnv() as env:
            res = support.run_script(SRC / "send_guard.py", json.dumps(self.event("see you at 3pm")), ("tool",), env.env())
            self.assertEqual(res.returncode, 0)

    def test_non_send_tool_ignored_even_with_key(self):
        with support.BrainEnv() as env:
            ev = {"tool_name": "Read", "tool_input": {"file_path": f"/x/{KEY}"}}
            self.assertEqual(support.run_script(SRC / "send_guard.py", json.dumps(ev), ("tool",), env.env()).returncode, 0)

    def test_garbage_fails_open_by_default_and_closed_on_request(self):
        for raw in ("garbage", ""):
            with support.BrainEnv() as env:
                self.assertEqual(support.run_script(SRC / "send_guard.py", raw, ("tool",), env.env()).returncode, 0)
                self.assertEqual(support.run_script(SRC / "send_guard.py", raw, ("prompt",), env.env()).returncode, 0)
            with support.BrainEnv() as env:
                cfg.save_config({"security": {"fail_closed": True}})
                self.assertEqual(support.run_script(SRC / "send_guard.py", raw, ("tool",), env.env()).returncode, 2)
                self.assertEqual(support.run_script(SRC / "send_guard.py", raw, ("prompt",), env.env()).returncode, 0)

    def test_override_is_single_use(self):
        with support.BrainEnv() as env:
            script = SRC / "send_guard.py"
            support.run_script(script, json.dumps({"session_id": "s1", "prompt": "send anyway"}), ("prompt",), env.env())
            first = support.run_script(script, json.dumps(self.event(f"x {KEY}")), ("tool",), env.env())
            second = support.run_script(script, json.dumps(self.event(f"x {KEY}")), ("tool",), env.env())
            self.assertEqual((first.returncode, second.returncode), (0, 2))

    def test_override_ignored_when_pasted_or_expired(self):
        with support.BrainEnv() as env:
            script = SRC / "send_guard.py"
            pasted = "<pasted_content id=1>send anyway</pasted_content id=1> hello"
            support.run_script(script, json.dumps({"session_id": "s1", "prompt": pasted}), ("prompt",), env.env())
            self.assertEqual(support.run_script(script, json.dumps(self.event(f"x {KEY}")), ("tool",), env.env()).returncode, 2)
            send_guard.mode_prompt({"session_id": "s2", "prompt": "send anyway"})
            self.assertFalse(send_guard.override_active("s2", now=time.time() + 600))

    def test_custom_pattern_from_config(self):
        with support.BrainEnv() as env:
            cfg.save_config(cfg.with_value(cfg.load_config(), "security.extra_patterns", {"customer id": "CUST-[0-9]{8}"}))
            res = support.run_script(SRC / "send_guard.py", json.dumps(self.event("id CUST-12345678")), ("tool",), env.env())
            self.assertEqual(res.returncode, 2)


class AuditTest(unittest.TestCase):
    def test_chain_verifies_then_detects_tampering(self):
        with support.BrainEnv() as env:
            self.assertEqual(audit.verify(), (True, 0, -1))
            for i in range(4):
                audit.append("mcp__mail__send_message", {"to": f"p{i}@x.example", "subject": f"s{i}"}, "ok", "sess")
            self.assertEqual(audit.verify(), (True, 4, -1))
            path = audit.path()
            lines = path.read_text().splitlines()
            record = json.loads(lines[1])
            record["recipients"] = ["evil@x.example"]
            lines[1] = json.dumps(record)
            path.write_text("\n".join(lines) + "\n")
            self.assertEqual(audit.verify(), (False, 4, 1))

    def test_deleting_a_middle_line_breaks_chain(self):
        with support.BrainEnv():
            for i in range(3):
                audit.append("t", {"to": f"p{i}@x.example"}, "ok")
            lines = audit.path().read_text().splitlines()
            audit.path().write_text("\n".join([lines[0], lines[2]]) + "\n")
            self.assertFalse(audit.verify()[0])

    def test_record_hook_only_records_sends_and_never_content(self):
        with support.BrainEnv() as env:
            support.run_script(SRC / "audit.py", json.dumps({"tool_name": "Read", "tool_input": {"file_path": "x"}}), env=env.env())
            self.assertFalse(audit.path().exists())
            event = {"tool_name": "mcp__mail__send_message", "session_id": "abcdef123",
                     "tool_input": {"to": "a@b.example", "subject": "Hello", "body": "secret plan text"}, "tool_response": {"ok": True}}
            support.run_script(SRC / "audit.py", json.dumps(event), env=env.env())
            text = audit.path().read_text()
            self.assertIn("a@b.example", text)
            self.assertNotIn("secret plan text", text)
            self.assertEqual(audit.verify()[:2], (True, 1))

    def test_cli_verify_exit_codes(self):
        with support.BrainEnv() as env:
            audit.append("t", {"to": "a@b.example"}, "ok")
            self.assertEqual(support.run_script(SRC / "audit.py", args=("verify",), env=env.env()).returncode, 0)
            audit.path().write_text(audit.path().read_text().replace("a@b.example", "z@b.example"))
            self.assertEqual(support.run_script(SRC / "audit.py", args=("verify",), env=env.env()).returncode, 1)


class GuardrailsTest(unittest.TestCase):
    def post(self, env, tool, data, session="g1"):
        return support.run_script(SRC / "guardrails.py", json.dumps({"session_id": session, "tool_name": tool, "tool_input": data}),
                                  ("post",), env.env())

    def stop(self, env, session="g1", **extra):
        return support.run_script(SRC / "guardrails.py", json.dumps({"session_id": session, **extra}), ("stop",), env.env())

    def test_alignment_only_for_long_prompts(self):
        with support.BrainEnv() as env:
            run = lambda text: support.run_script(SRC / "guardrails.py", json.dumps({"session_id": "x", "prompt": text}), ("prompt",), env.env())
            self.assertEqual(run("short").stdout, "")
            out = json.loads(run("word " * 100).stdout)
            self.assertIn("Alignment guardrail", out["hookSpecificOutput"]["additionalContext"])

    def test_file_loop_reminder_fires_once_at_five(self):
        with support.BrainEnv() as env:
            outputs = [self.post(env, "Edit", {"file_path": "/p/a.py"}).stdout for _ in range(7)]
            self.assertEqual([bool(o) for o in outputs], [False] * 4 + [True, False, False])
            self.assertIn("edited 5 times", outputs[4])

    def test_command_loop_reminder_at_three(self):
        with support.BrainEnv() as env:
            outputs = [self.post(env, "Bash", {"command": "make build"}).stdout for _ in range(4)]
            self.assertEqual([bool(o) for o in outputs], [False, False, True, False])

    def test_stop_blocks_once_when_code_changed_without_tests(self):
        with support.BrainEnv() as env:
            self.post(env, "Write", {"file_path": "/p/app.py"})
            first, second = self.stop(env), self.stop(env)
            self.assertEqual((first.returncode, second.returncode), (2, 0))
            self.assertIn("tests", first.stderr)

    def test_stop_ok_after_tests_or_for_docs(self):
        with support.BrainEnv() as env:
            self.post(env, "Write", {"file_path": "/p/app.py"})
            self.post(env, "Bash", {"command": "python3 -m pytest -q"})
            self.assertEqual(self.stop(env).returncode, 0)
            self.post(env, "Write", {"file_path": "/p/notes.md"}, session="g2")
            self.assertEqual(self.stop(env, session="g2").returncode, 0)

    def test_stop_hook_active_never_loops_and_switch_off(self):
        with support.BrainEnv() as env:
            self.post(env, "Write", {"file_path": "/p/app.py"})
            self.assertEqual(self.stop(env, stop_hook_active=True).returncode, 0)
            cfg.save_config(cfg.with_value(cfg.load_config(), "security.guardrails_off", ["tests"]))
            self.post(env, "Write", {"file_path": "/p/b.py"}, session="g3")
            self.assertEqual(self.stop(env, session="g3").returncode, 0)

    def test_garbage_never_fails(self):
        with support.BrainEnv() as env:
            for mode in ("prompt", "post", "stop"):
                self.assertEqual(support.run_script(SRC / "guardrails.py", "garbage", (mode,), env.env()).returncode, 0)


if __name__ == "__main__":
    unittest.main()
