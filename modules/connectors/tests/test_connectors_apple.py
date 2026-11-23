import gzip
import json
import sqlite3
import time

import pytest

import _common
import calendar_events
import contacts
import messages
import notes
import reminders


# ---------- _common ----------

def test_fold_and_apple_date():
    assert _common.fold("Élodie  Ça") == "elodie  ca"
    assert _common.apple_date(0) == "?"
    secs = int(time.time()) - _common.APPLE_EPOCH
    assert _common.apple_date(secs) == _common.apple_date(secs * 1_000_000_000)  # seconds and nanoseconds agree


def test_phone_normalisation_is_country_agnostic_unless_configured(monkeypatch):
    assert _common.normalise_phone("+1 (415) 555-0100") == "14155550100"
    assert _common.normalise_phone("0044 20 7946 0000") == "442079460000"
    assert _common.normalise_phone("07700 900123") == "07700900123"  # no country code configured
    monkeypatch.setenv("CARLO_DEFAULT_COUNTRY_CODE", "44")
    assert _common.normalise_phone("07700 900123") == "447700900123"
    assert _common.same_number("+44 7700 900123", "07700 900123")
    assert not _common.same_number("+44 7700 900123", "+44 7700 900999")
    assert not _common.same_number("", "123")


def test_open_ro_refuses_writes_and_missing_file(tmp_path):
    db = tmp_path / "x.db"
    sqlite3.connect(db).executescript("create table t(a); insert into t values (1);")
    with _common.open_ro(db) as conn:
        assert conn.execute("select a from t").fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("insert into t values (2)")
    with pytest.raises(FileNotFoundError):
        with _common.open_ro(tmp_path / "none.db"):
            pass


def test_open_ro_not_a_database_is_access_error(tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_text("garbage garbage garbage")
    with pytest.raises(_common.AccessError):
        with _common.open_ro(bad):
            pass


# ---------- contacts ----------

def make_addressbook(root, name="AddressBook-v22.abcddb", people=()):
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / name)
    con.executescript(
        "create table ZABCDRECORD (Z_PK integer primary key, ZFIRSTNAME, ZLASTNAME, ZORGANIZATION);"
        "create table ZABCDPHONENUMBER (ZOWNER, ZFULLNUMBER);"
        "create table ZABCDEMAILADDRESS (ZOWNER, ZADDRESS);"
    )
    for pk, (first, last, org, phones, mails) in enumerate(people, 1):
        con.execute("insert into ZABCDRECORD values (?,?,?,?)", (pk, first, last, org))
        for p in phones:
            con.execute("insert into ZABCDPHONENUMBER values (?,?)", (pk, p))
        for m in mails:
            con.execute("insert into ZABCDEMAILADDRESS values (?,?)", (pk, m))
    con.commit()
    con.close()
    return str(root / name)


def test_contacts_merge_across_sources_and_search(tmp_path):
    a = make_addressbook(tmp_path / "a", people=[("Zoë", "Example", "", ["+1 415 555 0100"], ["zoe@example.org"])])
    b = make_addressbook(tmp_path / "b", people=[("Zoë", "Example", "", ["(415) 555-0100", "+1 415 555 0199"], ["ZOE@example.org"]),
                                                  (None, None, "Acme Corp", [], [])])
    book = contacts.load_contacts([a, b])
    zoe = contacts.by_name("zoe example", book)[0]
    assert len(zoe.phones) == 2 and zoe.emails == ["zoe@example.org"]  # duplicates merged
    assert [c.display for c in contacts.by_name("acme", book)] == ["Acme Corp"]
    assert contacts.by_name("", book) == []
    assert contacts.by_phone("415-555-0199", book)[0].display == "Zoë Example"
    assert "phone: " in contacts.format_contact(zoe) and "mail: zoe@example.org" in contacts.format_contact(zoe)


def test_find_databases_lists_sources_and_root(tmp_path):
    make_addressbook(tmp_path / "Sources" / "S1")
    make_addressbook(tmp_path)
    assert len(contacts.find_databases(str(tmp_path))) == 2


# ---------- messages ----------

def typedstream(text: str) -> bytes:
    raw = text.encode()
    size = bytes([len(raw)]) if len(raw) < 0x80 else b"\x81" + len(raw).to_bytes(2, "little")
    return b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92\x84\x84\x84\x08NSString\x01\x94\x84\x01+" + size + raw


def test_extract_text_from_column_and_attributed_body():
    assert messages.extract_text("plain￼", None) == "plain"
    assert messages.extract_text(None, typedstream("Hello from the blob")) == "Hello from the blob"
    long = "x" * 200
    assert messages.extract_text(None, typedstream(long)) == long  # 0x81 two byte length
    assert messages.extract_text(None, b"nothing here") == ""
    assert messages.extract_text(None, None) == ""


