"""Builders for simulated WhatsApp and Apple Mail data (no real data is ever read)."""
import sqlite3
import time
from pathlib import Path


def make_whatsapp_db(path: Path, rows, book=None):
    """rows = (chat_jid, chat_name, content, timestamp, is_from_me)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT)")
    con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, chat_jid TEXT, content TEXT, timestamp TEXT,"
                " is_from_me INTEGER, media_type TEXT)")
    for jid, name, content, ts, mine in rows:
        con.execute("INSERT OR IGNORE INTO chats VALUES (?,?)", (jid, name))
        con.execute("INSERT INTO messages (chat_jid, content, timestamp, is_from_me, media_type) VALUES (?,?,?,?,NULL)",
                    (jid, content, ts, mine))
    con.commit()
    con.close()
    if book:
        b = sqlite3.connect(path.parent / "whatsapp.db")
        b.execute("CREATE TABLE whatsmeow_contacts (their_jid TEXT, full_name TEXT, push_name TEXT)")
        b.execute("CREATE TABLE whatsmeow_lid_map (lid TEXT, pn TEXT)")
        for jid, name in book.items():
            b.execute("INSERT INTO whatsmeow_contacts VALUES (?,?,?)", (jid, name, ""))
        b.commit()
        b.close()
    return path


def make_mail(root: Path, messages, recipients=None, attachments=None):
    """Build root/V10/MailData/Envelope Index. messages = (rowid, epoch, sender, subject, mailbox, read)."""
    data = root / "V10" / "MailData"
    data.mkdir(parents=True)
    con = sqlite3.connect(data / "Envelope Index")
    con.executescript(
        "CREATE TABLE addresses (ROWID INTEGER PRIMARY KEY, address TEXT, comment TEXT);"
        "CREATE TABLE subjects (ROWID INTEGER PRIMARY KEY, subject TEXT);"
        "CREATE TABLE mailboxes (ROWID INTEGER PRIMARY KEY, url TEXT);"
        "CREATE TABLE messages (ROWID INTEGER PRIMARY KEY, sender INTEGER, subject INTEGER, date_received INTEGER,"
        " mailbox INTEGER, read INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0);"
        "CREATE TABLE recipients (ROWID INTEGER PRIMARY KEY, message INTEGER, address INTEGER, type INTEGER, position INTEGER);"
        "CREATE TABLE attachments (ROWID INTEGER PRIMARY KEY, message INTEGER, attachment_id TEXT, name TEXT);"
        "INSERT INTO mailboxes VALUES (1, 'imap://acct/INBOX'), (2, 'imap://acct/Sent%20Messages'), (3, 'imap://acct/Trash');"
    )
    addr, subj = {}, {}

    def address_id(a, comment=""):
        if a not in addr:
            addr[a] = len(addr) + 1
            con.execute("INSERT INTO addresses VALUES (?,?,?)", (addr[a], a, comment))
        elif comment:
            con.execute("UPDATE addresses SET comment=? WHERE ROWID=?", (comment, addr[a]))
        return addr[a]

    def subject_id(s):
        if s not in subj:
            subj[s] = len(subj) + 1
            con.execute("INSERT INTO subjects VALUES (?,?)", (subj[s], s))
        return subj[s]

    for rowid, epoch, sender, subject, mailbox, read in messages:
        con.execute("INSERT INTO messages (ROWID, sender, subject, date_received, mailbox, read) VALUES (?,?,?,?,?,?)",
                    (rowid, address_id(sender), subject_id(subject), epoch, mailbox, read))
    for rowid, to, kind, name in recipients or []:
        con.execute("INSERT INTO recipients (message, address, type, position) VALUES (?,?,?,0)",
                    (rowid, address_id(to, name), kind))
    for rowid, name in attachments or []:
        con.execute("INSERT INTO attachments (message, attachment_id, name) VALUES (?,?,?)", (rowid, "1", name))
    con.commit()
    con.close()
    return data / "Envelope Index"


def write_emlx(root: Path, rowid: int, body: str):
    folder = root / "V10" / "acct" / "INBOX.mbox" / "Messages"
    folder.mkdir(parents=True, exist_ok=True)
    raw = f"From: a@example.com\nSubject: s\nContent-Type: text/plain\n\n{body}\n"
    (folder / f"{rowid}.emlx").write_bytes(f"{len(raw)}\n{raw}".encode())


NOW_EPOCH = int(time.time())
