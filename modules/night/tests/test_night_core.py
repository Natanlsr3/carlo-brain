import json
from datetime import datetime

import pytest

from helpers_night import FakeRun, done, make_task
from night import report, config, power, runner, statusline, tasks

NIGHT = datetime(2026, 3, 10, 23, 0)
EARLY = datetime(2026, 3, 11, 2, 0)
MORNING = datetime(2026, 3, 11, 8, 40)


# ---------- STATUS line ----------

@pytest.mark.parametrize("text,expected", [
    ("blah\nSTATUS: done - everything written", ("done", "everything written")),
    ("STATUS: partial - only step A\nmore chatter\n**STATUS: failed - cannot reach the site**", ("failed", "cannot reach the site")),
    ("`status: DONE`", ("done", "no reason given")),
    ("no status here", ("absent", "no STATUS line in the agent's output")),
    ("the status of this is fine", ("absent", "no STATUS line in the agent's output")),
])
def test_status_line_last_one_wins(text, expected):
    assert statusline.read(text) == expected


def test_limit_detection():
    assert statusline.hit_limit("You have hit your limit") and statusline.hit_limit("Usage limit reached")
    assert not statusline.hit_limit("all good")


# ---------- time and power ----------

def test_window_wraps_past_midnight():
    assert power.in_window(datetime(2026, 3, 10, 23, 0), "20:30", "06:00")
    assert power.in_window(datetime(2026, 3, 11, 5, 59), "20:30", "06:00")
    assert not power.in_window(datetime(2026, 3, 11, 6, 0), "20:30", "06:00")
    assert not power.in_window(datetime(2026, 3, 10, 14, 0), "20:30", "06:00")
    assert power.in_window(datetime(2026, 3, 10, 2, 0), "01:00", "05:00") and not power.in_window(datetime(2026, 3, 10, 6, 0), "01:00", "05:00")


def test_evening_of_after_midnight_belongs_to_yesterday():
    assert power.evening_of(datetime(2026, 3, 11, 1, 30), "06:00") == "2026-03-10"
    assert power.evening_of(datetime(2026, 3, 10, 22, 0), "06:00") == "2026-03-10"


def test_mains_detection(tmp_path):
    import subprocess

    def pmset(out):
        return lambda *a, **k: subprocess.CompletedProcess(a, 0, out, "")

    assert power.on_mains("darwin", pmset("Now drawing from 'AC Power'")) is True
    assert power.on_mains("darwin", pmset("Now drawing from 'Battery Power'")) is False
    assert power.on_mains("darwin", pmset("")) is None
    sysfs = tmp_path / "ps"
    (sysfs / "AC").mkdir(parents=True)
    (sysfs / "AC" / "online").write_text("0\n")
    assert power.on_mains("linux", sysfs=sysfs) is False
    (sysfs / "AC" / "online").write_text("1\n")
    assert power.on_mains("linux", sysfs=sysfs) is True
    assert power.on_mains("linux", sysfs=tmp_path / "none") is None


# ---------- config ----------

def test_config_defaults_override_and_validation(tmp_path):
    brain = tmp_path / "b"
    (brain / "config.d").mkdir(parents=True)
    assert config.load(brain).values["window"] == {"start": "20:30", "end": "06:00"}
    (brain / "config.d" / "night.json").write_text(json.dumps({"window": {"start": "22:00"}, "marathon": {"enabled": True}}))
    values = config.load(brain).values
    assert values["window"] == {"start": "22:00", "end": "06:00"} and values["marathon"]["enabled"] and values["marathon"]["max_passes"] == 40
    for bad in ({"window": {"start": "25:00"}}, {"step_max_s": 5}, {"extra_denied_tools": "x"}, {"last_step_before": "soon"}, [1]):
        (brain / "config.d" / "night.json").write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            config.load(brain)
    (brain / "config.d" / "night.json").write_text("{broken")
    with pytest.raises(ValueError):
        config.load(brain)


def test_denied_list_always_blocks_sends_and_merges_extras(cfg):
    denied = cfg.denied(["Bash(make:*)"])
    for tool in ("mcp__whatsapp__send_message", "mcp__claude_ai_Gmail__send_message", "Bash(git push:*)", "Bash(make:*)"):
        assert tool in denied
    assert len(denied) == len(set(denied))


# ---------- tasks ----------

