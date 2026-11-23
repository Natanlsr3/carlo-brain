from datetime import datetime, timedelta

from helpers_proactive import make_mail, make_whatsapp_db
from proactive.sources import followups

NOW = datetime(2026, 3, 10, 12, 0)
FMT = "%Y-%m-%d %H:%M:%S"


def at(days_ago, hour=9):
    return (NOW - timedelta(days=days_ago)).replace(hour=hour).strftime(FMT)


def chat_rows():
    a, b, c = "111@s.whatsapp.net", "222@s.whatsapp.net", "333@s.whatsapp.net"
    return [
        (a, "Can you send the report?", at(4), 1, None),                 # waiting on A
        (b, "Are you free Friday at 3pm?", at(5), 1, None),               # B will reply below
        (b, "Yes Friday works", at(3), 0, None),
        (c, "thanks!", at(4), 1, None),                                    # closing message, not a wait
    ]


NAMES = {"111@s.whatsapp.net": "Ada", "222@s.whatsapp.net": "Bo"}


def test_open_threads_keeps_questions_and_drops_closings_and_replied():
    threads = followups.threads_from_chats(chat_rows(), NAMES)
    found = followups.open_threads(threads, NOW, timedelta(days=21), set())
    assert [e["name"] for e in found.values()] == ["Ada"]
    assert found["wa:111@s.whatsapp.net"]["asked"] is True


def test_broadcast_text_is_not_a_wait():
    rows = [(f"{i}@s.whatsapp.net", "Happy new year everyone, see the invite", at(3), 1, None) for i in range(4)]
    threads = followups.threads_from_chats(rows, {})
    assert followups.open_threads(threads, NOW, timedelta(days=21), set()) == {}


def test_ignore_list_by_name_or_number():
    threads = followups.threads_from_chats(chat_rows(), NAMES)
    assert followups.open_threads(threads, NOW, timedelta(days=21), {"ada"}) == {}
    assert followups.open_threads(threads, NOW, timedelta(days=21), {"111"}) == {}


def test_old_threads_expire():
    threads = followups.threads_from_chats(chat_rows(), NAMES)
    assert followups.open_threads(threads, NOW, timedelta(days=2), set()) == {}


def test_reply_lifecycle_tracked_then_replied_then_expired(cfg):
    state = followups.update(followups.threads_from_chats(chat_rows()[:1], NAMES), {}, NOW, {"WhatsApp"}, cfg)
    assert list(state["tracked"]) == ["wa:111@s.whatsapp.net"] and not state["replies"]
    # Ada answers a day later
    later = NOW + timedelta(days=1)
    rows = chat_rows()[:1] + [("111@s.whatsapp.net", "Sent it just now", (NOW + timedelta(hours=5)).strftime(FMT), 0, None)]
    state2 = followups.update(followups.threads_from_chats(rows, NAMES), state, later, {"WhatsApp"}, cfg)
    assert [r["name"] for r in state2["replies"]] == ["Ada"] and not state2["tracked"]
    assert state["tracked"]  # input state untouched
    # replies stay 48 hours, then vanish
    gone = followups.update({}, state2, later + timedelta(hours=49), {"WhatsApp"}, cfg)
    assert gone["replies"] == []


def test_broken_channel_keeps_tracked_threads(cfg):
    state = followups.update(followups.threads_from_chats(chat_rows()[:1], NAMES), {}, NOW, {"WhatsApp"}, cfg)
    kept = followups.update({}, state, NOW + timedelta(days=1), set(), cfg)  # WhatsApp unreadable today
    assert list(kept["tracked"]) == list(state["tracked"])