def make_chatdb(path):
    con = sqlite3.connect(path)
    con.executescript(
        "create table handle (ROWID integer primary key, id text);"
        "create table message (ROWID integer primary key, date, is_from_me, handle_id, text, attributedBody);"
    )
    now_ns = (time.time() - _common.APPLE_EPOCH) * 1e9
    con.execute("insert into handle values (1, '+14155550100'), (2, 'zoe@example.org'), (3, '+14155550123')")
    rows = [
        (now_ns - 3e9, 0, 1, "Dinner on Friday?", None),
        (now_ns - 2e9, 1, 1, "Sure, 8pm", None),
        (now_ns - 1e9, 0, 2, None, typedstream("Résumé attached")),
        (now_ns - 86400e9 * 40, 0, 3, "ancient message about dinner", None),
    ]
    for i, (d, me, h, t, b) in enumerate(rows, 1):
        con.execute("insert into message values (?,?,?,?,?,?)", (i, d, me, h, t, b))
    con.commit()
    con.close()


def test_messages_search_thread_and_names(tmp_path):
    make_chatdb(tmp_path / "chat.db")
    book = [contacts.Contact("Zoe", "Example", "", ["+1 415 555 0100"], ["zoe@example.org"])]
    table = messages.name_table(book)
    with _common.open_ro(tmp_path / "chat.db") as conn:
        hits = messages.search(conn, "dinner", None, 10, table)
        assert len(hits) == 2 and "Zoe Example | Dinner on Friday?" in hits[0]
        assert len(messages.search(conn, "dinner", 7, 10, table)) == 1          # --days filter
        assert messages.search(conn, "resume", None, 10, table)[0].endswith("Résumé attached")  # accent insensitive
        conv = messages.thread(conn, "zoe", 10, book, table)
        assert [l.split(" | ")[1] for l in conv] == ["Zoe Example", "me", "Zoe Example"]  # phone + mail handles, oldest first
        assert messages.thread(conn, "+1 415 555 0123", 5, book, table)[0].endswith("ancient message about dinner")
        assert messages.thread(conn, "nobody", 5, book, table) == []
    assert messages.handle_name("+14155550100", table) == "Zoe Example"
    assert messages.handle_name("+19995550000", table) == "+19995550000"


# ---------- notes ----------

def pb(number: int, payload: bytes) -> bytes:
    def varint(n):
        out = b""
        while True:
            b = n & 0x7F
            n >>= 7
            out += bytes([b | (0x80 if n else 0)])
            if not n:
                return out
    return varint((number << 3) | 2) + varint(len(payload)) + payload


def zdata(text: str) -> bytes:
    return gzip.compress(pb(2, pb(3, pb(2, text.encode()))))


def make_notesdb(path):
    con = sqlite3.connect(path)
    con.executescript(
        "create table ZICNOTEDATA (Z_PK integer primary key, ZDATA blob);"
        "create table ZICCLOUDSYNCINGOBJECT (Z_PK integer primary key, ZTITLE1, ZSNIPPET, ZMODIFICATIONDATE1, ZISPASSWORDPROTECTED,"
        " ZNOTEDATA, ZFOLDER, ZMARKEDFORDELETION, ZTITLE2, ZFOLDERTYPE);"
    )
    con.execute("insert into ZICCLOUDSYNCINGOBJECT (Z_PK, ZTITLE2, ZFOLDERTYPE) values (100, 'Notes', 0), (101, 'Recently Deleted', 1)")
    data = [
        (1, "Shopping list", "milk eggs", 700000000, 0, 100, 0, "milk\neggs\nfresh basil"),
        (2, "Secret", "hidden", 700000100, 1, 100, 0, "never shown"),
        (3, "Trashed", "gone", 700000200, 0, 101, 0, "deleted content"),
        (4, "Marked", "gone", 700000300, 0, 100, 1, "marked for deletion"),
    ]
    for pk, title, snip, mod, prot, folder, marked, body in data:
        con.execute("insert into ZICNOTEDATA values (?,?)", (pk, zdata(body)))
        con.execute("insert into ZICCLOUDSYNCINGOBJECT (Z_PK, ZTITLE1, ZSNIPPET, ZMODIFICATIONDATE1, ZISPASSWORDPROTECTED,"
                    " ZNOTEDATA, ZFOLDER, ZMARKEDFORDELETION) values (?,?,?,?,?,?,?,?)", (pk, title, snip, mod, prot, pk, folder, marked))
    con.commit()
    con.close()


