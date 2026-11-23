"""Search tests: temporary folders, simulated Mail index, fake readers. No real personal data."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import search as sr  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.brain = self.root / "brain"
        (self.brain / "config.d").mkdir(parents=True)
        self.vault = self.root / "vault"
        self.docs = self.root / "docs"
        for folder in (self.vault, self.docs):
            folder.mkdir()
        (self.brain / "config.json").write_text(json.dumps({"vault": str(self.vault)}))
        (self.brain / "config.d" / "search.json").write_text(json.dumps({"folders": [str(self.docs)]}))
        os.environ.pop("CARLO_VAULT", None)
        self.addCleanup(self._tmp.cleanup)

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class FileSearchTests(Base):
    def test_vault_comes_before_folders_with_path_line_snippet(self):
        self.write(self.docs / "b.txt", "nothing\nthe Budget plan is here\n")
        self.write(self.vault / "a.md", "intro\n\nbudget decided: 5 percent\n")
        hits = sr.search_all("budget", ["vault", "folders"], self.brain)
        self.assertEqual([h.source for h in hits], ["vault", "files"])
        self.assertEqual((hits[0].path, hits[0].line), (str(self.vault / "a.md"), 3))
        self.assertIn("budget decided", hits[0].snippet)
        self.assertIn(f"{self.vault / 'a.md'}:3:", hits[0].render())

    def test_accents_case_and_all_terms_must_match(self):
        self.write(self.docs / "a.txt", "Réunion ÉCOLE lundi\nécole seulement\n")
        hits = sr.search_all("ecole reunion", ["folders"], self.brain)
        self.assertEqual([h.line for h in hits], [1])

    def test_file_name_match_has_line_zero(self):
        self.write(self.docs / "invoice_march.txt", "unrelated content")
        hit = sr.search_all("invoice", ["folders"], self.brain)[0]
        self.assertEqual((hit.line, hit.snippet), (0, "(file name)"))

    def test_deny_list_hides_secret_files_and_folders(self):
        env_name = "." + "env"
        for rel in (env_name, "app" + env_name, ".ssh/config", "keys/openrouter", "Library/x.txt", "my_token.txt",
                    "SECRETS.md", "server.pem", ".zshrc", "creds/password_list.txt", "notes/.git/HEAD"):
            self.write(self.docs / rel, "needle inside\n")
        self.write(self.docs / "ok.txt", "needle inside\n")
        hits = sr.search_all("needle", ["folders"], self.brain)
        self.assertEqual([Path(h.path).name for h in hits], ["ok.txt"])

    def test_config_extends_the_deny_list(self):
        (self.brain / "config.d" / "search.json").write_text(json.dumps({"folders": [str(self.docs)], "deny_dirs": ["private"],
                                                                         "deny_files": ["*.bak"]}))
        self.write(self.docs / "private" / "a.txt", "needle")
        self.write(self.docs / "b.bak", "needle")
        self.write(self.docs / "c.txt", "needle")
        self.assertEqual([Path(h.path).name for h in sr.search_all("needle", ["folders"], self.brain)], ["c.txt"])

    def test_vault_inside_a_library_folder_is_still_searched(self):
        vault = self.root / "Library" / "Mobile" / "vault"
        self.write(vault / "n.md", "needle here")
        (self.brain / "config.json").write_text(json.dumps({"vault": str(vault)}))
        self.assertEqual(len(sr.search_all("needle", ["vault"], self.brain)), 1)

    def test_binary_and_huge_files_are_skipped(self):
        (self.docs / "bin.dat").write_bytes(b"needle\0\1\2")
        self.write(self.docs / "photo.png", "needle")
        self.write(self.docs / "huge.txt", "needle " * 300000)
        self.assertEqual(sr.search_all("needle", ["folders"], self.brain), [])

    def test_secret_looking_line_is_never_printed(self):
        self.write(self.docs / "notes.txt", "my api_key = sk-abcdefghijklmnop1234567890\n")
        hit = sr.search_all("api_key", ["folders"], self.brain)[0]
        self.assertEqual(hit.snippet, sr.REDACTED)
        self.assertNotIn("sk-abc", hit.render())

    def test_caps_total_and_per_file(self):
        for i in range(10):
            self.write(self.docs / f"f{i}.txt", "needle\n" * 9)
        self.assertEqual(len(sr.search_all("needle", ["folders"], self.brain, limit=7)), 7)
        (self.brain / "config.d" / "search.json").write_text(json.dumps({"folders": [str(self.docs)], "max_per_file": 2, "max_results": 100}))
        self.assertEqual(len(sr.search_all("needle", ["folders"], self.brain)), 20)

    def test_long_line_is_trimmed_around_the_match(self):
        self.write(self.docs / "long.txt", "x" * 500 + " needle " + "y" * 500)
        snippet = sr.search_all("needle", ["folders"], self.brain)[0].snippet
        self.assertIn("needle", snippet)
        self.assertLess(len(snippet), 200)

    def test_empty_query_and_missing_vault_are_harmless(self):
        self.assertEqual(sr.search_all("   ", ["vault", "folders"], self.brain), [])
        (self.brain / "config.json").write_text("{}")
        self.assertEqual(sr.search_all("x", ["vault"], self.brain), [])


class AppleAndSpotlightTests(Base):
    def make_mail(self) -> Path:
        index = self.root / "Mail" / "V10" / "MailData" / "Envelope Index"
        index.parent.mkdir(parents=True)
        con = sqlite3.connect(index)
        con.executescript("create table addresses(ROWID integer primary key, address, comment);"
                          "create table subjects(ROWID integer primary key, subject);"
                          "create table messages(ROWID integer primary key, sender, subject, date_received, deleted, read);"
                          "insert into addresses values (1,'alice@example.org','Alice');"
                          "insert into subjects values (1,'Quarterly invoice'),(2,'Lunch');"
                          "insert into messages values (1,1,1,1700000000,0,1),(2,1,2,1700000100,0,1),(3,1,1,1700000200,1,1);")
        con.commit()
        con.close()
        return index

    def test_mail_searches_subject_and_sender_and_skips_deleted(self):
        index = self.make_mail()
        hits = sr.search_mail("invoice", sr.Options(), index=index)
        self.assertEqual(len(hits), 1)
        self.assertIn("Quarterly invoice", hits[0].snippet)
        self.assertEqual(len(sr.search_mail("alice", sr.Options(), index=index)), 2)
        self.assertEqual(sr.search_mail("nothing", sr.Options(), index=index), [])
        self.assertEqual(sr.find_mail_index(self.root / "Mail"), index)

    def test_mail_database_is_opened_read_only(self):
        index = self.make_mail()
        before = index.stat().st_mtime_ns
        sr.search_mail("invoice", sr.Options(), index=index)
        self.assertEqual(index.stat().st_mtime_ns, before)

    def test_broken_mail_index_gives_no_results_not_a_crash(self):
        bad = self.root / "bad"
        bad.write_text("nope")
        self.assertEqual(sr.search_mail("x", sr.Options(), index=bad), [])

    def test_notes_and_messages_use_the_connectors_readers(self):
        reader = self.brain / "connectors" / "apple"
        reader.mkdir(parents=True)
        for name in ("notes.py", "messages.py"):
            (reader / name).write_text("import sys\nprint('hit for ' + sys.argv[2] + ' in " + name + "')\nprint('1 result(s)')\n")
        notes = sr.search_apple("notes", "plan", self.brain, sr.Options(), platform="darwin")
        self.assertEqual([(h.source, h.snippet) for h in notes], [("notes", "hit for plan in notes.py")])
        self.assertEqual(sr.search_apple("messages", "plan", self.brain, sr.Options(), platform="darwin")[0].source, "messages")

    def test_apple_sources_are_skipped_off_macos_or_without_the_module(self):
        self.assertEqual(sr.search_apple("notes", "x", self.brain, sr.Options(), platform="linux"), [])
        self.assertEqual(sr.search_apple("notes", "x", self.brain, sr.Options(), platform="darwin"), [])
        self.assertEqual(sr.search_mail("x", sr.Options(), platform="linux"), [])

    def test_spotlight_is_filtered_by_the_deny_list_and_macos_only(self):
        class Res:
            stdout = "/home/u/Documents/a.txt\n/home/u/.ssh/id_rsa\n/home/u/Library/Mail/x.emlx\n/home/u/notes_secret.md\n"
        hits = sr.search_spotlight("a", [Path("/home/u/Documents")], sr.Options(), "darwin", run=lambda *a, **k: Res())
        self.assertEqual([h.path for h in hits], ["/home/u/Documents/a.txt"])
        self.assertEqual(sr.search_spotlight("a", [Path("/x")], sr.Options(), "linux"), [])


class CommandTests(Base):
    def run_cli(self, *args):
        env = {**os.environ, "CARLO_BRAIN_HOME": str(self.brain), "HOME": str(self.root)}  # fake HOME: never touch the real Mail
        return subprocess.run([sys.executable, "-I", str(Path(sr.__file__)), *args], capture_output=True, text=True, env=env)

    def test_cli_prints_hits_and_json_and_exit_code(self):
        self.write(self.vault / "a.md", "the needle line")
        res = self.run_cli("needle", "--source", "vault")
        self.assertEqual(res.returncode, 0)
        self.assertIn("a.md:1:", res.stdout)
        self.assertIn("1 result(s)", res.stdout)
        data = json.loads(self.run_cli("needle", "--source", "vault", "--json").stdout)
        self.assertEqual(data[0]["line"], 1)
        self.assertEqual(self.run_cli("zzzz", "--source", "vault").returncode, 1)

    def test_nothing_is_written_by_a_search(self):
        self.write(self.vault / "a.md", "needle")
        before = sorted(str(p) for p in self.root.rglob("*"))
        self.run_cli("needle")
        self.assertEqual(sorted(str(p) for p in self.root.rglob("*")), before)

    def test_no_dash_characters_in_shipped_text(self):
        base = Path(sr.__file__).parent
        for path in [Path(sr.__file__), base / "skills" / "find-it" / "SKILL.md", base.parent / "module.toml"]:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(chr(0x2014), text)
            self.assertNotIn(chr(0x2013), text)


if __name__ == "__main__":
    unittest.main()
