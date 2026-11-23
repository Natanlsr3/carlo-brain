import json
import zipfile
from datetime import date, datetime, timedelta

from helpers_proactive import make_mail
from proactive.sources import schedules, slots, todo


def make_xlsx(path, rows):
    shared = []
    sheet_rows = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, text in enumerate(row):
            shared.append(text)
            cells.append(f'<c r="{chr(65 + c)}{r}" t="s"><v>{len(shared) - 1}</v></c>')
        sheet_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
        zf.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{''.join(sheet_rows)}</sheetData></worksheet>")
    return path


def test_xlsx_rows_and_rows_about_me(tmp_path):
    path = make_xlsx(tmp_path / "plan.xlsx", [["Name", "Mon", "Tue"], ["Alex", "9-17", "off"], ["Sam", "off", "9-17"]])
    rows = schedules.xlsx_rows(path)
    assert rows[1] == ["Alex", "9-17", "off"]
    assert schedules.rows_about_me(rows, ["alex"]) == ["Alex | 9-17 | off"]
    assert schedules.rows_about_me(rows, []) == []


def test_corrupt_or_oversized_xlsx_is_empty_not_a_crash(tmp_path):
    bad = tmp_path / "bad.xlsx"
    bad.write_text("not a zip")
    assert schedules.xlsx_rows(bad) == []
    assert schedules.xlsx_rows(tmp_path / "missing.xlsx") == []


def mails():
    return [
        (1, "2026-03-09 08:00:00", "boss@example.org", "Weekly schedule", ["plan.xlsx"], 0),
        (2, "2026-03-09 09:00:00", "boss@example.org", "Re: Weekly schedule", [], 0),   # same subject
        (3, "2026-03-09 10:00:00", "news@promo.example", "Our shift to summer", [], 0),  # automated, no file
        (4, "2026-03-09 11:00:00", "friend@example.org", "Lunch?", [], 0),
        (5, "2026-03-09 12:00:00", "hr@example.org", "Rota for April", ["rota.pdf"], 0),
    ]


def test_find_dedupes_skips_handled_and_automated(tmp_path):
    kw = schedules.words_regex([])
    found = schedules.find(mails(), kw, set())
    assert [s.title.split("'")[1] for s in found] == ["Rota for April", "Re: Weekly schedule"]
    handled = {"weekly schedule"}
    found2 = schedules.find(mails(), kw, handled)
    assert [s.title.split("'")[1] for s in found2] == ["Rota for April"]


def test_find_previews_my_rows(tmp_path):
    xlsx = make_xlsx(tmp_path / "plan.xlsx", [["Alex", "9-17"], ["Sam", "off"]])
    found = schedules.find(mails()[:1], schedules.words_regex([]), set(), lambda rid: [xlsx], ["Alex"])
    assert found[0].detail == ("Alex | 9-17",)
    assert found[0].kind == "schedule" and "add it?" in found[0].question


def test_extra_keywords(tmp_path):
    kw = schedules.words_regex(["lineup"])
    assert schedules.find([(9, "2026-03-09 12:00:00", "a@example.org", "Saturday lineup", [], 0)], kw, set())


def test_handled_file_roundtrip(tmp_path):
    f = tmp_path / "handled.txt"
    f.write_text("# comment\nWeekly Schedule  # done\n\n")
    assert schedules.load_handled(f) == {"weekly schedule"}
    assert schedules.load_handled(tmp_path / "none") == set()


def test_schedules_collect_from_fake_mail(tmp_path, cfg, brain_home):
    root = tmp_path / "Mail"
    root.mkdir()
    now = datetime.now()
    make_mail(root, [(1, int((now - timedelta(days=1)).timestamp()), "boss@example.org", "Team schedule", 1, 0)],
              attachments=[(1, "plan.xlsx")])
    cfg["sources"]["apple_mail"].update(enabled=True, root=str(root))
    result = schedules.collect(cfg, now)
    assert len(result.signals) == 1 and not result.outages
    (brain_home / "state" / "proactive").mkdir(parents=True, exist_ok=True)
    (brain_home / "state" / "proactive" / "handled.txt").write_text("team schedule\n")
    assert schedules.collect(cfg, now).signals == []


