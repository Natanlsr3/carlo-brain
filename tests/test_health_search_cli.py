"""End to end: `carlo add health search`, `carlo doctor` shows the watchdog, `carlo search` works, uninstall is clean."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

ROOT = support.ROOT


def carlo(env, *args):
    return subprocess.run([sys.executable, str(ROOT / "carlo"), *args], capture_output=True, text=True,
                          env=env.env(), timeout=120, stdin=subprocess.DEVNULL)


class HealthSearchCliTests(unittest.TestCase):
    def setup_env(self, env):
        res = carlo(env, "init", "--yes", "--vault", str(env.vault), "--name", "Testy", "--user", "Sam",
                    "--modules", "memory,health,search")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_install_registers_hook_skill_and_config_and_removal_is_clean(self):
        with support.BrainEnv(with_vault=False) as env:
            self.setup_env(env)
            settings = json.loads((env.claude / "settings.json").read_text())
            self.assertIn("carlo-brain:health", json.dumps(settings))
            self.assertTrue((env.brain / "health" / "healthcheck.py").exists())
            self.assertTrue((env.brain / "config.d" / "health.json").exists())
            self.assertTrue((env.claude / "skills" / "find-it" / "SKILL.md").exists())
            self.assertEqual(carlo(env, "remove", "health", "search").returncode, 0)
            self.assertNotIn("carlo-brain:health", (env.claude / "settings.json").read_text())
            self.assertFalse((env.claude / "skills" / "find-it" / "SKILL.md").exists())

    def test_user_edited_skill_is_kept(self):
        with support.BrainEnv(with_vault=False) as env:
            skill = env.claude / "skills" / "find-it" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("mine")
            self.setup_env(env)
            self.assertEqual(skill.read_text(), "mine")
            self.assertTrue(skill.with_name("SKILL.md.new").exists())
            carlo(env, "remove", "search")
            self.assertEqual(skill.read_text(), "mine")

    def test_doctor_reports_a_stale_job_and_the_exit_code(self):
        with support.BrainEnv(with_vault=False) as env:
            self.setup_env(env)
            clean = carlo(env, "doctor")
            self.assertNotIn("threshold", clean.stdout)
            (env.brain / "config.d" / "health.json").write_text(json.dumps(
                {"jobs": [{"name": "scout", "proof": str(env.brain / "out" / "none_*.md"), "max_age_h": 1}]}))
            proof = env.brain / "out" / "scout.md"
            proof.parent.mkdir()
            proof.write_text("x")
            os.utime(proof, (1_600_000_000, 1_600_000_000))
            (env.brain / "config.d" / "health.json").write_text(json.dumps(
                {"jobs": [{"name": "scout", "proof": str(proof), "max_age_h": 192}]}))
            doctor = carlo(env, "doctor")
            self.assertIn("[FAIL] scout: last run", doctor.stdout)
            self.assertIn("threshold 8 days", doctor.stdout)
            self.assertEqual(doctor.returncode, 1)

    def test_boot_hook_drops_and_clears_the_signal(self):
        with support.BrainEnv(with_vault=False) as env:
            self.setup_env(env)
            note = env.brain / "state" / "boot.d" / "health.md"
            conf = env.brain / "config.d" / "health.json"
            proof = env.brain / "out.md"
            proof.write_text("x")
            os.utime(proof, (1_600_000_000, 1_600_000_000))
            conf.write_text(json.dumps({"catchup": False, "jobs": [{"name": "scout", "proof": str(proof), "max_age_h": 24}]}))
            support.run_script(env.brain / "health" / "healthcheck.py", args=("boot",), env=env.env())
            self.assertIn("scout: last run", note.read_text())
            os.utime(proof, None)
            support.run_script(env.brain / "health" / "healthcheck.py", args=("boot",), env=env.env())
            self.assertFalse(note.exists())

    def test_carlo_search_command(self):
        with support.BrainEnv(with_vault=False) as env:
            self.assertEqual(carlo(env, "search", "needle").returncode, 1)  # module not installed
            self.setup_env(env)
            (env.vault / "00_System" / "found.md").write_text("line one\nthe needle is here\n")
            res = carlo(env, "search", "needle", "--source", "vault")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("found.md:2:", res.stdout)

    def test_carlo_health_repair_and_status_and_rebuild_cache(self):
        with support.BrainEnv(with_vault=False) as env:
            self.assertEqual(carlo(env, "health", "status").returncode, 1)  # module not installed
            self.setup_env(env)
            logs = env.brain / "state" / "logs"
            if logs.exists():
                logs.rmdir()
            status = carlo(env, "health", "status")
            self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
            self.assertIn("repair: on", status.stdout)
            self.assertFalse(logs.exists())  # status never changes anything
            self.assertFalse(carlo(env, "health", "repair", "--dry-run").returncode)
            self.assertFalse(logs.exists())
            self.assertIn("[fixed]", carlo(env, "health", "repair").stdout)
            self.assertTrue(logs.is_dir())
            (env.brain / "config.d" / "health.json").write_text(json.dumps({"repair": False}))
            logs.rmdir()
            self.assertIn("switched off", carlo(env, "health", "repair").stdout)
            self.assertFalse(logs.exists())
            res = carlo(env, "search", "--rebuild-cache")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("cache rebuilt", res.stdout)


if __name__ == "__main__":
    unittest.main()