def test_task_check_ok_and_each_problem(cfg, tmp_path):
    ok = make_task(cfg, "01_ok")
    assert tasks.check(ok, cfg) == []
    assert tasks.load_task(ok, cfg).workdir == ok / "work"
    cases = {
        "02_bash": dict(tools="Read,Bash"),
        "03_steps": dict(steps=0),
        "04_dirs": dict(extra={"add_dirs": [str(tmp_path / "missing")]}),
    }
    for name, kw in cases.items():
        problems = tasks.check(make_task(cfg, name, **kw), cfg)
        assert problems, name
    empty_prompt = make_task(cfg, "05_empty", prompt="  ")
    assert "prompt.md missing or empty" in tasks.check(empty_prompt, cfg)
    no_json = cfg.queue / "06_nojson"
    no_json.mkdir()
    assert tasks.check(no_json, cfg) == ["task.json missing"]
    assert tasks.check(cfg.queue / "bad name!", cfg)[0].startswith("folder name")


def test_missing_claude_is_reported(cfg):
    broken = config.Settings(brain=cfg.brain, values={**cfg.values, "claude_bin": "definitely-not-installed-xyz"})
    assert any("command not found" in p for p in tasks.check(make_task(cfg, "01_x"), broken))


def test_protected_folders_are_refused_on_macos_only(tmp_path):
    home = tmp_path / "h"
    (home / "Desktop" / "proj").mkdir(parents=True)
    assert tasks.protected_folder(home / "Desktop" / "proj", home, "darwin") == "Desktop"
    assert tasks.protected_folder(home / "Desktop" / "proj", home, "linux") is None
    assert tasks.protected_folder(home / "work", home, "darwin") is None


def test_create_validates_name_and_refuses_duplicates(cfg):
    path = tasks.create(cfg, "01_new", "do things", steps=3, model="sonnet")
    assert json.loads((path / "task.json").read_text())["steps"] == 3
    with pytest.raises(ValueError):
        tasks.create(cfg, "01_new", "again")
    with pytest.raises(ValueError):
        tasks.create(cfg, "../escape", "x")


# ---------- runner ----------

def test_command_and_environment(cfg, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "leak")
    monkeypatch.setenv("MY_SECRET", "leak")
    monkeypatch.setenv("KEEP_ME", "yes")
    keyfile = cfg.brain / "keys" / "claude_oauth_token"
    keyfile.parent.mkdir(parents=True)
    keyfile.write_text("sk-ant-fake")
    keyfile.chmod(0o600)
    env = runner.login_env(cfg)
    assert "OPENAI_API_KEY" not in env and "MY_SECRET" not in env and env["KEEP_ME"] == "yes"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-fake"
    keyfile.chmod(0o644)
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in runner.login_env(cfg)   # a world-readable token file is ignored
    cmd = runner.build_command(cfg, "opus", "Read,Write", cfg.denied(), ["/data"])
    assert cmd[:4] == ["sh", "-p", "--model", "opus"] and cmd[cmd.index("--add-dir") + 1] == "/data"
    assert "mcp__whatsapp__send_message" in cmd[cmd.index("--disallowedTools") + 1]


def test_steps_run_in_order_and_task_moves_to_done(cfg):
    path = make_task(cfg, steps=2)
    fake = FakeRun([done(), done()])
    results = runner.run_queue(cfg, lambda: NIGHT, fake)
    assert [(r.name, r.state, r.steps_done) for r in results] == [("01_demo", "finished", 2)]
    assert not path.exists() and (cfg.done / "01_demo_2026-03-10").exists()
    first = fake.calls[0][1]["input"]
    assert "Step 1 of 2 on 2026-03-10" in first and "Standing rules" in first and "STATUS: done|partial|failed" in first
    assert "Step 2 of 2" in fake.calls[1][1]["input"]
    assert fake.calls[0][1]["cwd"] == path / "work"


def test_exit_zero_without_status_line_is_not_a_finished_step(cfg):
    path = make_task(cfg, steps=2)
    fake = FakeRun([(0, "I did everything, trust me")])
    result = runner.run_task(cfg, tasks.load_task(path, cfg), lambda: NIGHT, fake)
    assert result.state == "partial" and result.steps_done == 0 and "absent" in result.reason
    assert not (path / "steps_done").exists() and len(fake.calls) == 1   # stops at the first unfinished step


