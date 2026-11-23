"""Tests for the sync module, using a local bare repository as the remote."""
import json
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
import support  # noqa: E402

SRC = Path(support.module_src("sync"))

import sync  # noqa: E402
import carlo_config as cfg  # noqa: E402


def git(path, *args):
    return subprocess.run(["git", *sync.IDENTITY, *args], cwd=str(path), capture_output=True, text=True, check=True).stdout


@unittest.skipUnless(shutil.which("git"), "git not installed")
class SyncTest(unittest.TestCase):
    def setup_remote(self, env):
        bare = env.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], capture_output=True, check=True)
        cfg.save_config(cfg.with_value(cfg.with_value(cfg.load_config(), "sync.remote", str(bare)), "sync.branch", "main"))
        return bare

    def other_clone(self, env, bare):
        clone = env.root / "other"
        subprocess.run(["git", "clone", str(bare), str(clone)], capture_output=True, check=True)
        return clone

    def test_local_only_commits_without_remote(self):
        with support.BrainEnv() as env:
            result = sync.run("end", env.vault)
            self.assertTrue(result["committed"])
            self.assertEqual(result["push"], "skipped")
            self.assertTrue((env.vault / ".git").exists())
            self.assertTrue((env.vault / ".gitignore").exists())
            self.assertFalse(sync.run("end", env.vault)["committed"], "nothing changed, no empty commit")

    def test_end_pushes_and_start_pulls(self):
        with support.BrainEnv() as env:
            bare = self.setup_remote(env)
            self.assertEqual(sync.run("end", env.vault)["push"], "ok")
            clone = self.other_clone(env, bare)
            (clone / "from_other.md").write_text("hello")
            git(clone, "add", "-A")
            git(clone, "commit", "-m", "other")
            git(clone, "push", "origin", "HEAD:main")
            result = sync.run("start", env.vault)
            self.assertEqual(result["pull"], "ok")
            self.assertTrue((env.vault / "from_other.md").exists())

    def test_push_after_remote_moved_merges_then_pushes(self):
        with support.BrainEnv() as env:
            bare = self.setup_remote(env)
            sync.run("end", env.vault)
            clone = self.other_clone(env, bare)
            (clone / "a.md").write_text("a")
            git(clone, "add", "-A")
            git(clone, "commit", "-m", "a")
            git(clone, "push", "origin", "HEAD:main")
            (env.vault / "b.md").write_text("b")
            self.assertEqual(sync.run("end", env.vault)["push"], "ok")
            self.assertTrue((env.vault / "a.md").exists() and (env.vault / "b.md").exists())

    def test_conflict_is_aborted_signalled_and_nothing_lost(self):
        with support.BrainEnv() as env:
            bare = self.setup_remote(env)
            (env.vault / "note.md").write_text("base\n")
            sync.run("end", env.vault)
            clone = self.other_clone(env, bare)
            (clone / "note.md").write_text("remote version\n")
            git(clone, "add", "-A")
            git(clone, "commit", "-m", "r")
            git(clone, "push", "origin", "HEAD:main")
            (env.vault / "note.md").write_text("local version\n")
            result = sync.run("start", env.vault)
            self.assertEqual(result["pull"], "conflict")
            self.assertEqual((env.vault / "note.md").read_text(), "local version\n")
            self.assertFalse((env.vault / ".git" / "MERGE_HEAD").exists())
            self.assertTrue((cfg.boot_dir() / sync.CONFLICT_SIGNAL).exists())
            self.assertEqual(sync.run("end", env.vault)["push"], "conflict", "never forces")

    def test_conflict_signal_cleared_after_successful_pull(self):
        with support.BrainEnv() as env:
            self.setup_remote(env)
            sync.signal_conflict("x")
            sync.run("end", env.vault)
            sync.run("start", env.vault)
            self.assertFalse((cfg.boot_dir() / sync.CONFLICT_SIGNAL).exists())

    def test_missing_vault_is_reported_not_raised(self):
        with support.BrainEnv(with_vault=False) as env:
            self.assertIn("error", sync.run("start", env.root / "nope"))

    def test_server_step_skipped_without_config_and_failed_gracefully(self):
        self.assertEqual(sync.update_server({}), "skipped")
        self.assertIn(sync.update_server({"host": "nobody@127.0.0.1", "path": "/x"}), ("failed",))

    def test_hook_detach_returns_immediately_and_headless_noop(self):
        with support.BrainEnv() as env:
            # headless first: the detached run below keeps working in the background and may init the vault
            res = support.run_script(SRC / "sync.py", args=("end",), env=env.env(CARLO_HEADLESS="1"))
            self.assertEqual(res.returncode, 0)
            self.assertFalse((env.vault / ".git").exists())
            res = support.run_script(SRC / "sync.py", args=("end",), env=env.env())
            self.assertEqual(res.returncode, 0)
            self.assertIn("sync_end", cfg.last_runs())
            marker = cfg.state_dir() / "runs" / "sync_end.txt"
            before = marker.stat().st_mtime_ns
            res = support.run_script(SRC / "sync.py", args=("end", "--detach"), env=env.env())
            self.assertEqual(res.returncode, 0)
            # wait for the background run to finish before the temp folder is removed
            deadline = time.time() + 30
            while time.time() < deadline and marker.stat().st_mtime_ns == before:
                time.sleep(0.2)
            time.sleep(0.5)


if __name__ == "__main__":
    unittest.main()
