"""Tests for `carlo scan` and the deep setup state. Only fake HOME trees are scanned, never the real one."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

import carlo_cli  # noqa: E402
import carlo_mapdiff as mapdiff  # noqa: E402
import carlo_scan as scan  # noqa: E402
import carlo_scan_sources as sources  # noqa: E402
import carlo_setup as setup_state  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def make_repo(path: Path, remote: str = "", readme: str = "") -> None:
    path.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **GIT_ENV}
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=env)
    if readme:
        (path / "README.md").write_text(readme, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "--allow-empty", "-m", "first"], check=True, env=env)
    if remote:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", remote], check=True, env=env)


def args(**kw) -> SimpleNamespace:
    base = dict(quick=False, full=False, background=False, status=False, yes=False, root=None, max_seconds=None, dismiss=None)
    return SimpleNamespace(**{**base, **kw})


def fake_tree(home: Path) -> Path:
    desk = home / "Desktop"
    make_repo(desk / "alpha", "https://user:SECRETPASS@github.example.com/me/alpha.git", "# Alpha\n\nA tool that does alpha things.\n")
    make_repo(desk / "beta", "git@git.example.org:me/beta.git")
    (desk / "Notes").mkdir()
    (desk / "Notes" / ".obsidian").mkdir()
    for i in range(3):
        (desk / "Notes" / f"n{i}.md").write_text(f"# Note {i}\ntext\n")
    (desk / "Thesis").mkdir()
    for i in range(6):
        (desk / "Thesis" / f"chapter{i}.txt").write_text(f"Chapter {i}\n")
    (desk / "alpha" / ".env").write_text("OPENAI_API_KEY=sk-aaaaaaaaaaaaaaaaaaaaaaaa\n")
    (desk / "alpha" / "token_notes.md").write_text("# secret title\n")
    (desk / "node_modules" / "pkg").mkdir(parents=True)
    (desk / "node_modules" / "pkg" / "index.js").write_text("x")
    (home / ".ssh").mkdir()
    (home / ".ssh" / "id_rsa").write_text("PRIVATE")
    (desk / "Library").mkdir()
    (desk / "Library" / "hidden.txt").write_text("x")
    return desk


class ScanTest(unittest.TestCase):
    def test_scans_fake_home_and_ignores_secrets(self):
        with support.BrainEnv(with_vault=False) as env:
            desk = fake_tree(env.home)
            result = scan.scan_roots([desk], "full")
            text = json.dumps(result)
            names = {p["name"]: p for p in result["projects"]}
            self.assertEqual(set(names), {"alpha", "beta"})
            self.assertEqual(names["alpha"]["remote_host"], "github.example.com")
            self.assertEqual(names["beta"]["remote_host"], "git.example.org")
            self.assertIsNotNone(names["alpha"]["last_commit"])
            self.assertEqual(names["alpha"]["last_commit_days"], 0)
            self.assertIn("A tool that does alpha things.", names["alpha"]["readme_head"])
            for secret in ("SECRETPASS", "sk-aaaa", ".ssh", "id_rsa", "token_notes", "node_modules", "hidden.txt", "/.env"):
                self.assertNotIn(secret, text)
            self.assertEqual([v["markdown_files"] for v in result["notes"]["obsidian"]], [3])
            self.assertEqual([f["name"] for f in result["recent_folders"]], ["Thesis"])
            self.assertTrue(result["tools"]["git"])
            self.assertEqual(result["sources"]["mail"], "absent")
            self.assertEqual(result["notes"]["apple_notes"]["count"], None)

    def test_caps_depth_entries_and_time(self):
        with support.BrainEnv(with_vault=False) as env:
            deep = env.home / "Desktop" / "a" / "b" / "c" / "d" / "e"
            deep.mkdir(parents=True)
            (deep / "deep.txt").write_text("x")
            (env.home / "Desktop" / "top.txt").write_text("x")
            quick = json.dumps(scan.scan_roots([env.home / "Desktop"], "quick"))
            self.assertIn("top.txt", quick)
            self.assertNotIn("deep.txt", quick)  # quick stops at depth 3
            self.assertIn("deep.txt", json.dumps(scan.scan_roots([env.home / "Desktop"], "full")))
            many = env.home / "Many"
            many.mkdir()
            for i in range(600):
                (many / f"f{i}.txt").write_text("x")
            capped = scan.Walk(many, 3, time.monotonic() + 30, 300, 5, [], [])
            capped.run()
            self.assertEqual(capped.reason, "entry cap reached")
            self.assertLessEqual(capped.entries, 300)
            self.assertEqual(len(capped.heap), 5)
            timed = scan.scan_roots([many], "quick", max_seconds=-1)
            self.assertTrue(timed["stats"]["truncated"])
            self.assertEqual(timed["stats"]["reason"], "time cap reached")

    def test_top_n_recent_files_per_root(self):
        with support.BrainEnv(with_vault=False) as env:
            folder = env.home / "Documents"
            folder.mkdir()
            for i in range(30):
                path = folder / f"d{i}.txt"
                path.write_text("x")
                os.utime(path, (1_700_000_000 + i, 1_700_000_000 + i))
            result = scan.scan_roots([folder], "quick")
            files = result["recent_files"][str(folder)]
            self.assertEqual(len(files), 15)
            self.assertTrue(files[0]["path"].endswith("d29.txt"))

    def test_markdown_title_and_secret_line_hidden(self):
        with support.BrainEnv(with_vault=False) as env:
            folder = env.home / "Documents"
            folder.mkdir()
            (folder / "plan.md").write_text("# The plan\nbody\n")
            (folder / "odd.md").write_text("password = hunter2hunter2\n")
            result = scan.scan_roots([folder], "quick")
            titles = {Path(f["path"]).name: f.get("title") for f in result["recent_files"][str(folder)]}
            self.assertEqual(titles["plan.md"], "# The plan")
            self.assertIn("hidden", titles["odd.md"])
            self.assertNotIn("hunter2", json.dumps(result))

    def test_sources_presence_and_mcp_names_only(self):
        with support.BrainEnv(with_vault=False) as env:
            (env.home / "Library" / "Messages").mkdir(parents=True)
            (env.home / "Library" / "Messages" / "chat.db").write_text("DO NOT READ ME")
            (env.home / ".claude.json").write_text(json.dumps({"mcpServers": {"notion": {"command": "x", "env": {"TOKEN": "supersecretvalue"}}}}))
            result = scan.scan_roots([], "quick")
            self.assertEqual(result["sources"]["messages"], "readable")
            self.assertEqual(result["sources"]["notion_mcp"], "configured")
            self.assertEqual(result["sources"]["google_mcp"], "not configured")
            dumped = json.dumps(result)
            self.assertNotIn("supersecretvalue", dumped)
            self.assertNotIn("DO NOT READ ME", dumped)

    def test_deny_list_covers_the_search_module(self):
        search_src = support.module_src("search")
        self.assertTrue(search_src)
        import search as search_module
        self.assertTrue(search_module.DENY_DIRS <= scan.DENY_DIRS)
        self.assertTrue(set(search_module.DENY_FILES) <= set(scan.DENY_FILES))

    def test_host_parsing_drops_credentials(self):
        self.assertEqual(sources.host_of("https://u:p@Example.com/x/y.git"), "example.com")
        self.assertEqual(sources.host_of("git@host.test:me/x.git"), "host.test")
        self.assertEqual(sources.host_of("not a url"), "")


class ConsentAndModesTest(unittest.TestCase):
    def run_cli(self, a) -> tuple:
        out = io.StringIO()
        with redirect_stdout(out):
            code = scan.run_cli(a)
        return code, out.getvalue()

    def test_consent_required_and_folders_printed(self):
        with support.BrainEnv(with_vault=False) as env:
            fake_tree(env.home)
            code, out = self.run_cli(args(quick=True))  # stdin is not a tty under the test runner
            self.assertEqual(code, 2)
            self.assertIn("~/Desktop", out)
            self.assertIn("never reads mail or messages", out)
            self.assertIn("--yes", out)
            self.assertFalse((scan.scan_dir() / "scan.json").exists())
            self.assertFalse(scan.consent_path().exists())

    def test_yes_scans_and_writes_json_and_summary(self):
        with support.BrainEnv(with_vault=False) as env:
            fake_tree(env.home)
            code, out = self.run_cli(args(quick=True, yes=True))
            self.assertEqual(code, 0)
            data = json.loads((scan.scan_dir() / "scan.json").read_text())
            self.assertEqual(len(data["projects"]), 2)
            summary = (scan.scan_dir() / "scan.md").read_text()
            self.assertIn("alpha", summary)
            self.assertLess(len(summary.splitlines()), 70)
            self.assertEqual([str(r) for r in scan.consented_roots()], [str(env.home / "Desktop")])
            self.assertEqual(scan.read_progress()["status"], "done")
            self.assertNotIn(chr(0x2014), summary + out)

    def test_interactive_no_scans_nothing(self):
        with support.BrainEnv(with_vault=False) as env:
            fake_tree(env.home)
            with redirect_stdout(io.StringIO()):
                self.assertFalse(scan.confirmed(args(), [env.home / "Desktop"], "quick", ask=lambda _q: "n", tty=True))
                self.assertTrue(scan.confirmed(args(), [env.home / "Desktop"], "quick", ask=lambda _q: "y", tty=True))
                self.assertFalse(scan.confirmed(args(), [env.home / "Desktop"], "quick", tty=False))

    def test_background_writes_status_file_until_done(self):
        with support.BrainEnv(with_vault=False) as env:
            fake_tree(env.home)
            code, out = self.run_cli(args(full=True, yes=True, background=True))
            self.assertEqual(code, 0)
            self.assertIn("carlo scan --status", out)
            self.assertTrue(scan.progress_path().exists())
            deadline = time.time() + 30
            while time.time() < deadline and scan.read_progress().get("status") != "done":
                time.sleep(0.2)
            state = scan.read_progress()
            self.assertEqual(state["status"], "done")
            self.assertEqual(state["mode"], "full")
            self.assertEqual(state["projects_found"], 2)
            code, out = self.run_cli(args(status=True))
            self.assertIn("scan full: done", out)

    def test_status_reports_a_dead_scan(self):
        with support.BrainEnv(with_vault=False):
            scan.write_progress({"status": "running", "mode": "full", "pid": 99999999})
            self.assertIn("stopped", scan.status_lines()[0])

    def test_status_without_any_scan(self):
        with support.BrainEnv(with_vault=False):
            self.assertIn("No scan yet", scan.status_lines()[0])

    def test_cli_parser_exposes_scan_and_setup(self):
        parsed = carlo_cli.build_parser().parse_args(["scan", "--full", "--background", "--yes", "--root", "/x"])
        self.assertTrue(parsed.full and parsed.background and parsed.yes)
        self.assertEqual(parsed.root, ["/x"])
        self.assertEqual(carlo_cli.build_parser().parse_args(["setup"]).action, "status")


class SetupStateTest(unittest.TestCase):
    def test_progress_resumes_where_it_stopped(self):
        with support.BrainEnv(with_vault=False):
            self.assertFalse(setup_state.in_progress())
            setup_state.save_progress("consent", {"role": "founder"}, done=True)
            state = setup_state.save_progress("interview", {"style": "short"})
            self.assertEqual(state["step"], "interview")
            self.assertEqual(state["steps_done"], ["consent"])
            again = setup_state.load_progress()
            self.assertEqual(again["answers"], {"role": "founder", "style": "short"})
            self.assertTrue(setup_state.in_progress())
            self.assertIn("step 'interview'", setup_state.reminders(date(2026, 1, 1))[0])
            setup_state.save_progress("interview", done=True)
            self.assertEqual(setup_state.load_progress()["step"], "map")
            with self.assertRaises(ValueError):
                setup_state.save_progress("nonsense")
            setup_state.save_progress("done", done=True)
            self.assertFalse(setup_state.in_progress())
            self.assertEqual(setup_state.reminders(date(2026, 1, 1)), [])

    def test_plan_session_validates_and_stores_the_slot(self):
        with support.BrainEnv(with_vault=False) as env:
            plan = setup_state.plan_session("2026-11-27", "18:00", today=date(2026, 11, 23))
            stored = json.loads((env.brain / "state" / "setup" / "next_session.json").read_text())
            self.assertEqual((stored["date"], stored["time"]), ("2026-11-27", "18:00"))
            self.assertEqual(plan["date"], "2026-11-27")
            for bad in (("27/11/2026", ""), ("2026-11-27", "6pm"), ("2026-11-01", "")):
                with self.assertRaises(ValueError):
                    setup_state.plan_session(*bad, today=date(2026, 11, 23))

    def test_cli_save_plan_status_and_reset(self):
        with support.BrainEnv(with_vault=False):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(carlo_cli.main(["setup", "save", "scan", "--done", "--answer", "who=a founder"]), 0)
                self.assertEqual(carlo_cli.main(["setup", "plan", "--date", "2999-01-02", "--time", "10:30"]), 0)
                self.assertEqual(carlo_cli.main(["setup", "status"]), 0)
                self.assertEqual(carlo_cli.main(["setup", "plan", "--date", "nope"]), 1)
                self.assertEqual(carlo_cli.main(["setup", "reset"]), 0)
            text = out.getvalue()
            self.assertIn("step interview", text)
            self.assertIn("2999-01-02", text)
            self.assertIn("answers saved: who", text)
            self.assertFalse(setup_state.load_progress())


class MapDiffTest(unittest.TestCase):
    MAP = ("# MAP\n\n**Who**: Sam.\n\n**Active projects** (read the entry file first):\n"
           "- Oldproject: the old thing. Entry file: `10_Projects/oldproject/oldproject.md`.\n"
           "- **Known app**: runs fine.\n\n**Where to look for more**:\n- Todo: x\n")

    def scan_data(self, **kw) -> dict:
        repo = lambda n, d: {"name": n, "path": f"/w/{n}", "last_commit_days": d, "remote_host": None, "readme_head": []}  # noqa: E731
        base = {"projects": [repo("newthing", 3), repo("Known-App", 2), repo("oldproject", 90), repo("ancient", 400)],
                "recent_folders": [], "sources": {"mail": "readable", "messages": "denied", "contacts": "absent"}}
        return {**base, **kw}

    def test_project_names_read_from_the_map(self):
        self.assertEqual(mapdiff.map_project_names(self.MAP), ["Oldproject", "Known app"])

    def test_suggestions_new_inactive_and_source(self):
        items = mapdiff.build_suggestions(self.scan_data(), self.MAP, [], [], [])
        ids = [i["id"] for i in items]
        self.assertEqual(ids, ["project:newthing", "archive:Oldproject", "source:mail"])
        self.assertTrue(all(len(i["text"]) > 10 for i in items))

    def test_dismissed_connected_and_cap(self):
        items = mapdiff.build_suggestions(self.scan_data(), self.MAP, [], ["project:newthing"], ["connectors"])
        self.assertEqual([i["id"] for i in items], ["archive:Oldproject"])
        many = self.scan_data(projects=[{"name": f"p{i}", "path": f"/w/p{i}", "last_commit_days": 1} for i in range(8)])
        self.assertEqual(len(mapdiff.build_suggestions(many, self.MAP, [], [], [])), 3)

    def test_vault_folder_counts_as_known(self):
        items = mapdiff.new_projects(self.scan_data(), self.MAP, ["newthing"])
        self.assertEqual(items, [])

    def test_dismiss_is_persisted(self):
        with support.BrainEnv(with_vault=False):
            mapdiff.dismiss("project:x")
            mapdiff.dismiss("source:mail")
            self.assertEqual(mapdiff.load_state()["dismissed"], ["project:x", "source:mail"])
            with redirect_stdout(io.StringIO()):
                self.assertEqual(scan.run_cli(args(dismiss="archive:y")), 0)
            self.assertIn("archive:y", mapdiff.load_state()["dismissed"])

    def test_render_boot_asks_one_question_at_a_time(self):
        text = mapdiff.render_boot(mapdiff.build_suggestions(self.scan_data(), self.MAP), "2026-11-23")
        self.assertTrue(text.startswith("<!-- once -->"))
        self.assertIn("ONE closed question at a time", text)
        self.assertIn("Never edit MAP.md", text)
        self.assertLess(len(text), 1500)
        self.assertEqual(mapdiff.render_boot([], "2026-11-23"), "")


if __name__ == "__main__":
    unittest.main()
