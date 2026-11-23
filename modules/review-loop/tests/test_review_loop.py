"""Tests for the review-loop module: real git in a temporary repo, no model call."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
import support  # noqa: E402

SRC = Path(support.module_src("review-loop"))

import review_loop as rl  # noqa: E402
import carlo_config as cfg  # noqa: E402

SCRIPT = SRC / "review_loop.py"
BODY = "".join(f"x{i} = {i}\n" for i in range(12))


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "app.py").write_text("a = 1\n")
    (repo / "notes.md").write_text("hi\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


class ReviewLoopTest(unittest.TestCase):
    def hook(self, env, mode, repo, session="s1", **extra):
        event = {"session_id": session, "cwd": str(repo), **extra}
        return support.run_script(SCRIPT, json.dumps(event), (mode,), env.env())

    def test_blocks_once_per_diff_with_the_file_list(self):
        with support.BrainEnv() as env:
            repo = make_repo(env.root)
            self.assertEqual(self.hook(env, "start", repo).returncode, 0)
            self.assertEqual(self.hook(env, "stop", repo).returncode, 0, "nothing changed")
            (repo / "app.py").write_text(BODY)
            first = self.hook(env, "stop", repo)
            self.assertEqual(first.returncode, 2)
            self.assertIn("reviewer", first.stderr)
            self.assertIn("app.py", first.stderr)
            self.assertEqual(self.hook(env, "stop", repo).returncode, 0, "same diff: asked once")

    def test_new_diff_asks_again_until_the_session_cap(self):
        with support.BrainEnv() as env:
            repo = make_repo(env.root)
            self.hook(env, "start", repo)
            codes = []
            for n in range(4):
                (repo / "app.py").write_text(BODY + f"y = {n}\n")
                codes.append(self.hook(env, "stop", repo).returncode)
            self.assertEqual(codes, [2, 2, 0, 0], "default cap is 2 per session")

    def test_existing_diff_before_the_session_does_not_count(self):
        with support.BrainEnv() as env:
            repo = make_repo(env.root)
            (repo / "app.py").write_text(BODY)
            self.hook(env, "start", repo)
            self.assertEqual(self.hook(env, "stop", repo).returncode, 0)

    def test_untracked_code_counts_docs_and_tiny_changes_do_not(self):
        with support.BrainEnv() as env:
            repo = make_repo(env.root)
            self.hook(env, "start", repo)
            (repo / "notes.md").write_text("changed " * 100)
            self.assertEqual(self.hook(env, "stop", repo).returncode, 0, "docs are not code")
            (repo / "app.py").write_text("a = 2\n")
            self.assertEqual(self.hook(env, "stop", repo).returncode, 0, "below min_lines")
            (repo / "new_module.py").write_text(BODY)
            res = self.hook(env, "stop", repo)
            self.assertEqual(res.returncode, 2)
            self.assertIn("new_module.py", res.stderr)

    def test_stop_hook_active_off_switch_and_headless(self):
        with support.BrainEnv() as env:
            repo = make_repo(env.root)
            self.hook(env, "start", repo)
            (repo / "app.py").write_text(BODY)
            self.assertEqual(self.hook(env, "stop", repo, stop_hook_active=True).returncode, 0)
            headless = support.run_script(SCRIPT, json.dumps({"session_id": "h", "cwd": str(repo)}), ("stop",),
                                          {**env.env(), "CARLO_HEADLESS": "1"})
            self.assertEqual(headless.returncode, 0)
            cfg.save_config(cfg.with_value(cfg.load_config(), "review_loop.enabled", False))
            self.assertEqual(self.hook(env, "stop", repo, session="s2").returncode, 0)

    def test_not_a_repo_and_garbage_input_never_block(self):
        with support.BrainEnv() as env:
            plain = env.root / "plain"
            plain.mkdir()
            (plain / "a.py").write_text(BODY)
            self.assertEqual(self.hook(env, "stop", plain).returncode, 0)
            for mode in ("start", "stop", "other"):
                self.assertEqual(support.run_script(SCRIPT, "garbage", (mode,), env.env()).returncode, 0)

    def test_mode_stop_does_not_mutate_its_input(self):
        with support.BrainEnv() as env:
            repo = make_repo(env.root)
            (repo / "app.py").write_text(BODY)
            state = {"baseline": "", "asked": [], "count": 0}
            reason, new = rl.mode_stop({"cwd": str(repo)}, state)
            self.assertTrue(reason)
            self.assertEqual(state["asked"], [])
            self.assertEqual(new["count"], 1)

    def test_module_contract_and_reviewer_agent_exists(self):
        import carlo_modules as mods
        module = mods.load_module(ROOT / "modules" / "review-loop")
        self.assertEqual({h["event"] for h in module.hooks}, {"SessionStart", "Stop"})
        self.assertTrue((ROOT / "modules" / "agents-skills" / "src" / "agents" / "reviewer.md").exists())


if __name__ == "__main__":
    unittest.main()
