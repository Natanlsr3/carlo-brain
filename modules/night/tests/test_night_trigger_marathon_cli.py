import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from helpers_night import FakeRun, done, make_task
from night import config, marathon, trigger

MAIN = Path(__file__).resolve().parents[1] / "src" / "main.py"
NIGHT = datetime(2026, 3, 10, 23, 0)


def clock(*times):
    """A clock that returns the given times in order, then keeps the last one."""
    items = list(times)
    return lambda: items.pop(0) if len(items) > 1 else items[0]


# ---------- trigger conditions ----------

def test_should_start_matrix(cfg):
    assert trigger.should_start(cfg, NIGHT, True) == (False, "nothing queued")
    make_task(cfg)
    assert trigger.should_start(cfg, NIGHT, True) == (True, "conditions met")
    assert trigger.should_start(cfg, datetime(2026, 3, 10, 14, 0), True) == (False, "outside the night window")
    assert trigger.should_start(cfg, NIGHT, False) == (False, "waiting: on battery")
    assert trigger.should_start(cfg, NIGHT, None)[0] is True                       # unknown power state: do not block
    assert trigger.should_start(cfg, datetime(2026, 3, 10, 14, 0), False, force=True) == (True, "forced")
    off = config.Settings(brain=cfg.brain, values={**cfg.values, "require_ac": False})
    assert trigger.should_start(off, NIGHT, False)[0] is True


def test_trigger_runs_once_per_evening_and_writes_report(cfg):
    make_task(cfg, steps=1)
    fake = FakeRun([done()])
    lines = trigger.trigger(cfg, lambda: NIGHT, lambda: True, run=fake)
    assert lines and lines[0].startswith("- **01_demo**: done")
    assert (cfg.state / "launched_2026-03-10").exists() and (cfg.state / "report_unread").exists()
    make_task(cfg, "02_later", steps=1)
    assert trigger.trigger(cfg, lambda: NIGHT + timedelta(hours=1), lambda: True, run=FakeRun([])) == []   # same evening: no second run
    after_midnight = datetime(2026, 3, 11, 1, 0)
    assert trigger.trigger(cfg, lambda: after_midnight, lambda: True, run=FakeRun([])) == []               # still the same night
    next_evening = trigger.trigger(cfg, lambda: NIGHT + timedelta(days=1), lambda: True, run=FakeRun([done()]))
    assert next_evening and "02_later" in next_evening[0]


def test_battery_defers_and_is_logged_not_launched(cfg):
    make_task(cfg)
    fake = FakeRun([])
    assert trigger.trigger(cfg, lambda: NIGHT, lambda: False, run=fake) == [] and not fake.calls
    assert "waiting: on battery" in (cfg.logs / "trigger.log").read_text()
    assert not (cfg.state / "launched_2026-03-10").exists()          # it will retry on the next tick


def test_marker_is_written_before_the_run_so_a_crash_cannot_loop(cfg):
    make_task(cfg)

    def crash(cmd, **kw):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        trigger.trigger(cfg, lambda: NIGHT, lambda: True, run=crash)
    assert (cfg.state / "launched_2026-03-10").exists()
    assert trigger.trigger(cfg, lambda: NIGHT, lambda: True, run=FakeRun([done()])) == []


def test_force_ignores_window_and_marker(cfg):
    make_task(cfg, steps=1)
    assert trigger.trigger(cfg, lambda: datetime(2026, 3, 10, 14, 0), lambda: False, force=True, run=FakeRun([done()]))


def test_a_second_trigger_while_one_runs_does_nothing(cfg):
    import fcntl

    make_task(cfg)
    cfg.state.mkdir(parents=True, exist_ok=True)
    held = open(cfg.state / "trigger.lock", "w")
    fcntl.flock(held, fcntl.LOCK_EX)
    try:
        assert trigger.trigger(cfg, lambda: NIGHT, lambda: True, run=FakeRun([])) == []
    finally:
        held.close()


# ---------- marathon ----------

def marathon_cfg(cfg, **over):
    values = {**cfg.values, "marathon": {**cfg.values["marathon"], "enabled": True, **over}}
    return config.Settings(brain=cfg.brain, values=values)


def write_backlog(cfg, text):
    marathon.ensure_files(cfg)
    (cfg.marathon / "BACKLOG.md").write_text(text)


