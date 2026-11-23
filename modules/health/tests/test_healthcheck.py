"""Watchdog tests: temporary brain, fake clocks, fake launcher. No real jobs, keys or models."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import healthcheck as wd  # noqa: E402

NOW = datetime(2026, 3, 20, 12, 0).astimezone()


def touch(path: Path, age_h: float, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    stamp = (NOW - timedelta(hours=age_h)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name).resolve() / "brain"
        self.brain.mkdir()
        self.addCleanup(self._tmp.cleanup)

    def install(self, *names, since_days=30):
        stamp = (NOW - timedelta(days=since_days)).isoformat()
        (self.brain / "config.json").write_text(json.dumps({"modules": {n: {"installed_at": stamp} for n in names}}))

    def conf(self, name, data):
        path = self.brain / "config.d" / f"{name}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data))


class JobTests(Base):
    def test_fresh_job_is_ok_and_stale_job_fails_with_clear_message(self):
        self.install()
        self.conf("health", {"jobs": [
            {"name": "scout", "proof": str(self.brain / "out" / "scout_*.md"), "max_age_h": 192},
            {"name": "digest", "proof": str(self.brain / "out" / "digest.md"), "max_age_h": 24}]})
        touch(self.brain / "out" / "scout_1.md", 264)
        touch(self.brain / "out" / "digest.md", 2)
        found = {f.name: f for f in wd.check_jobs(self.brain, wd.load_settings(self.brain), NOW)}
        self.assertEqual(found["digest"].level, wd.OK)
        self.assertEqual(found["scout"].level, wd.FAIL)
        self.assertEqual(found["scout"].text, "scout: last run 11 days ago, threshold 8 days")

    def test_never_ran_is_a_failure_only_after_the_threshold_since_install(self):
        self.install("proactive", since_days=0)
        self.conf("proactive", {"sources": {"todo": {"enabled": True}}})
        self.assertEqual(wd.check_jobs(self.brain, {}, NOW)[0].level, wd.SKIP)
        self.install("proactive", since_days=5)
        late = wd.check_jobs(self.brain, {}, NOW)[0]
        self.assertEqual(late.level, wd.FAIL)
        self.assertIn("never ran", late.text)

    def test_self_improve_jobs_come_from_the_task_list_with_their_own_threshold(self):
        self.install("self-improve")
        self.conf("self-improve-tasks", {"tasks": [{"name": "improver", "days": ["sun"], "window_h": 72, "catch_up": True,
                                                    "command": "echo hi"}]})
        touch(self.brain / "state" / "self-improve" / "tasks" / "improver.json", 150)
        job = wd.check_jobs(self.brain, {}, NOW)[0]
        self.assertEqual((job.name, job.level), ("self-improve:improver", wd.OK))  # 168 + 72 hours allowed
        self.assertAlmostEqual(wd.max_gap_hours(["mon", "thu"], 0), 96)  # longest gap Thu to Mon

    def test_proactive_needs_an_enabled_source_and_night_needs_a_queued_task(self):
        self.install("proactive", "night")
        self.conf("proactive", {"sources": {"todo": {"enabled": False}}})
        self.assertEqual(wd.check_jobs(self.brain, {}, NOW), [])
        queue = self.brain / "data" / "night" / "queue"
        (queue / "01_task").mkdir(parents=True)
        self.assertEqual([f.name for f in wd.check_jobs(self.brain, {}, NOW)], ["night"])

    def test_ignore_list_hides_a_job(self):
        self.install()
        settings = {"jobs": [{"name": "x", "proof": str(self.brain / "none"), "max_age_h": 1}], "ignore": ["x"]}
        self.assertEqual(wd.check_jobs(self.brain, settings, NOW), [])


class ConnectorTests(Base):
    def test_token_file_checks_never_need_the_content(self):
        self.install("night")
        token = self.brain / "keys" / "claude_oauth_token"
        self.assertEqual(wd.check_auth_token(self.brain, wd.installed_modules(self.brain))[0].level, wd.WARN)
        touch(token, 1, "")
        self.assertIn("empty", wd.check_auth_token(self.brain, wd.installed_modules(self.brain))[0].text)
        touch(token, 1, "SECRET-VALUE-DO-NOT-LEAK")
        token.chmod(0o644)
        text = wd.check_auth_token(self.brain, wd.installed_modules(self.brain))[0].text
        self.assertIn("chmod 600", text)
        self.assertNotIn("SECRET-VALUE", text)
        token.chmod(0o600)
        self.assertEqual(wd.check_auth_token(self.brain, wd.installed_modules(self.brain))[0].level, wd.OK)

    def test_token_not_needed_without_headless_modules(self):
        self.install("proactive")
        self.assertEqual(wd.check_auth_token(self.brain, wd.installed_modules(self.brain)), [])

    def test_old_token_asks_for_renewal(self):
        self.install("self-improve")
        touch(self.brain / "keys" / "claude_oauth_token", 24 * 340, "x").chmod(0o600)
        self.assertIn("renew", wd.check_auth_token(self.brain, wd.installed_modules(self.brain))[0].text)

    def test_database_readable_or_broken(self):
        db = self.brain / "wa.db"
        sqlite3.connect(db).execute("create table t(a)").connection.close()
        self.conf("health", {"files": [{"name": "chats", "path": str(db), "sqlite": True},
                                       {"name": "gone", "path": str(self.brain / "nope.db"), "sqlite": True}]})
        out = {f.name: f for f in wd.check_databases(self.brain, wd.load_settings(self.brain), "linux")}
        self.assertEqual(out["chats"].level, wd.OK)
        self.assertEqual(out["gone"].level, wd.FAIL)
        (self.brain / "junk.db").write_text("not a database")
        self.assertIn("cannot be read", wd.sqlite_state(self.brain / "junk.db"))

    def test_enabled_whatsapp_source_with_missing_database_fails(self):
        self.conf("proactive", {"sources": {"whatsapp": {"enabled": True, "db": str(self.brain / "absent.db")}}})
        out = wd.check_databases(self.brain, {}, "linux")
        self.assertEqual((out[0].name, out[0].level), ("whatsapp", wd.FAIL))

    def test_telegram_only_when_configured(self):
        self.assertEqual(wd.check_telegram(self.brain), [])
        self.conf("telegram", {"allowed_user_ids": [1]})
        self.assertEqual(wd.check_telegram(self.brain)[0].level, wd.FAIL)

    def test_mcp_servers_expected_vs_listed(self):
        class Res:
            stdout = "vault: https://x - connected\nbroken: cmd - Failed to connect\n"
        from unittest import mock
        with mock.patch.object(wd.shutil, "which", return_value="/usr/local/bin/claude"):
            out = {f.name: f.level for f in wd.check_mcp(["vault", "broken", "absent"], run=lambda *a, **k: Res())}
        self.assertEqual(out, {"mcp:vault": wd.OK, "mcp:broken": wd.FAIL, "mcp:absent": wd.FAIL})
        self.assertEqual(wd.check_mcp([]), [])


class OutputTests(Base):
    def test_note_only_when_broken_and_removed_when_healthy(self):
        note = self.brain / "state" / "boot.d" / "health.md"
        bad = [wd.Finding(wd.FAIL, "scout", "scout: last run 11 days ago, threshold 8 days"), wd.Finding(wd.OK, "x", "x: fine")]
        wd.write_note(self.brain, bad)
        text = note.read_text()
        self.assertIn("scout: last run 11 days ago, threshold 8 days", text)
        self.assertNotIn("x: fine", text)
        wd.write_note(self.brain, [wd.Finding(wd.OK, "scout", "scout: ok")])
        self.assertFalse(note.exists())

    def test_note_of_another_module_is_never_removed(self):
        note = self.brain / "state" / "boot.d" / "health.md"
        note.parent.mkdir(parents=True)
        note.write_text("mine")
        wd.write_note(self.brain, [])
        self.assertTrue(note.exists())

    def test_note_is_capped(self):
        many = [wd.Finding(wd.FAIL, str(i), f"job{i}: last run {i} days ago, threshold 1 days") for i in range(80)]
        self.assertLessEqual(len(wd.render_note(many)), 900)


class CatchUpTests(Base):
    def setUp(self):
        super().setUp()
        self.install()
        self.conf("health", {"jobs": [{"name": "digest", "proof": str(self.brain / "d.md"), "max_age_h": 24, "command": "run-digest"},
                                      {"name": "manual", "proof": str(self.brain / "m.md"), "max_age_h": 24}]})
        touch(self.brain / "d.md", 100)
        touch(self.brain / "m.md", 100)
        self.findings = wd.check_jobs(self.brain, wd.load_settings(self.brain), NOW)

    def test_launches_only_stale_jobs_with_a_command_and_only_once_per_window(self):
        calls = []
        launch = lambda command, brain: calls.append(command)  # noqa: E731
        self.assertEqual(wd.catch_up(self.brain, self.findings, NOW, launch), ["digest"])
        self.assertEqual(wd.catch_up(self.brain, self.findings, NOW + timedelta(hours=1), launch), [])
        self.assertEqual(wd.catch_up(self.brain, self.findings, NOW + timedelta(hours=7), launch), ["digest"])
        self.assertEqual(calls, ["run-digest", "run-digest"])

    def test_dry_run_launches_and_marks_nothing(self):
        calls = []
        self.assertEqual(wd.catch_up(self.brain, self.findings, NOW, lambda c, b: calls.append(c), dry_run=True), ["digest"])
        self.assertEqual(calls, [])
        self.assertFalse((self.brain / "state" / "health").exists())

    def test_clean_env_strips_keys(self):
        os.environ["FAKE_API_KEY"] = "v"
        self.addCleanup(os.environ.pop, "FAKE_API_KEY", None)
        env = wd.clean_env()
        self.assertNotIn("FAKE_API_KEY", env)
        self.assertEqual(env["CARLO_HEADLESS"], "1")


class CommandTests(Base):
    def test_boot_writes_note_and_is_silent_in_headless_runs(self):
        self.install()
        self.conf("health", {"jobs": [{"name": "old", "proof": str(self.brain / "o.md"), "max_age_h": 1}], "catchup": False})
        touch(self.brain / "o.md", 50)
        os.environ["CARLO_BRAIN_HOME"] = str(self.brain)
        self.addCleanup(os.environ.pop, "CARLO_BRAIN_HOME", None)
        fake_home = mock.patch.dict(os.environ, {"HOME": str(self.brain.parent)})  # the repair playbook must never see the real HOME
        fake_home.start()
        self.addCleanup(fake_home.stop)
        os.environ["CARLO_HEADLESS"] = "1"
        self.addCleanup(os.environ.pop, "CARLO_HEADLESS", None)
        self.assertEqual(wd.cmd_watch(full=False), 0)
        self.assertFalse((self.brain / "state" / "boot.d" / "health.md").exists())
        del os.environ["CARLO_HEADLESS"]
        self.assertEqual(wd.cmd_watch(full=False), 0)
        self.assertIn("old: last run", (self.brain / "state" / "boot.d" / "health.md").read_text())

    def test_no_dash_characters_in_shipped_text(self):
        for path in [Path(wd.__file__), Path(wd.__file__).parents[1] / "module.toml"]:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(chr(0x2014), text)
            self.assertNotIn(chr(0x2013), text)


if __name__ == "__main__":
    unittest.main()
