import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from proactive import briefing, scan, voice
from proactive.model import Signal, SourceResult

RUN = Path(__file__).resolve().parents[1] / "src" / "run.py"
DAY = date(2026, 3, 10)


def sig(kind, title, q="", bonus=0):
    return Signal(kind, title, "t", question=q, bonus=bonus)


def test_ranking_caps_per_kind_and_max_points(cfg):
    many = [sig("reply", f"R{i}", f"q{i}") for i in range(5)] + [sig("slot", "S"), sig("mention", "M"), sig("followup", "F")]
    chosen = briefing.select(many, cfg)
    kinds = [s.kind for s in chosen]
    assert kinds.count("reply") == 3 and len(chosen) == 5
    assert kinds[:3] == ["reply"] * 3 and "followup" in kinds


def test_bonus_breaks_order_and_unknown_kind_is_dropped(cfg):
    out = briefing.select([sig("reply", "plain"), sig("reply", "vip", bonus=5), sig("weird", "x")], cfg)
    assert [s.title for s in out] == ["vip", "plain"]


def test_weights_are_configurable(cfg):
    cfg["scoring"]["kinds"]["slot"]["weight"] = 500
    out = briefing.select([sig("reply", "r"), sig("slot", "s")], cfg)
    assert out[0].title == "s"


def test_question_comes_from_first_point_only_and_info_has_none(cfg):
    text = briefing.build([sig("reply", "Ada replied", "Answer to Ada ready: send it? (go / let me look)"), sig("slot", "1 slot")], [], DAY, cfg)
    assert text.count("Question:") == 1 and "Answer to Ada ready" in text
    info = briefing.build([sig("slot", "1 slot")], [], DAY, cfg)
    assert "Question" not in info


def test_empty_briefing_says_so(cfg):
    assert "Nothing important" in briefing.build([], [], DAY, cfg)


def test_word_budget_drops_last_points_never_the_first(cfg):
    cfg["briefing"].update(max_words=40, words_per_point=15)
    pts = [sig("reply", "word " * 14, "q?"), sig("deadline", "word " * 14), sig("followup", "word " * 14)]
    text = briefing.build(pts, [], DAY, cfg)
    assert briefing.count_words(text) <= 40
    assert text.count("\n1. ") == 1 and "\n3. " not in text


def test_hard_trim_when_first_point_alone_is_too_long(cfg):
    cfg["briefing"].update(max_words=25, words_per_point=100)
    text = briefing.build([sig("reply", "word " * 60, "q " * 10)], ["a b c " * 5], DAY, cfg)
    assert briefing.count_words(text) <= 25


def test_outage_line_is_visible_and_capped(cfg):
    text = briefing.build([], [f"source{i}: cannot read" for i in range(5)], DAY, cfg)
    assert "Sources in outage:" in text and "and 2 more" in text


def test_no_typographic_dashes_in_output(cfg):
    text = briefing.build([sig("reply", "A \u2014 B \u2013 C", "ok?")], [], DAY, cfg)
    assert "\u2014" not in text and "\u2013" not in text


def test_voice_failure_becomes_outage_until_success(tmp_path):
    (tmp_path / "voice.log").write_text("2026-03-09 07:00 OK say\n2026-03-10 07:00 FAIL no voice found\n")
    assert "Voice failed on 2026-03-10" in briefing.voice_outage(tmp_path)
    (tmp_path / "voice.log").write_text("2026-03-10 07:00 FAIL x\n2026-03-11 07:00 OK say\n")
    assert briefing.voice_outage(tmp_path) == ""
    assert briefing.voice_outage(tmp_path / "none") == ""


def test_write_briefing_boot_file_has_rule_and_is_capped(cfg, brain_home):
    cfg["briefing"]["boot_max_chars"] = 200
    text = briefing.build([sig("reply", "x " * 20, "q?")], [], DAY, cfg)
    briefing.write_briefing(text, cfg)
    boot = (brain_home / "state" / "boot.d" / "proactive.md").read_text()
    assert boot.startswith("Proactive rule:") and len(boot) <= 200
    assert (brain_home / "state" / "proactive" / "briefing.md").read_text() == text


def test_generate_without_scan_reports_it(cfg, brain_home):
    text = briefing.generate(cfg, datetime(2026, 3, 10, 8))
    assert "scan has not run yet" in text


# ---------- scan ----------

def test_scan_outputs_roundtrip_and_digest(cfg, brain_home):
    result = SourceResult([Signal("slot", "2 slots", "slots", detail=("a", "b"))], ["WhatsApp: cannot read (x)"])
    scan.write_outputs(result, datetime(2026, 3, 10, 8))
    signals, outages = scan.load_signals()
    assert signals[0].detail == ("a", "b") and outages == ["WhatsApp: cannot read (x)"]
    digest = (brain_home / "state" / "proactive" / "digest.md").read_text()
    assert digest.index("Sources in outage") < digest.index("## slot")


def test_one_crashing_source_does_not_hide_the_others(cfg, monkeypatch):
    def boom(cfg, now):
        raise RuntimeError("kaboom")

    ok = SourceResult([Signal("slot", "fine", "t")])
    monkeypatch.setattr(scan, "SOURCES", [("todo", boom), ("slots", lambda c, n: ok)])
    cfg["sources"]["todo"]["enabled"] = True
    cfg["sources"]["slots"]["enabled"] = True
    result = scan.scan(cfg, datetime.now())
    assert [s.title for s in result.signals] == ["fine"] and "todo: cannot read (kaboom)" in result.outages[0]