def test_open_items_counts_unchecked_and_in_progress():
    assert marathon.open_items("- [x] done\n- [ ] todo\n- [x] [in progress] odd\n- task [in progress]\n- [dropped: no]") == 2


def test_marathon_stops_when_backlog_is_empty_and_seeds_files(cfg):
    mcfg = marathon_cfg(cfg)
    write_backlog(mcfg, "- [x] all done\n")
    result = marathon.run_marathon(mcfg, lambda: NIGHT, FakeRun([]), lambda s: None)
    assert (result.passes, result.reason) == (0, "backlog empty")
    assert (mcfg.marathon / "prompt.md").exists() and (mcfg.marathon / "JOURNAL.md").exists()


def test_marathon_runs_until_the_backlog_is_ticked(cfg):
    mcfg = marathon_cfg(cfg)
    write_backlog(mcfg, "- [ ] one\n- [ ] two\n")
    sleeps = []

    def run(cmd, **kw):
        calls.append(kw["input"])
        if len(calls) == 2:
            (mcfg.marathon / "BACKLOG.md").write_text("- [x] one\n- [x] two\n")
        return subprocess.CompletedProcess(cmd, 0, "STATUS: done - ticked", "")

    calls = []
    result = marathon.run_marathon(mcfg, lambda: NIGHT, run, sleeps.append)
    assert (result.passes, result.ok, result.failed, result.reason) == (2, 2, 0, "backlog empty")
    assert "pass 1" in calls[0] and "Standing rules" in calls[0] and sleeps == [20, 20]


def test_marathon_deadline_max_passes_and_failure_streak(cfg):
    write = lambda c: write_backlog(c, "- [ ] forever\n")
    mcfg = marathon_cfg(cfg)
    write(mcfg)
    morning = datetime(2026, 3, 11, 9, 20)
    assert marathon.run_marathon(mcfg, lambda: morning, FakeRun([]), lambda s: None).reason == "deadline 09:15 reached"
    assert marathon.deadline_passed(datetime(2026, 3, 10, 21, 0), mcfg) is False       # an evening start is never cut
    capped = marathon_cfg(cfg, max_passes=2)
    assert marathon.run_marathon(capped, lambda: NIGHT, FakeRun([done(), done()]), lambda s: None).reason == "maximum number of passes reached"
    failing = marathon.run_marathon(mcfg, lambda: NIGHT, FakeRun([(0, "no status")] * 9), lambda s: None)
    assert (failing.failed, failing.reason) == (5, "5 failed passes in a row")


def test_marathon_usage_limit_pauses_instead_of_counting_a_pass(cfg):
    mcfg = marathon_cfg(cfg, max_passes=1)
    write_backlog(mcfg, "- [ ] x\n")
    sleeps = []
    result = marathon.run_marathon(mcfg, lambda: NIGHT, FakeRun([(1, "you hit your limit"), done()]), sleeps.append)
    assert sleeps[0] == 600 and result.passes == 1 and result.ok == 1


def test_trigger_with_marathon_only_and_extra_report_line(cfg):
    mcfg = marathon_cfg(cfg, max_passes=1)
    write_backlog(mcfg, "- [ ] x\n")
    assert trigger.has_work(mcfg)
    lines = trigger.trigger(mcfg, lambda: NIGHT, lambda: True, run=FakeRun([done()]), sleep=lambda s: None)
    assert "marathon" in lines[-1] and "1 pass(es)" in lines[-1]
    assert "marathon" in (mcfg.state / "REPORT.md").read_text()
    assert not trigger.has_work(cfg)          # marathon disabled: an open backlog alone does not start a night


# ---------- CLI ----------

def run_main(*args, brain, claude=None):
    env = {k: v for k, v in os.environ.items() if "KEY" not in k}
    env["CARLO_BRAIN_HOME"] = str(brain)
    return subprocess.run([sys.executable, "-I", str(MAIN), *args], capture_output=True, text=True, env=env, timeout=60)


def set_config(brain, **values):
    (brain / "config.d").mkdir(parents=True, exist_ok=True)
    (brain / "config.d" / "night.json").write_text(json.dumps(values))


