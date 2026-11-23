"""Deep search tests: tiny real docx, xlsx, pptx and emlx fixtures in a temp dir, pdftotext mocked. No personal data."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import search as sr  # noqa: E402
import textextract as tx  # noqa: E402

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_zip(path: Path, members: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def make_docx(path: Path, paragraphs) -> Path:
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>' for t in paragraphs)
    return make_zip(path, {"word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>"})


def make_xlsx(path: Path, rows) -> Path:
    strings = [c for row in rows for c in row if isinstance(c, str)]
    sst = "".join(f"<si><t>{s}</t></si>" for s in strings)
    sheet_rows, index = "", 0
    for n, row in enumerate(rows, 1):
        cells = ""
        for col, value in enumerate(row):
            ref = "ABCDEF"[col] + str(n)
            if isinstance(value, str):
                cells += f'<c r="{ref}" t="s"><v>{index}</v></c>'
                index += 1
            else:
                cells += f'<c r="{ref}"><v>{value}</v></c>'
        sheet_rows += f'<row r="{n}">{cells}</row>'
    return make_zip(path, {"xl/sharedStrings.xml": f"<sst>{sst}</sst>",
                           "xl/worksheets/sheet1.xml": f"<worksheet><sheetData>{sheet_rows}</sheetData></worksheet>"})


def make_pptx(path: Path, slides) -> Path:
    members = {f"ppt/slides/slide{i}.xml": f"<p:sld><a:p><a:r><a:t>{t}</a:t></a:r></a:p></p:sld>" for i, t in enumerate(slides, 1)}
    return make_zip(path, members)


def make_emlx(path: Path, subject: str, plain: str = "", html: str = "", sender: str = "sam@example.org") -> Path:
    if plain and html:
        mime = ('Content-Type: multipart/alternative; boundary="b"\n\n--b\nContent-Type: text/plain; charset=utf-8\n\n' + plain +
                '\n--b\nContent-Type: text/html; charset=utf-8\n\n' + html + "\n--b--\n")
    elif html:
        mime = "Content-Type: text/html; charset=utf-8\n\n" + html + "\n"
    else:
        mime = "Content-Type: text/plain; charset=utf-8\n\n" + plain + "\n"
    raw = f"From: {sender}\nTo: me@example.org\nSubject: {subject}\nDate: Mon, 2 Mar 2026 10:00:00 +0000\n{mime}".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(str(len(raw)).encode() + b"\n" + raw + b'<?xml version="1.0"?><plist><dict/></plist>')
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.brain = self.root / "brain"
        (self.brain / "config.d").mkdir(parents=True)
        self.docs = self.root / "docs"
        self.docs.mkdir()
        self.conf({"folders": [str(self.docs)]})
        (self.brain / "config.json").write_text("{}")
        os.environ.pop("CARLO_VAULT", None)
        self.addCleanup(self._tmp.cleanup)

    def conf(self, data):
        (self.brain / "config.d" / "search.json").write_text(json.dumps(data))

    def find(self, query, **kw):
        return sr.search_all(query, ["folders"], self.brain, **kw)


class OfficeTests(Base):
    def test_docx_content_is_found_with_line_and_snippet(self):
        make_docx(self.docs / "contract.docx", ["Intro", "The renewal clause is in March &amp; April"])
        hits = self.find("renewal clause")
        self.assertEqual([(h.line, Path(h.path).name) for h in hits], [(2, "contract.docx")])
        self.assertIn("March & April", hits[0].snippet)

    def test_xlsx_cells_shared_and_numbers_are_one_line_per_row(self):
        make_xlsx(self.docs / "budget.xlsx", [["item", "cost"], ["printer", 249]])
        hits = self.find("printer 249")
        self.assertEqual(hits[0].line, 2)
        self.assertIn("printer | 249", hits[0].snippet)

    def test_pptx_slides_in_numeric_order(self):
        make_pptx(self.docs / "deck.pptx", ["first slide", "pricing slide ten"])
        self.assertEqual(self.find("pricing")[0].line, 2)

    def test_broken_zip_falls_back_to_the_file_name(self):
        (self.docs / "report.docx").write_bytes(b"not a zip")
        hits = self.find("report")
        self.assertEqual((hits[0].line, hits[0].snippet), (0, "(file name)"))
        self.assertEqual(self.find("zzzz"), [])

    def test_zip_bomb_is_refused_not_expanded(self):
        make_zip(self.docs / "bomb.docx", {"word/document.xml": "<w:t>needle</w:t>" + " " * 3_000_000})
        self.conf({"folders": [str(self.docs)], "max_doc_mb": 0})
        self.assertIsNone(tx.extract(self.docs / "bomb.docx", 100_000))  # file size cap
        small = tx.extract_docx  # expansion cap: members bigger than the limit raise
        with self.assertRaises(ValueError):
            small(self.docs / "bomb.docx", 1_000_000)

    def test_size_cap_is_configurable(self):
        make_docx(self.docs / "big.docx", ["needle here"])
        self.conf({"folders": [str(self.docs)], "max_doc_mb": 0})
        self.assertEqual(self.find("needle"), [])
        self.conf({"folders": [str(self.docs)], "max_doc_mb": 20})
        self.assertEqual(len(self.find("needle")), 1)

    def test_secret_looking_line_inside_a_document_is_hidden(self):
        make_docx(self.docs / "notes.docx", ["login", "password = hunter2hunter2 for the portal"])
        self.assertEqual(self.find("portal"), [])  # the line is dropped before matching (and before any caching)
        self.assertNotIn("hunter2", json.dumps([h.snippet for h in self.find("login")]))
        self.assertEqual(self.find("login")[0].line, 1)

    def test_denied_names_are_never_opened(self):
        make_docx(self.docs / "my_password_list.docx", ["needle"])
        make_docx(self.docs / "keys" / "ok.docx", ["needle"])
        self.assertEqual(self.find("needle"), [])

    def test_deep_off_keeps_the_old_behaviour(self):
        make_docx(self.docs / "contract.docx", ["renewal clause"])
        self.conf({"folders": [str(self.docs)], "deep": False})
        self.assertEqual(self.find("renewal"), [])
        self.assertEqual(self.find("contract")[0].snippet, "(file name)")


class PdfTests(Base):
    def setUp(self):
        super().setUp()
        (self.docs / "invoice.pdf").write_bytes(b"%PDF-1.4 fake")

    def res(self, out="", code=0, err=""):
        return subprocess.CompletedProcess([], code, out, err)

    def test_pdftotext_is_used_first(self):
        calls = []

        def fake_run(argv, **kw):
            calls.append(argv[0])
            return self.res("Total due\nthe rent is 900\n")
        with mock.patch.object(tx.shutil, "which", return_value="/usr/bin/pdftotext"), mock.patch.object(tx.subprocess, "run", fake_run):
            hits = self.find("rent")
        self.assertEqual((hits[0].line, calls), (2, ["/usr/bin/pdftotext"]))

    def test_falls_back_to_mdimport_then_mdls_on_macos(self):
        outputs = {"mdimport": self.res("", 0, 'kMDItemTextContent = "alpha\\nthe lease ends soon";\n'),
                   "mdls": self.res("(null)")}
        with mock.patch.object(tx.shutil, "which", return_value=None), mock.patch.object(tx.sys, "platform", "darwin"), \
                mock.patch.object(tx.subprocess, "run", lambda argv, **kw: outputs[argv[0]]):
            self.assertEqual(self.find("lease")[0].line, 2)
            outputs["mdimport"] = self.res("", 0, "nothing useful")
            outputs["mdls"] = self.res("spotlight text: lease from mdls")
            self.assertIn("mdls", self.find("lease")[0].snippet)

    def test_no_reader_falls_back_to_the_file_name(self):
        with mock.patch.object(tx.shutil, "which", return_value=None), mock.patch.object(tx.sys, "platform", "linux"):
            hits = self.find("invoice")
        self.assertEqual((hits[0].line, hits[0].snippet), (0, "(file name)"))

    def test_reader_timeout_or_error_never_raises(self):
        def boom(argv, **kw):
            raise subprocess.TimeoutExpired(argv, 1)
        with mock.patch.object(tx.shutil, "which", return_value="/usr/bin/pdftotext"), mock.patch.object(tx.subprocess, "run", boom):
            self.assertEqual(self.find("invoice")[0].line, 0)


class CacheTests(Base):
    def test_cache_is_off_by_default_and_on_with_the_option(self):
        make_docx(self.docs / "a.docx", ["needle one"])
        self.find("needle")
        self.assertFalse((self.brain / "state" / "search-cache").exists())
        self.conf({"folders": [str(self.docs)], "cache": True})
        self.find("needle")
        entries = list((self.brain / "state" / "search-cache").glob("*.json"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].stat().st_mode & 0o077, 0)

    def test_cache_hit_skips_extraction_and_mtime_change_invalidates(self):
        self.conf({"folders": [str(self.docs)], "cache": True})
        doc = make_docx(self.docs / "a.docx", ["needle one"])
        self.find("needle")
        with mock.patch.object(tx, "extract", side_effect=AssertionError("must come from the cache")):
            self.assertEqual(len(self.find("needle")), 1)
        make_docx(doc, ["needle two"])
        stamp = time.time() + 100
        os.utime(doc, (stamp, stamp))
        self.assertEqual(self.find("needle")[0].snippet, "needle two")

    def test_cached_text_is_already_redacted(self):
        self.conf({"folders": [str(self.docs)], "cache": True})
        make_docx(self.docs / "a.docx", ["api_key = abcdef123456789 here", "other line"])
        self.find("other")
        raw = next((self.brain / "state" / "search-cache").glob("*.json")).read_text()
        self.assertNotIn("abcdef123456789", raw)

    def test_rebuild_cache_refills_and_the_cli_flag_works(self):
        make_docx(self.docs / "a.docx", ["needle one"])
        make_xlsx(self.docs / "b.xlsx", [["needle", 1]])
        self.assertEqual(sr.rebuild_cache(self.brain), 2)
        cache = self.brain / "state" / "search-cache"
        stale = cache / "stale.json"
        stale.write_text("{}")
        env = {**os.environ, "CARLO_BRAIN_HOME": str(self.brain), "HOME": str(self.root)}
        res = subprocess.run([sys.executable, "-I", str(Path(sr.__file__)), "--rebuild-cache"], capture_output=True, text=True, env=env)
        self.assertEqual((res.returncode, "2 document(s)" in res.stdout), (0, True), res.stdout + res.stderr)
        self.assertFalse(stale.exists())
        both = subprocess.run([sys.executable, "-I", str(Path(sr.__file__)), "--rebuild-cache", "needle", "--source", "folders"],
                              capture_output=True, text=True, env=env)
        self.assertEqual(both.returncode, 0)
        self.assertIn("a.docx", both.stdout)
        self.assertNotEqual(subprocess.run([sys.executable, "-I", str(Path(sr.__file__))], capture_output=True, env=env).returncode, 0)

    def test_cache_stops_growing_at_its_cap(self):
        self.conf({"folders": [str(self.docs)], "cache": True, "cache_max_mb": 0})
        make_docx(self.docs / "a.docx", ["needle"])
        self.assertEqual(len(self.find("needle")), 1)
        self.assertFalse(list((self.brain / "state" / "search-cache").glob("*.json")))


class MailBodyTests(Base):
    def setUp(self):
        super().setUp()
        self.mail = self.root / "Mail"
        self.msgs = self.mail / "V10" / "ACCOUNT" / "INBOX.mbox" / "Data" / "Messages"

    def mail_hits(self, query, **kw):
        return sr.search_all(query, ["mail"], self.brain, platform="darwin", mail_root=self.mail, **kw)

    def test_plain_text_is_preferred_and_headers_are_searchable(self):
        make_emlx(self.msgs / "1.emlx", "Lunch plan", plain="see you at the bistro\nbring the slides", html="<p>html only words</p>")
        hits = self.mail_hits("bistro")
        self.assertEqual((hits[0].source, Path(hits[0].path).name), ("mail", "1.emlx"))
        self.assertEqual(self.mail_hits("html only"), [])
        self.assertTrue(self.mail_hits("lunch plan"))

    def test_html_only_mail_is_stripped_of_tags_style_and_entities(self):
        make_emlx(self.msgs / "2.emlx", "Offer", html="<style>.x{color:red}</style><p>The <b>quote</b> is 12&nbsp;000 &amp; fair</p>")
        hits = self.mail_hits("quote")
        self.assertIn("The quote is", hits[0].snippet)
        self.assertNotIn("<b>", hits[0].snippet)
        self.assertEqual(self.mail_hits("color red"), [])

    def test_sent_is_included_trash_and_drafts_are_not(self):
        make_emlx(self.mail / "V10" / "ACCOUNT" / "Sent Messages.mbox" / "Data" / "Messages" / "3.emlx", "Re: plan", plain="needle in sent")
        make_emlx(self.mail / "V10" / "ACCOUNT" / "Deleted Messages.mbox" / "Messages" / "4.emlx", "Old", plain="needle in trash")
        make_emlx(self.mail / "V10" / "ACCOUNT" / "Drafts.mbox" / "Messages" / "5.emlx", "Wip", plain="needle in drafts")
        paths = [Path(h.path).name for h in self.mail_hits("needle")]
        self.assertEqual(paths, ["3.emlx"])

    def test_partial_emlx_and_broken_files_do_not_crash(self):
        make_emlx(self.msgs / "6.partial.emlx", "Part", plain="needle partial body")
        (self.msgs / "7.emlx").write_bytes(b"\xff\xfe garbage")
        (self.msgs / "8.emlx").write_bytes(b"")
        self.assertEqual([Path(h.path).name for h in self.mail_hits("needle")], ["6.partial.emlx"])

    def test_secret_looking_body_line_is_hidden_and_size_cap_applies(self):
        make_emlx(self.msgs / "9.emlx", "Access", plain="the portal password: Sup3rSecretValue\nportal ready")
        hits = self.mail_hits("portal")
        self.assertEqual(hits[0].snippet, sr.REDACTED)
        self.conf({"folders": [str(self.docs)], "max_mail_kb": 0})
        self.assertEqual(self.mail_hits("portal"), [])

    def test_off_macos_and_deep_off_return_nothing_and_nothing_is_written(self):
        make_emlx(self.msgs / "1.emlx", "x", plain="needle")
        before = sorted(str(p) for p in self.root.rglob("*"))
        self.assertEqual(sr.search_mail_bodies(["needle"], sr.Options(), platform="linux"), [])
        self.assertEqual(sr.search_mail_bodies(["needle"], sr.Options(deep=False), self.mail), [])
        self.mail_hits("needle")
        self.assertEqual(sorted(str(p) for p in self.root.rglob("*")), before)

    def test_time_budget_stops_the_walk(self):
        make_emlx(self.msgs / "1.emlx", "x", plain="needle")
        self.assertEqual(sr.search_mail_bodies(["needle"], sr.Options(), self.mail, deadline=time.monotonic() - 1), [])


class TextTests(unittest.TestCase):
    def test_no_dash_characters_in_new_text(self):
        base = Path(tx.__file__).parent
        for path in [Path(tx.__file__), Path(__file__), base / "search.py", base / "skills" / "find-it" / "SKILL.md",
                     base.parent / "README.md"]:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(chr(0x2014), text, path)
            self.assertNotIn(chr(0x2013), text, path)


if __name__ == "__main__":
    unittest.main()