def test_disabled_sources_are_not_called(cfg, monkeypatch):
    called = []
    monkeypatch.setattr(scan, "SOURCES", [("todo", lambda c, n: called.append(1) or SourceResult())])
    assert scan.scan(cfg, datetime.now()).signals == [] and not called


# ---------- voice ----------

def vcfg(cfg, **kw):
    cfg["voice"].update(enabled=True, **kw)
    return cfg


def test_voice_due_rules(cfg, tmp_path):
    morning, night = datetime(2026, 3, 10, 8), datetime(2026, 3, 10, 22)
    assert not voice.due(morning, cfg, tmp_path)               # disabled by default
    vcfg(cfg)
    assert voice.due(morning, cfg, tmp_path)
    assert not voice.due(night, cfg, tmp_path)                 # outside hours
    (tmp_path / "voice_day").write_text("2026-03-10\n")
    assert not voice.due(morning, cfg, tmp_path)               # already played today
    assert voice.due(datetime(2026, 3, 11, 8), cfg, tmp_path)  # new day
    (tmp_path / "voice_off").write_text("")
    assert not voice.due(datetime(2026, 3, 11, 8), cfg, tmp_path)


def test_spoken_text_strips_markup():
    assert voice.spoken_text("# Briefing\n1. **Ada** replied\n> q") == "Briefing\nAda replied\n q".strip()


def test_speak_success_failure_and_logging(cfg, tmp_path):
    vcfg(cfg, command="fake-tts --stdin")
    (tmp_path / "briefing.md").write_text("# Briefing\n1. Hello")
    calls = []

    def ok(cmd, **kw):
        calls.append((cmd, kw["input"]))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    assert voice.speak(cfg, tmp_path, run=ok) is True
    assert calls[0][0] == ["fake-tts", "--stdin"] and "Hello" in calls[0][1]
    assert " OK fake-tts" in (tmp_path / "voice.log").read_text()

    def bad(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "no such voice")

    assert voice.speak(cfg, tmp_path, run=bad) is False
    assert "FAIL no such voice" in (tmp_path / "voice.log").read_text().splitlines()[-1]


def test_speak_without_briefing_logs_failure(cfg, tmp_path):
    vcfg(cfg, command="x")
    assert voice.speak(cfg, tmp_path) is False
    assert "FAIL briefing.md missing" in (tmp_path / "voice.log").read_text()


def test_command_for_without_any_tool_raises(cfg, monkeypatch):
    monkeypatch.setattr(voice.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="no text to speech"):
        voice.command_for(cfg, [])


def test_command_for_prefers_installed_voice(cfg, monkeypatch):
    monkeypatch.setattr(voice.shutil, "which", lambda name: "/usr/bin/say" if name == "say" else None)
    assert voice.command_for(cfg, ["Alex", "Zoe"]) == ["say", "-v", "Alex", "-f", "-"]
    cfg["voice"]["voice"] = "Zoe"
    assert voice.command_for(cfg, ["Alex", "Zoe"]) == ["say", "-v", "Zoe", "-f", "-"]


def test_play_if_due_marks_day_before_spawning(cfg, tmp_path):
    vcfg(cfg)
    spawned = []
    now = datetime(2026, 3, 10, 8)
    assert voice.play_if_due(now, cfg, tmp_path, spawn=lambda: spawned.append(1)) is True
    assert (tmp_path / "voice_day").read_text().strip() == "2026-03-10"
    assert voice.play_if_due(now, cfg, tmp_path, spawn=lambda: spawned.append(1)) is False
    assert len(spawned) == 1


# ---------- CLI (real subprocess, throwaway home) ----------

def run_cli(brain_home, *args, config=None):
    env = {k: v for k, v in os.environ.items() if "KEY" not in k}
    env["CARLO_BRAIN_HOME"] = str(brain_home)
    if config is not None:
        env["CARLO_PROACTIVE_CONFIG"] = str(config)
    return subprocess.run([sys.executable, "-I", str(RUN), *args], capture_output=True, text=True, env=env, timeout=60)


def test_cli_init_never_overwrites(brain_home):
    first = run_cli(brain_home, "init")
    target = brain_home / "config.d" / "proactive.json"
    assert first.returncode == 0 and target.exists()
    target.write_text('{"lookback_hours": 5}')
    run_cli(brain_home, "init")
    assert json.loads(target.read_text()) == {"lookback_hours": 5}


def test_cli_example_config_is_valid(brain_home):
    from proactive import config

    example = Path(__file__).resolve().parents[1] / "src" / "config.example.json"
    config.load(example)


def test_cli_run_with_everything_disabled_writes_empty_briefing(brain_home):
    out = run_cli(brain_home, "run")
    assert out.returncode == 0
    assert "Nothing important" in (brain_home / "state" / "boot.d" / "proactive.md").read_text()


def test_cli_boot_never_fails_even_with_broken_config(brain_home, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{broken")
    out = run_cli(brain_home, "boot", config=bad)
    assert out.returncode == 0 and "proactive boot" in out.stderr
    assert run_cli(brain_home, "scan", config=bad).returncode == 1


def test_cli_boot_with_nothing_enabled_does_nothing(brain_home):
    assert run_cli(brain_home, "boot").returncode == 0
    assert not (brain_home / "state" / "proactive").exists()


def test_cli_unknown_command_prints_usage(brain_home):
    out = run_cli(brain_home, "nope")
    assert out.returncode == 2 and "run.py init" in out.stdout