def test_signals_rank_inputs(cfg):
    cfg["scoring"]["important_names"] = ["Ada"]
    state = {"tracked": {"k": {"name": "Bo", "channel": "mail", "since": at(5), "excerpt": "Invoice?", "asked": True}},
             "replies": [{"key": "x", "name": "Ada", "channel": "WhatsApp", "when": at(0), "excerpt": "done", "seen": at(0)}]}
    sigs = followups.to_signals(state, NOW, cfg)
    reply = next(s for s in sigs if s.kind == "reply")
    nudge = next(s for s in sigs if s.kind == "followup")
    assert reply.bonus == 5 and "ready" in reply.question
    assert nudge.bonus == 5 and "5 d" in nudge.title
    cfg["sources"]["followups"]["min_wait_days"] = 9
    assert not [s for s in followups.to_signals(state, NOW, cfg) if s.kind == "followup"]


def test_mail_threads_and_closing_reply():
    sent = [(1, int(datetime(2026, 3, 5, 9).timestamp()), "pat@example.org", "Pat", "Proposal for next week")]
    recv = [(2, int(datetime(2026, 3, 6, 9).timestamp()), "pat@example.org", "Re: Proposal for next week")]
    th = followups.threads_from_mail(sent, recv, {}, ["me@example.com"])
    assert th["mail:pat@example.org"]["name"] == "Pat"
    assert [m[1] for m in th["mail:pat@example.org"]["messages"]] == [True, False]
    # automated recipients and my own address are skipped
    sent2 = sent + [(3, 1, "noreply@x.example", "X", "Hi"), (4, 1, "me@example.com", "Me", "note to self")]
    assert list(followups.threads_from_mail(sent2, [], {}, ["me@example.com"])) == ["mail:pat@example.org"]


def test_mail_thanks_reply_is_a_closing_not_an_expectation():
    thread = {"channel": "mail", "name": "Pat", "messages": []}
    bodies = {7: "Thanks, noted.\n\nOn Mon, Pat wrote:\n> old"}
    assert followups.expects_answer(thread, "Re: Plan", 7, lambda r: bodies[r]) is False
    assert followups.expects_answer(thread, "Plan", 7, lambda r: bodies[r]) is True  # first mail of a thread


def test_collect_end_to_end_persists_state(tmp_path, cfg, brain_home):
    db = make_whatsapp_db(tmp_path / "s" / "messages.db",
                          [("111@s.whatsapp.net", "x", "Can you send the report?", at(4), 1)], book={"111@s.whatsapp.net": "Ada"})
    cfg["sources"]["whatsapp"].update(enabled=True, db=str(db))
    cfg["sources"]["apple_mail"]["enabled"] = False
    cfg["sources"]["followups"]["channels"] = ["whatsapp"]
    result = followups.collect(cfg, NOW)
    assert [s.kind for s in result.signals] == ["followup"] and "Ada" in result.signals[0].title
    assert (brain_home / "state" / "proactive" / "followups.json").exists()


def test_collect_reports_outage_and_does_not_write_state(tmp_path, cfg, brain_home):
    cfg["sources"]["whatsapp"].update(enabled=True, db=str(tmp_path / "missing.db"))
    cfg["sources"]["followups"]["channels"] = ["whatsapp"]
    result = followups.collect(cfg, NOW)
    assert "Follow-ups (WhatsApp)" in result.outages[0]
    assert not (brain_home / "state" / "proactive" / "followups.json").exists()


def test_collect_mail_channel(tmp_path, cfg):
    root = tmp_path / "Mail"
    root.mkdir()
    sent_epoch = int(datetime.now().timestamp()) - 4 * 86400
    make_mail(root, [(1, sent_epoch, "me@example.com", "Proposal?", 2, 1)], [(1, "pat@example.org", 0, "Pat")])
    cfg["sources"]["apple_mail"].update(enabled=True, root=str(root))
    cfg["identity"]["addresses"] = ["me@example.com"]
    cfg["sources"]["followups"]["channels"] = ["mail"]
    result = followups.collect(cfg, datetime.now())
    assert [s.kind for s in result.signals] == ["followup"] and "Pat" in result.signals[0].title
