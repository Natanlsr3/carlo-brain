"""Repair playbook tests: fake HOME and brain in a temp dir, subprocess mocked. Nothing real is launched or touched."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import healthcheck as wd  # noqa: E402
import repair as rp  # noqa: E402

NOW = datetime(2026, 3, 20, 12, 0).astimezone()
LABEL = "com.carlo-brain.proactive.scan"


def done(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


class FakeSystem:
    """Records every command; `answers` maps the first word(s) of a command to a CompletedProcess."""

    def __init__(self, answers=None):
        self.calls, self.started, self.answers = [], [], answers or {}

    def run(self, argv, **kw):
        self.calls.append(list(argv))
        for prefix in (" ".join(argv[:3]), " ".join(argv[:2]), argv[0]):
            if prefix in self.answers:
                res = self.answers[prefix]
                if isinstance(res, Exception):
                    raise res
                return res
        return done()

    def popen(self, argv, **kw):
        self.started.append((list(argv), kw))

    def ran(self, *prefix):
        return [c for c in self.calls if c[: len(prefix)] == list(prefix)]


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.home = self.root / "home"
        self.brain = self.root / "brain"
        self.home.mkdir()
        for sub in ("config.d", "state/boot.d", "state/health", "state/logs"):
            (self.brain / sub).mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)
        self.sys = FakeSystem()

    def conf(self, data):
        (self.brain / "config.d" / "health.json").write_text(json.dumps(data))

    def plist(self, label=LABEL):
        path = self.home / "Library" / "LaunchAgents" / f"{label}.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<plist/>")
        return path

    def repair(self, findings=(), now=NOW, **kw):
        kw.setdefault("platform", "darwin")
        kw.setdefault("full", True)
        return rp.run_repair(self.brain, list(findings), now, home=self.home, run=self.sys.run, popen=self.sys.popen, env={"A": "1"}, **kw)

    def statuses(self, outcomes):
        return {o.key: o.status for o in outcomes}


class LaunchdTests(Base):
    def test_unloaded_job_is_bootstrapped_and_logged(self):
        plist = self.plist()
        self.sys.answers["launchctl print"] = done(113, err="Could not find service")
        out = self.repair()
        self.assertEqual(self.statuses(out)[f"launchd:{LABEL}"], rp.FIXED)
        self.assertEqual(self.sys.ran("launchctl", "bootstrap"), [["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)]])
        self.assertIn(f"fixed launchd:{LABEL}", rp.log_file(self.brain).read_text())

    def test_loaded_job_is_left_alone_and_linux_skips_launchd(self):
        self.plist()
        self.assertNotIn(f"launchd:{LABEL}", self.statuses(self.repair()))
        self.sys.answers["launchctl print"] = done(1)
        self.assertEqual(self.statuses(self.repair(platform="linux")), {})
        self.assertEqual(self.sys.ran("launchctl", "bootstrap"), [])

    def test_failed_bootstrap_is_logged_and_handed_to_the_user_with_the_command(self):
        self.plist()
        self.sys.answers["launchctl print"] = done(1)
        self.sys.answers["launchctl bootstrap"] = done(5, err="Bootstrap failed: 5: Input/output error")
        out = self.repair()
        self.assertEqual(self.statuses(out)[f"launchd:{LABEL}"], rp.FAILED)
        self.assertIn("Input/output error", rp.log_file(self.brain).read_text())
        self.assertTrue(rp.actions_for_note(out)[0].startswith("launchctl bootstrap gui/"))

    def test_ignored_job_is_not_repaired(self):
        self.plist()
        self.sys.answers["launchctl print"] = done(1)
        self.conf({"ignore": ["proactive.scan"]})
        self.assertEqual(self.statuses(self.repair()), {})

    def test_other_launchd_jobs_are_never_touched(self):
        self.plist("com.someone.else")
        self.sys.answers["launchctl print"] = done(1)
        self.assertEqual(self.sys.ran("launchctl", "bootstrap"), [])
        self.repair()
        self.assertEqual(self.sys.ran("launchctl", "bootstrap"), [])


class ThrottleTests(Base):
    def test_at_most_once_per_24_hours_then_again(self):
        self.plist()
        self.sys.answers["launchctl print"] = done(1)
        self.repair()
        second = self.repair(now=NOW + timedelta(hours=23))
        self.assertEqual(self.statuses(second)[f"launchd:{LABEL}"], rp.THROTTLED)
        self.assertEqual(len(self.sys.ran("launchctl", "bootstrap")), 1)
        self.assertIn("launchctl bootstrap", rp.actions_for_note(second)[0])  # still broken: the user hears about it
        third = self.repair(now=NOW + timedelta(hours=25))
        self.assertEqual(self.statuses(third)[f"launchd:{LABEL}"], rp.FIXED)
        self.assertEqual(len(self.sys.ran("launchctl", "bootstrap")), 2)

    def test_attempt_is_marked_before_the_fix_so_a_crash_does_not_loop(self):
        self.plist()
        self.sys.answers["launchctl print"] = done(1)
        self.sys.answers["launchctl bootstrap"] = subprocess.TimeoutExpired("launchctl", 20)
        self.assertEqual(self.statuses(self.repair())[f"launchd:{LABEL}"], rp.FAILED)
        self.assertEqual(self.statuses(self.repair(now=NOW + timedelta(hours=1)))[f"launchd:{LABEL}"], rp.THROTTLED)

    def test_dry_run_changes_nothing_and_does_not_start_the_clock(self):
        self.plist()
        self.sys.answers["launchctl print"] = done(1)
        out = self.repair(dry_run=True)
        self.assertEqual(self.statuses(out)[f"launchd:{LABEL}"], rp.WOULD_FIX)
        self.assertEqual(self.sys.ran("launchctl", "bootstrap"), [])
        self.assertFalse(rp.state_file(self.brain).exists())
        self.assertFalse(rp.log_file(self.brain).exists())
        self.assertEqual(self.statuses(self.repair())[f"launchd:{LABEL}"], rp.FIXED)


class OffSwitchTests(Base):
    def test_switched_off_runs_nothing_but_still_gives_the_commands(self):
        (self.brain / "state" / "health").rmdir()
        for setting in (False, {"enabled": False}):
            self.plist()
            self.conf({"repair": setting})
            self.sys.answers["launchctl print"] = done(1)
            out = self.repair()
            self.assertEqual({o.status for o in out}, {rp.OFF})
            self.assertEqual(self.sys.ran("launchctl", "bootstrap"), [])
            self.assertTrue(any("mkdir -p" in a for a in rp.actions_for_note(out)))
            self.assertFalse((self.brain / "state" / "health").exists())

    def test_default_is_on(self):
        self.assertTrue(rp.repair_config({})["enabled"])
        self.assertTrue(rp.repair_config({"repair": {"max_log_mb": 1}})["enabled"])


class McpTests(Base):
    LISTED = done(0, "vault: https://x - connected\nplaywright: npx @playwright/mcp - connected\n")

    def test_missing_server_is_reregistered_with_the_stored_command(self):
        self.conf({"expect_mcp": ["vault", "notes"], "repair": {"mcp_commands": {"notes": "claude mcp add notes -s user -- npx notes-mcp"}}})
        self.sys.answers["claude mcp list"] = self.LISTED
        out = self.repair()
        self.assertEqual(self.statuses(out), {"mcp:notes": rp.FIXED})
        self.assertEqual(self.sys.ran("claude", "mcp", "add"), [["claude", "mcp", "add", "notes", "-s", "user", "--", "npx", "notes-mcp"]])

    def test_no_stored_command_means_a_manual_line_and_nothing_runs(self):
        self.conf({"expect_mcp": ["notes"]})
        self.sys.answers["claude mcp list"] = self.LISTED
        out = self.repair()
        self.assertEqual(self.statuses(out), {"mcp:notes": rp.MANUAL})
        self.assertIn("claude mcp add notes", rp.actions_for_note(out)[0])
        self.assertEqual(self.sys.ran("claude", "mcp", "add"), [])

    def test_a_stored_command_that_is_not_claude_mcp_add_is_refused(self):
        self.conf({"expect_mcp": ["notes"], "repair": {"mcp_commands": {"notes": "rm -rf /"}}})
        self.sys.answers["claude mcp list"] = self.LISTED
        self.assertEqual(self.statuses(self.repair()), {"mcp:notes": rp.MANUAL})
        self.assertEqual(self.sys.ran("rm"), [])

    def test_failed_server_is_not_reregistered_only_missing_ones_and_fast_mode_skips(self):
        self.conf({"expect_mcp": ["vault"], "repair": {"mcp_commands": {"vault": "claude mcp add vault -- x"}}})
        self.sys.answers["claude mcp list"] = done(0, "vault: x - failed to connect\n")
        self.assertEqual(self.statuses(self.repair()), {})
        self.sys.answers["claude mcp list"] = done(0, "")
        self.assertEqual(self.statuses(self.repair(full=False)), {})
        self.assertEqual(self.sys.ran("claude", "mcp", "list"), [self.sys.calls[0]])  # only the first (full) call listed

    def test_unusable_list_command_changes_nothing(self):
        self.conf({"expect_mcp": ["vault"]})
        self.sys.answers["claude mcp list"] = done(1, err="not logged in")
        self.assertEqual(self.statuses(self.repair()), {})
        self.sys.answers["claude mcp list"] = FileNotFoundError("claude")
        self.assertEqual(self.statuses(self.repair()), {})


class BridgeTests(Base):
    def bridge(self):
        path = self.brain / "data" / "whatsapp-mcp" / "whatsapp-bridge" / "whatsapp-bridge"
        path.parent.mkdir(parents=True)
        path.write_text("#!/bin/sh")
        return path

    def enable_source(self):
        (self.brain / "config.d" / "proactive.json").write_text(json.dumps({"sources": {"whatsapp": {"enabled": True}}}))

    def test_dead_configured_bridge_is_started_detached_with_a_log(self):
        binary = self.bridge()
        self.enable_source()
        self.sys.answers["pgrep"] = done(1)
        out = self.repair()
        self.assertEqual(self.statuses(out), {"whatsapp-bridge": rp.FIXED})
        argv, kw = self.sys.started[0]
        self.assertEqual((argv, kw["cwd"], kw["start_new_session"]), ([str(binary)], str(binary.parent), True))
        self.assertTrue((self.brain / "state" / "logs" / "whatsapp-bridge.log").exists())

    def test_running_not_configured_or_service_managed_bridge_is_left_alone(self):
        self.bridge()
        self.sys.answers["pgrep"] = done(1)
        self.assertEqual(self.statuses(self.repair()), {})  # binary exists, but nothing says it is wanted
        self.enable_source()
        self.sys.answers["pgrep"] = done(0)
        self.assertEqual(self.statuses(self.repair()), {})
        self.sys.answers["pgrep"] = done(1)
        self.plist("com.carlo-brain.whatsapp-bridge")
        self.sys.answers["launchctl print"] = done(0)
        self.assertNotIn("whatsapp-bridge", self.statuses(self.repair()))
        self.assertEqual(self.sys.started, [])

    def test_explicit_command_in_config_is_used(self):
        self.conf({"repair": {"whatsapp_bridge": {"command": "/opt/bridge --port 1", "cwd": str(self.root)}}})
        self.sys.answers["pgrep"] = done(1)
        self.repair()
        self.assertEqual(self.sys.started[0][0], ["/opt/bridge", "--port", "1"])


class LogAndDirTests(Base):
    def test_big_log_is_copied_then_truncated_in_place_and_small_one_is_kept(self):
        self.conf({"repair": {"max_log_mb": 0.001}})  # about 1 KB
        big, small = self.brain / "state" / "logs" / "big.log", self.brain / "state" / "logs" / "small.log"
        big.write_text("x" * 5000)
        small.write_text("tiny")
        inode = big.stat().st_ino
        out = self.repair()
        self.assertEqual(self.statuses(out), {f"log:{big}": rp.FIXED})
        self.assertEqual((big.stat().st_size, big.stat().st_ino), (0, inode))
        self.assertEqual((big.with_name("big.log.1")).read_text(), "x" * 5000)
        self.assertEqual(small.read_text(), "tiny")

    def test_configured_extra_log_and_symlinks(self):
        extra = self.root / "app.log"
        extra.write_text("y" * 3000)
        link = self.brain / "state" / "logs" / "link.log"
        link.symlink_to(extra)
        self.conf({"repair": {"max_log_mb": 0.001, "logs": [str(extra)]}})
        keys = self.statuses(self.repair())
        self.assertEqual(keys, {f"log:{extra}": rp.FIXED})

    def test_missing_state_folders_are_recreated(self):
        (self.brain / "state" / "logs").rmdir()
        (self.brain / "state" / "health").rmdir()
        out = self.repair()
        self.assertEqual({o.status for o in out}, {rp.FIXED})
        self.assertTrue((self.brain / "state" / "logs").is_dir() and (self.brain / "state" / "health").is_dir())

    def test_module_state_folders_only_for_installed_modules(self):
        (self.brain / "config.json").write_text(json.dumps({"modules": {"night": {}}}))
        keys = self.statuses(self.repair())
        self.assertEqual(keys, {f"dir:{self.brain / 'state' / 'night'}": rp.FIXED})


class ManualTests(Base):
    def finding(self, name, text, level="fail"):
        return wd.Finding(level, name, text, "connector")

    def test_expired_login_full_disk_access_and_missing_key_only_produce_commands(self):
        findings = [self.finding("claude-auth", "claude-auth: keys/claude_oauth_token older than 335 days, renew it", "warn"),
                    self.finding("apple-messages", "apple-messages: not readable (Full Disk Access?)"),
                    self.finding("telegram", "telegram: bot token file missing")]
        out = self.repair(findings)
        self.assertEqual({o.status for o in out}, {rp.MANUAL})
        actions = rp.actions_for_note(out)
        self.assertEqual(len(actions), 3)
        self.assertTrue(any(a.startswith("claude setup-token") for a in actions))
        self.assertTrue(any("x-apple.systempreferences" in a and "Privacy_AllFiles" in a for a in actions))
        self.assertTrue(any("telegram_bot_token" in a for a in actions))
        self.assertEqual(self.sys.calls, [])  # nothing executed, not even a launchctl print
        self.assertFalse(rp.log_file(self.brain).exists())

    def test_wrong_permissions_give_a_chmod_line(self):
        out = self.repair([self.finding("claude-auth", "claude-auth: keys/claude_oauth_token readable by others (chmod 600)", "warn")])
        self.assertTrue(rp.actions_for_note(out)[0].startswith("chmod 600 "))

    def test_healthy_findings_produce_nothing(self):
        self.assertEqual(self.repair([self.finding("claude-auth", "ok", "ok")]), [])

    def test_note_carries_the_actions_and_boot_writes_it(self):
        finding = self.finding("claude-auth", "claude-auth: keys/claude_oauth_token missing", "warn")
        note = wd.render_note([finding], actions=["claude setup-token   # then save it"])
        self.assertIn("- `claude setup-token   # then save it`", note)
        self.assertIn("Only the user can do these", note)
        many = [wd.Finding(wd.FAIL, f"j{i}", f"job {i} is very late and needs a long explanation here", "job") for i in range(40)]
        self.assertIn("- `one action`", wd.render_note(many, actions=["one action"]))  # the cap never cuts the actions


class WatchIntegrationTests(Base):
    def test_boot_repairs_then_rechecks_and_clears_the_note(self):
        """cmd_watch end to end with a fake HOME: a missing state folder is fixed and the note disappears."""
        (self.brain / "config.json").write_text(json.dumps({"modules": {}}))
        proof = self.brain / "o.md"
        self.conf({"jobs": [{"name": "old", "proof": str(proof), "max_age_h": 1}], "catchup": False})
        proof.write_text("x")
        os.utime(proof, (1_600_000_000, 1_600_000_000))
        env = {"CARLO_BRAIN_HOME": str(self.brain), "HOME": str(self.home)}
        with mock.patch.dict(os.environ, env):
            os.environ.pop("CARLO_HEADLESS", None)
            with mock.patch.object(rp.subprocess, "run", side_effect=self.sys.run):
                self.assertEqual(wd.cmd_watch(full=False), 0)
        self.assertIn("old: last run", (self.brain / "state" / "boot.d" / "health.md").read_text())

    def test_status_and_repair_commands_run_and_respect_dry_run(self):
        env = {**os.environ, "CARLO_BRAIN_HOME": str(self.brain), "HOME": str(self.home)}
        script = str(Path(wd.__file__))
        (self.brain / "state" / "logs").rmdir()
        status = subprocess.run([sys.executable, "-I", script, "status"], capture_output=True, text=True, env=env)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("repair: on", status.stdout)
        self.assertIn("would-fix", status.stdout)
        self.assertFalse((self.brain / "state" / "logs").exists())
        dry = subprocess.run([sys.executable, "-I", script, "repair", "--dry-run"], capture_output=True, text=True, env=env)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertFalse((self.brain / "state" / "logs").exists())
        real = subprocess.run([sys.executable, "-I", script, "repair"], capture_output=True, text=True, env=env)
        self.assertIn("[fixed]", real.stdout)
        self.assertTrue((self.brain / "state" / "logs").is_dir())
        self.assertIn("created", subprocess.run([sys.executable, "-I", script, "status"], capture_output=True, text=True, env=env).stdout)


class TextTests(unittest.TestCase):
    def test_no_dash_characters_in_shipped_text(self):
        base = Path(rp.__file__).parent
        for path in [Path(rp.__file__), base.parent / "README.md", base.parent / "install.sh"]:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(chr(0x2014), text, path)
            self.assertNotIn(chr(0x2013), text, path)


if __name__ == "__main__":
    unittest.main()
