from datetime import datetime, timedelta

from helpers_proactive import make_mail, write_emlx
from proactive.sources import mail, mail_apple

NOW = datetime.now()


def epoch(hours_ago):
    return int((NOW - timedelta(hours=hours_ago)).timestamp())


def build(tmp_path):
    root = tmp_path / "Mail"
    root.mkdir()
    msgs = [
        (1, epoch(3), "pat@example.org", "Quick question about Friday", 1, 0),
        (2, epoch(2), "no-reply@shop.example", "Your receipt", 1, 0),
        (3, epoch(2), "lee@example.org", "Already read", 1, 1),
        (4, epoch(1), "me@example.com", "Sent to Pat", 2, 1),
        (5, epoch(1), "list@example.org", "Mailing list post", 1, 0),
    ]
    rec = [(1, "me@example.com", 0, ""), (2, "me@example.com", 0, ""), (3, "me@example.com", 0, ""),
           (4, "pat@example.org", 0, "Pat"), (5, "others@example.org", 0, "")]
    make_mail(root, msgs, rec, attachments=[(1, "plan.xlsx")])
    return root


def test_find_index_picks_newest_version(tmp_path):
    for v in ("V9", "V10"):
        d = tmp_path / v / "MailData"
        d.mkdir(parents=True)
        (d / "Envelope Index").write_text("")
    assert mail_apple.find_index(tmp_path).parents[1].name == "V10"


def test_find_index_missing_raises(tmp_path):
    import pytest
    from proactive.model import SourceError

    with pytest.raises(SourceError):
        mail_apple.find_index(tmp_path)


def test_recent_and_direct_ids(tmp_path):
    root = build(tmp_path)
    index = mail_apple.find_index(root)
    rows = mail_apple.recent(index, NOW - timedelta(hours=10))
    assert [r[0] for r in rows] == [1, 2, 3, 4, 5]
    assert rows[0][4] == ["plan.xlsx"]
    assert mail_apple.direct_ids(index, NOW - timedelta(hours=10), ["ME@example.com"]) == {1, 2, 3}


def test_read_only_connection_cannot_write(tmp_path):
    import sqlite3

    import pytest

    index = mail_apple.find_index(build(tmp_path))
    con = mail_apple.connect(index)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("UPDATE messages SET read = 1")


def test_sent_and_received_skips_trash(tmp_path):
    root = build(tmp_path)
    index = mail_apple.find_index(root)
    sent, received = mail_apple.sent_and_received(index, NOW - timedelta(days=2), ["me@example.com"])
    assert [(s[0], s[2]) for s in sent] == [(4, "pat@example.org")]
    assert sent[0][3] == "Pat"
    assert [r[0] for r in received] == [1]  # Pat's mail in the inbox


def test_unread_direct_signals_skip_automated_read_and_lists(tmp_path, cfg):
    root = build(tmp_path)
    cfg["sources"]["apple_mail"].update(enabled=True, root=str(root))
    cfg["identity"]["addresses"] = ["me@example.com"]
    result = mail.collect(cfg, NOW)
    assert [s.title.split(":")[0] for s in result.signals] == ["Unread mail from pat@example.org"]
    assert not result.outages


def test_contacts_csv_names_senders(tmp_path, cfg):
    root = build(tmp_path)
    csv_path = tmp_path / "c.csv"
    csv_path.write_text("name,email\nPat Example,pat@example.org\n")
    cfg["sources"]["apple_mail"].update(enabled=True, root=str(root))
    cfg["identity"]["addresses"] = ["me@example.com"]
    cfg["contacts"]["csv"] = str(csv_path)
    assert "Pat Example" in mail.collect(cfg, NOW).signals[0].title


def test_missing_mail_data_is_an_outage(tmp_path, cfg):
    cfg["sources"]["apple_mail"].update(enabled=True, root=str(tmp_path / "empty"))
    result = mail.collect(cfg, NOW)
    assert result.signals == [] and "Mail: cannot read" in result.outages[0]


def test_body_reads_emlx_without_touching_read_flag(tmp_path):
    root = build(tmp_path)
    write_emlx(root, 1, "Can we meet Thursday at 3pm?")
    files = mail_apple.MailFiles(root)
    assert "Thursday at 3pm" in files.body(1)
    assert files.body(999) == ""
    index = mail_apple.find_index(root)
    assert mail_apple.recent(index, NOW - timedelta(hours=10))[0][5] == 0  # still unread