def test_schedules_missing_mail_is_outage(tmp_path, cfg):
    cfg["sources"]["apple_mail"]["root"] = str(tmp_path / "nothing")
    assert "Schedules (mail)" in schedules.collect(cfg, datetime.now()).outages[0]


# ---------- slots ----------

def test_slot_finder_positive_and_negative():
    assert slots.find("Can we do Thursday at 3pm?")
    assert slots.find("let's say 14:30 tomorrow")
    assert slots.find("March 12 at 10am works")
    assert not slots.find("I think 3 apples is fine")
    assert not slots.find("see you soon")


def test_slot_finder_ignores_quoted_mail():
    text = "Sounds good.\n\nOn Mon, Pat wrote:\n> let's meet Friday at 3pm"
    assert slots.find(text) == []


def test_slots_from_mail_filters_automated_invites_and_unknowns():
    rows = [
        (1, "2026-03-09 08:00:00", "pat@example.org", "Call", [], 0),
        (2, "2026-03-09 08:00:00", "noreply@cal.example", "Call", [], 0),
        (3, "2026-03-09 08:00:00", "pat@example.org", "Invitation: Call Friday 3pm", [], 0),
        (4, "2026-03-09 08:00:00", "stranger@example.org", "Call", [], 0),
    ]
    bodies = {i: "Can we talk Friday at 3pm?" for i in range(1, 5)}
    out = slots.from_mail(rows, lambda r: bodies[r], ["pat@example.org"], set())
    assert len(out) == 1 and "pat@example.org" in out[0]
    # direct recipients count even when the sender is unknown
    out2 = slots.from_mail(rows[3:], lambda r: bodies[r], [], {4})
    assert len(out2) == 1


def test_slots_summary_is_info_only():
    sig = slots.summarise(["a", "b", "c"], 2)[0]
    assert sig.question == "" and sig.detail == ("b", "c") and "3 meeting slots" in sig.title
    assert slots.summarise([], 5) == []


# ---------- todo ----------

TODAY = date(2026, 3, 10)


def test_todo_signals_overdue_today_tomorrow_only():
    items = [
        {"title": "Overdue thing", "due": "2026-03-08"},
        {"title": "Today thing", "due": "2026-03-10T09:00"},
        {"title": "Tomorrow thing", "due": "2026-03-11"},
        {"title": "Later", "due": "2026-03-20"},
        {"title": "Done", "due": "2026-03-10", "done": True},
        {"title": "", "due": "2026-03-10"},
        {"title": "No date"},
        {"title": "Bad date", "due": "soon"},
    ]
    sigs = todo.signals(items, TODAY)
    assert [(s.title, s.bonus) for s in sigs] == [("Due overdue: Overdue thing", 8), ("Due today: Today thing", 5),
                                                  ("Due tomorrow: Tomorrow thing", 0)]
    assert sigs[0].question.endswith("(yes / later)")


def test_todo_load_errors_are_source_errors(tmp_path, cfg):
    f = tmp_path / "t.json"
    f.write_text('{"not": "a list"}')
    cfg["sources"]["todo"].update(enabled=True, file=str(f))
    assert "todo: cannot read" in todo.collect(cfg, datetime(2026, 3, 10)).outages[0]
    cfg["sources"]["todo"]["file"] = str(tmp_path / "missing.json")
    assert "not found" in todo.collect(cfg, datetime(2026, 3, 10)).outages[0]
    cfg["sources"]["todo"]["file"] = ""
    assert "no export file" in todo.collect(cfg, datetime(2026, 3, 10)).outages[0]


def test_todo_collect_ok(tmp_path, cfg):
    f = tmp_path / "t.json"
    f.write_text(json.dumps([{"title": "Pay rent", "due": "2026-03-10", "done": False}]))
    cfg["sources"]["todo"].update(enabled=True, file=str(f))
    assert todo.collect(cfg, datetime(2026, 3, 10, 8)).signals[0].kind == "deadline"