def test_partial_status_and_nonzero_exit_stop_the_task(cfg):
    path = make_task(cfg, steps=3)
    fake = FakeRun([done(), (0, "STATUS: partial - source blocked")])
    result = runner.run_task(cfg, tasks.load_task(path, cfg), lambda: NIGHT, fake)
    assert result.steps_done == 1 and "partial: source blocked" in result.reason and (path / "steps_done").read_text() == "1"
    crash = runner.run_task(cfg, tasks.load_task(path, cfg), lambda: NIGHT, FakeRun([(1, "STATUS: done - but exit 1")]))
    assert crash.state == "partial" and "exit code 1" in crash.reason and crash.steps_done == 1


def test_resume_from_recorded_progress(cfg):
    path = make_task(cfg, steps=3)
    (path / "steps_done").write_text("2")
    fake = FakeRun([done()])
    result = runner.run_task(cfg, tasks.load_task(path, cfg), lambda: NIGHT, fake)
    assert result.state == "finished" and "Step 3 of 3" in fake.calls[0][1]["input"] and len(fake.calls) == 1


def test_no_new_step_after_the_morning_limit(cfg):
    path = make_task(cfg, steps=2)
    fake = FakeRun([])
    result = runner.run_task(cfg, tasks.load_task(path, cfg), lambda: MORNING, fake)
    assert result.state == "partial" and "no new step after 08:30" in result.reason and not fake.calls
    assert not runner.too_late(EARLY, cfg) and not runner.too_late(datetime(2026, 3, 10, 21, 0), cfg)


def test_usage_limit_stops_without_calling_it_a_failure(cfg):
    path = make_task(cfg, steps=2)
    result = runner.run_task(cfg, tasks.load_task(path, cfg), lambda: NIGHT, FakeRun([(1, "You have hit your limit")]))
    assert result.state == "partial" and "usage limit" in result.reason


def test_timeout_and_missing_binary_are_reported(cfg):
    import subprocess

    path = make_task(cfg, steps=1)

    def timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    result = runner.run_task(cfg, tasks.load_task(path, cfg), lambda: NIGHT, timeout)
    assert result.state == "partial" and "exit code 124" in result.reason

    def missing(cmd, **kw):
        raise FileNotFoundError("x")

    assert "exit code 127" in runner.run_task(cfg, tasks.load_task(path, cfg), lambda: NIGHT, missing).reason


def test_blocked_task_is_reported_and_others_still_run(cfg):
    make_task(cfg, "01_bad", tools="Bash")
    make_task(cfg, "02_good", steps=1)
    broken = cfg.queue / "03_broken"
    broken.mkdir()
    (broken / "task.json").write_text("{nope")
    results = {r.name: r for r in runner.run_queue(cfg, lambda: NIGHT, FakeRun([done()]))}
    assert results["01_bad"].state == "blocked" and "bare `Bash`" in results["01_bad"].reason
    assert results["02_good"].state == "finished" and results["03_broken"].state == "blocked"


def test_step_output_is_logged_without_losing_earlier_steps(cfg):
    make_task(cfg, steps=2)
    runner.run_queue(cfg, lambda: NIGHT, FakeRun([done("one"), done("two")]))
    log = (cfg.logs / "01_demo.log").read_text()
    assert "step 1 exit 0" in log and "step 2 exit 0" in log and "done - two" in log


# ---------- report ----------

def test_report_written_and_shown_once(cfg):
    results = [runner.TaskResult("01_a", "A", 2, 2, "finished", "2/2 steps done"), runner.TaskResult("02_b", "B", 1, 3, "partial", "step 2 not finished")]
    report.write(cfg, results, NIGHT, ["- **marathon**: 3 pass(es)"])
    text = (cfg.state / "REPORT.md").read_text()
    assert "**01_a**: done (2/2 steps)" in text and "**02_b**: TO FINISH (1/3 steps)" in text and "marathon" in text
    report.boot_note(cfg)
    note = cfg.brain / "state" / "boot.d" / "night.md"
    assert note.read_text().startswith("<!-- once -->\n") and "02_b" in note.read_text() and not (cfg.state / "report_unread").exists()
    note.write_text("old note not yet shown")  # nothing new: an unshown note is left for the injector, nothing is rewritten
    report.boot_note(cfg)
    assert note.read_text() == "old note not yet shown"


def test_boot_note_without_report_does_nothing(cfg):
    report.boot_note(cfg)
    assert not (cfg.brain / "state" / "boot.d" / "night.md").exists()