def test_cli_add_list_check(cfg, tmp_path):
    set_config(cfg.brain, claude_bin="sh")
    prompt = tmp_path / "p.md"
    prompt.write_text("do step {STEP}")
    out = run_main("add", "01_cli", "--prompt-file", str(prompt), "--steps", "2", brain=cfg.brain)
    assert out.returncode == 0 and "pre-flight check passed" in out.stdout
    assert "01_cli: 0/2 steps" in run_main("list", brain=cfg.brain).stdout
    assert run_main("check", brain=cfg.brain).stdout.strip() == "01_cli: ok"
    assert run_main("add", "01_cli", "--prompt-file", str(prompt), brain=cfg.brain).returncode == 1          # duplicate
    assert run_main("add", brain=cfg.brain).returncode == 2


def test_cli_check_reports_problems_and_boot_never_fails(cfg):
    set_config(cfg.brain, claude_bin="definitely-not-installed-xyz")
    make_task(cfg, "01_x")
    out = run_main("check", brain=cfg.brain)
    assert out.returncode == 1 and "command not found" in out.stdout
    (cfg.brain / "config.d" / "night.json").write_text("{broken")
    boot = run_main("boot", brain=cfg.brain)
    assert boot.returncode == 0 and "night boot" in boot.stderr
    assert run_main("trigger", brain=cfg.brain).returncode == 1          # a broken config is an error, not a silent skip
    set_config(cfg.brain)
    assert run_main("bogus", brain=cfg.brain).returncode == 2


def test_cli_boot_shows_report_once(cfg):
    from night import report, runner

    report.write(cfg, [runner.TaskResult("01_a", "A", 1, 1, "finished", "ok")], NIGHT)
    run_main("boot", brain=cfg.brain)
    assert "01_a" in (cfg.brain / "state" / "boot.d" / "night.md").read_text()
    assert "01_a" in run_main("report", brain=cfg.brain).stdout
    note = cfg.brain / "state" / "boot.d" / "night.md"
    note.unlink()                              # the core injector deletes a `once` note after showing it
    run_main("boot", brain=cfg.brain)
    assert not note.exists()                   # nothing new: it does not come back


def test_cli_end_to_end_with_a_fake_claude_executable(cfg, tmp_path):
    fake = tmp_path / "fake_claude"
    fake.write_text(f"#!{sys.executable}\nimport sys\nsys.stdin.read()\nopen('output.txt','w').write('written by the task')\nprint('STATUS: done - wrote output.txt')\n")
    fake.chmod(0o755)
    set_config(cfg.brain, claude_bin=str(fake), keep_awake=False)
    task = make_task(cfg, "01_e2e", steps=1)
    out = run_main("trigger", "--force", brain=cfg.brain)
    assert out.returncode == 0 and "01_e2e**: done (1/1 steps)" in out.stdout
    assert (cfg.done / "01_e2e_" / "..").exists() or any(p.name.startswith("01_e2e_") for p in cfg.done.iterdir())
    finished = next(p for p in cfg.done.iterdir() if p.name.startswith("01_e2e_"))
    assert (finished / "work" / "output.txt").read_text() == "written by the task" and not task.exists()


# ---------- module ----------

MODULE = Path(__file__).resolve().parents[1]


def test_module_toml_valid_for_core_cli():
    core_lib = MODULE.parents[1] / "core" / "lib"
    if not (core_lib / "carlo_modules.py").exists():
        pytest.skip("core CLI not present")
    sys.path.insert(0, str(core_lib))
    import carlo_modules

    module = carlo_modules.load_module(MODULE)
    assert module.name == "night" and module.launchd[0]["interval"] == 600 and module.hooks[0]["event"] == "SessionStart"


@pytest.mark.parametrize("script", sorted((MODULE / "src").glob("*.sh")) + [MODULE / "install.sh", MODULE / "uninstall.sh"], ids=lambda p: p.name)
def test_scripts_parse(script):
    assert subprocess.run(["bash", "-n", str(script)], capture_output=True).returncode == 0


def test_example_task_is_valid_and_no_personal_data(cfg):
    from night import tasks

    shutil_copy = __import__("shutil").copytree
    shutil_copy(MODULE / "src" / "example_task", cfg.queue / "01_example")
    task = tasks.load_task(cfg.queue / "01_example", cfg)
    assert task.steps == 3 and "{STEP}" in (task.path / "prompt.md").read_text()
    for path in MODULE.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts and path.name != "test_night_trigger_marathon_cli.py":
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for word in ("na" "tan", "/us" "ers/", "las" "ar", "@gm" "ail"):
                assert word not in text, f"{word} in {path}"