def test_notes_list_search_read_skip_deleted_and_protected(tmp_path):
    make_notesdb(tmp_path / "n.sqlite")
    with _common.open_ro(tmp_path / "n.sqlite") as conn:
        all_notes = notes.list_notes(conn)
    assert [n[0] for n in all_notes] == ["Secret", "Shopping list"]
    assert notes.search(all_notes, "basil", 5)[0].endswith("fresh basil")
    assert notes.search(all_notes, "never shown", 5) == []                     # protected body is not searched
    assert "(protected)" in notes.search(all_notes, "secret", 5)[0]            # but its title is
    assert "fresh basil" in notes.read(all_notes, "shopping")
    assert "not readable" in notes.read(all_notes, "secret")
    assert notes.read(all_notes, "trashed") == "No note found."
    assert notes.note_body(b"not gzip") == "" and notes.note_body(None) == ""


# ---------- reminders ----------

SEP = reminders.SEP


def test_reminders_parse_export_and_quit_when_not_running():
    calls = []

    def fake(script):
        calls.append(script)
        if "is running" in script:
            return "false\n"
        if "quit" in script:
            return ""
        return f"Buy milk{SEP}2 litres{SEP}2026-03-10T09:00:00{SEP}Home\nCall Sam{SEP}{SEP}{SEP}Work\n{SEP}{SEP}{SEP}\n"

    items = reminders.fetch("Home", fake)
    assert [i["title"] for i in items] == ["Buy milk", "Call Sam"]
    assert items[0]["due"] == "2026-03-10T09:00:00" and items[1]["due"] == ""
    assert any('list "Home"' in c for c in calls) and "quit" in calls[-1]
    export = reminders.to_todo_export(items)
    assert export[0] == {"title": "Buy milk", "due": "2026-03-10T09:00:00", "done": False, "note": "2 litres"}


def test_reminders_does_not_quit_an_app_that_was_open():
    calls = []

    def fake(script):
        calls.append(script)
        return "true\n" if "is running" in script else ""

    reminders.fetch(None, fake)
    assert not any("quit" in c for c in calls) and "every list" in calls[1]


def test_reminders_script_escapes_list_name():
    assert '\\"' in reminders.build_script('My "list"')


def test_reminders_cli_export_and_error(tmp_path, capsys):
    def fake(script):
        return "true\n" if "is running" in script else f"A{SEP}{SEP}2026-03-10T09:00:00{SEP}L\n"

    out = tmp_path / "todo.json"
    assert reminders.main(["export", "--out", str(out)], fake) == 0
    assert json.loads(out.read_text())[0]["title"] == "A"

    def broken(script):
        raise RuntimeError("not authorised")

    assert reminders.main(["count"], broken) == 2
    assert "not authorised" in capsys.readouterr().err


# ---------- calendar ----------

def test_calendar_events_skip_cancelled_and_filter_calendar(tmp_path):
    db = tmp_path / "Calendar.sqlitedb"
    con = sqlite3.connect(db)
    con.executescript(
        "create table Calendar (ROWID integer primary key, title);"
        "create table CalendarItem (ROWID integer primary key, summary, all_day, status);"
        "create table OccurrenceCache (event_id, calendar_id, occurrence_start_date, occurrence_end_date);"
    )
    con.execute("insert into Calendar values (1, 'Work'), (2, 'Home')")
    base = time.time() - _common.APPLE_EPOCH
    con.executemany("insert into CalendarItem values (?,?,?,?)", [(1, "Standup", 0, 1), (2, "Cancelled call", 0, 3),
                                                                  (3, "Holiday", 1, 0), (4, "Far future", 0, 1), (5, "Gym", 0, 0)])
    con.executemany("insert into OccurrenceCache values (?,?,?,?)", [
        (1, 1, base + 3600, base + 7200), (2, 1, base + 3600, base + 7200), (3, 2, base + 86400, base + 172800),
        (4, 1, base + 86400 * 90, base + 86400 * 90 + 60), (5, 2, base + 5000, base + 6000)])
    con.commit()
    con.close()
    now = time.time()
    with _common.open_ro(db) as conn:
        events = calendar_events.upcoming(conn, now, now + 7 * 86400)
        assert [e["title"] for e in events] == ["Standup", "Gym", "Holiday"]
        assert [e["title"] for e in calendar_events.upcoming(conn, now, now + 7 * 86400, "work")] == ["Standup"]
    lines = [calendar_events.format_event(e) for e in events]
    assert lines[0].endswith("| Standup [Work]") and "(all day)" in lines[2]
