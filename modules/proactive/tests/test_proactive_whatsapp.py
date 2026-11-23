from datetime import datetime, timedelta

from helpers_proactive import make_whatsapp_db
from proactive.sources import whatsapp

NOW = datetime(2026, 3, 10, 12, 0)


def ts(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")


def rows():
    g = "g1@g.us"
    return [
        (g, "Project group", "Reminder: the form is due tomorrow", ts(5), 0),
        (g, "Project group", "Deadline for sign-up is tonight, urgent", ts(4), 0),
        (g, "Project group", "Please fill the form before midnight", ts(3), 0),
        (g, "Project group", "lol", ts(2), 0),
        ("g2@g.us", "Banter", "urgent joke", ts(2), 0),  # single keyword hit: not enough
        ("g2@g.us", "Banter", "Alex can you check this", ts(1), 0),
        ("111@s.whatsapp.net", "Wrong name", "Are you free on Friday?", ts(6), 0),
        ("222@s.whatsapp.net", "Other", "thanks!", ts(7), 1),
    ]


def test_analyse_flags_busy_group_mention_and_unanswered_dm():
    busy, mentions, waiting = whatsapp.analyse(rows(), ["Alex"], min_group=3)
    assert [g["name"] for g in busy.values()] == ["Project group"]
    assert busy["g1@g.us"]["n"] == 3
    assert [m[0] for m in mentions] == ["Banter"]
    assert list(waiting) == ["111@s.whatsapp.net"]  # chat 222: my message was last


def test_extra_keywords_extend_detection():
    r = [("g@g.us", "G", "bring the zebra costume", ts(1), 0)] * 3
    assert not whatsapp.analyse(r, [], min_group=3)[0]
    assert whatsapp.analyse(r, [], ["zebra"], min_group=3)[0]


def test_collect_end_to_end_with_address_book(tmp_path, cfg):
    db = make_whatsapp_db(tmp_path / "store" / "messages.db", rows(), book={"111@s.whatsapp.net": "Sam Example"})
    cfg["sources"]["whatsapp"].update(enabled=True, db=str(db))
    cfg["identity"]["names"] = ["Alex"]
    result = whatsapp.collect(cfg, NOW)
    titles = " | ".join(s.title for s in result.signals)
    assert "Sam Example wrote last" in titles  # address book beats the bridge's bad chat name
    assert "Wrong name" not in titles
    assert "Project group" in titles and "Banter mentions you" in titles
    assert not result.outages
    dm = next(s for s in result.signals if s.kind == "direct_unanswered")
    assert dm.question.startswith("Reply to Sam Example ready")


def test_missing_database_is_an_outage_not_an_empty_result(tmp_path, cfg):
    cfg["sources"]["whatsapp"].update(enabled=True, db=str(tmp_path / "nope.db"))
    result = whatsapp.collect(cfg, NOW)
    assert result.signals == []
    assert "WhatsApp: cannot read" in result.outages[0]


def test_corrupt_database_is_an_outage(tmp_path, cfg):
    bad = tmp_path / "messages.db"
    bad.write_text("this is not sqlite")
    cfg["sources"]["whatsapp"].update(enabled=True, db=str(bad))
    assert "cannot read" in whatsapp.collect(cfg, NOW).outages[0]


def test_raw_dump_is_private_and_skips_broadcasts(tmp_path, cfg, brain_home):
    db = make_whatsapp_db(tmp_path / "s" / "messages.db", rows() + [("status@broadcast", "S", "hi", ts(1), 0)])
    cfg["sources"]["whatsapp"].update(enabled=True, db=str(db), write_raw=True)
    whatsapp.collect(cfg, NOW)
    raw = brain_home / "state" / "proactive" / "raw_messages.md"
    text = raw.read_text()
    assert "## Project group (group)" in text and "status@broadcast" not in text and "hi" not in text.split("Banter")[0][-5:]
    assert oct(raw.stat().st_mode & 0o777) == "0o600"
