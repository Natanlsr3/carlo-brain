"""get.sh (one-line installer) against a local file:// source, in a fake HOME. No network, no real claude."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GET = ROOT / "get.sh"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]


def make_source(tmp: Path) -> Path:
    """A throwaway git repo holding the current working tree (so uncommitted changes are tested too)."""
    source = tmp / "source"
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv"))
    subprocess.run(GIT + ["init", "-q"], cwd=source, check=True)
    subprocess.run(GIT + ["add", "-A"], cwd=source, check=True)
    subprocess.run(GIT + ["commit", "-q", "-m", "snapshot"], cwd=source, check=True)
    return source


def run_get(home: Path, source: Path, *args: str, extra: dict = None, path: str = None) -> subprocess.CompletedProcess:
    env = {"HOME": str(home), "PATH": path or os.environ.get("PATH", ""), "CARLO_NO_LAUNCHD": "1",
           "CARLO_BRAIN_REPO": f"file://{source}", "SHELL": "/bin/zsh", **(extra or {})}
    return subprocess.run(["bash", str(GET), *args], capture_output=True, text=True, env=env, timeout=180,
                          stdin=subprocess.DEVNULL)


class GetShTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.source = make_source(self.tmp)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_clone_install_hint_then_update(self) -> None:
        first = run_get(self.home, self.source)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertTrue((self.home / "carlo-brain" / ".git").is_dir())
        self.assertTrue((self.home / "carlo-vault" / "00_System" / "MAP.md").exists(), "default vault ~/carlo-vault")
        self.assertTrue((self.home / ".claude" / "skills" / "setup" / "SKILL.md").exists())
        self.assertIn("export PATH=", first.stdout, "PATH line when ~/.local/bin is not on PATH")
        self.assertEqual(first.stdout.strip().splitlines()[-1], "Next: run claude and type: setup (5 questions, it fills your map)")
        second = run_get(self.home, self.source)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("Updating", second.stdout)

    def test_no_path_line_when_local_bin_is_on_path(self) -> None:
        path = f"{self.home / '.local' / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"
        res = run_get(self.home, self.source, path=path)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertNotIn("export PATH=", res.stdout)

    def test_arguments_pass_through_and_dir_override(self) -> None:
        target, vault = self.tmp / "elsewhere", self.tmp / "my-vault"
        res = run_get(self.home, self.source, "--vault", str(vault), extra={"CARLO_BRAIN_DIR": str(target)})
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertTrue((target / ".git").is_dir())
        self.assertTrue((vault / "00_System" / "MAP.md").exists())
        self.assertFalse((self.home / "carlo-vault").exists())

    def test_never_overwrites_a_non_git_folder(self) -> None:
        folder = self.home / "carlo-brain"
        folder.mkdir()
        (folder / "mine.txt").write_text("keep me")
        res = run_get(self.home, self.source)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("not a git checkout", res.stderr)
        self.assertEqual((folder / "mine.txt").read_text(), "keep me")
        self.assertFalse((self.home / "carlo-vault").exists())

    def test_missing_git_is_a_clear_message(self) -> None:
        empty = self.tmp / "empty-path"
        empty.mkdir()
        bash = shutil.which("bash")
        res = subprocess.run([bash, str(GET)], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30,
                             env={"HOME": str(self.home), "PATH": str(empty)})
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("git is required", res.stderr)

    def test_script_is_safe_by_construction(self) -> None:
        text = GET.read_text()
        self.assertIn("set -euo pipefail", text)
        self.assertNotIn("sudo ", text.replace("sudo apt install git", ""))
        self.assertTrue(os.access(GET, os.X_OK))


if __name__ == "__main__":
    unittest.main()
