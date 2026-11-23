import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from helpers_selfimprove import make_fake_claude
from selfimprove import bench, jobs, runner, scheduler, status

MAIN = Path(__file__).resolve().parents[1] / "src" / "main.py"


# ---------- runner ----------

def test_success_records_state(cfg):
    code = runner.execute(cfg, "t1", "echo hello", retries=0)
    state = runner.read_state(cfg, "t1")
    assert code == 0 and state["status"] == "done" and state["error"] == "" and state["last_success"]
    assert "hello" in (cfg.state / "logs" / "t1.log").read_text()


def test_failure_retries_are_bounded_and_wait_grows(cfg):
    waits, attempts = [], []

    def once(c, name, command):
        attempts.append(1)
        return 1, "boom\nsecond line"

    code = runner.execute(cfg, "t2", "x", retries=2, wait_s=10, once=once, sleep=waits.append)
    assert code == 1 and len(attempts) == 3 and waits == [10, 20]
    state = runner.read_state(cfg, "t2")
    assert state["status"] == "failed" and state["error"] == "second line" and state["attempts"] == 3


@pytest.mark.parametrize("definitive", [126, 127, 78])
def test_definitive_failures_are_not_retried(cfg, definitive):
    calls = []
    runner.execute(cfg, "t3", "x", retries=3, once=lambda c, n, cmd: calls.append(1) or (definitive, "nope"), sleep=lambda s: None)
    assert len(calls) == 1


def test_retry_then_success_clears_the_error(cfg):
    results = iter([(1, "flaky"), (0, "fine")])
    assert runner.execute(cfg, "t4", "x", retries=1, once=lambda c, n, cmd: next(results), sleep=lambda s: None) == 0
    assert runner.read_state(cfg, "t4")["error"] == ""


def test_second_copy_does_not_run_while_locked(cfg):
    import fcntl

    runner.tasks_dir(cfg).mkdir(parents=True)
    held = open(runner.tasks_dir(cfg) / "t5.lock", "w")
    fcntl.flock(held, fcntl.LOCK_EX)
    calls = []
    try:
        assert runner.execute(cfg, "t5", "x", once=lambda *a: calls.append(1) or (0, "")) == 0
    finally:
        held.close()
    assert calls == []


def test_missing_command_is_127_and_task_env_is_set(cfg):
    code, out = runner.run_once(cfg, "t6", "echo $CARLO_TASK; nonexistent-command-xyz")
    assert code == 127 and "t6" in out


# ---------- scheduler ----------

TASK = {"name": "weekly", "command": "echo", "days": ["sun"], "time": "09:00", "window_h": 72, "catch_up": True}
SUNDAY_10 = datetime(2026, 3, 8, 10, 0)   # a Sunday


def test_latest_slot_and_due_logic():
    assert scheduler.latest_slot(TASK, SUNDAY_10) == datetime(2026, 3, 8, 9, 0)
    assert scheduler.latest_slot(TASK, datetime(2026, 3, 8, 8, 59)) == datetime(2026, 3, 1, 9, 0)   # before the slot: last week's
    assert scheduler.due_slot(TASK, {}, SUNDAY_10) == datetime(2026, 3, 8, 9, 0)
    assert scheduler.due_slot(TASK, {"last_slot": "2026-03-08T09:00:00"}, SUNDAY_10) is None         # already launched
    assert scheduler.due_slot(TASK, {"last_slot": "2026-03-01T09:00:00"}, SUNDAY_10) is not None


def test_missed_slot_is_caught_up_within_window_only():
    tuesday = datetime(2026, 3, 10, 20, 0)                     # machine was off since Sunday
    assert scheduler.due_slot(TASK, {}, tuesday) == datetime(2026, 3, 8, 9, 0)
    assert scheduler.due_slot(TASK, {}, datetime(2026, 3, 12, 9, 0)) is None  # more than 72 h late: dropped
    strict = {**TASK, "catch_up": False}
    assert scheduler.due_slot(strict, {}, tuesday) is None
    assert scheduler.due_slot(strict, {}, datetime(2026, 3, 8, 9, 20)) is not None   # within tolerance


def test_tick_marks_slot_before_launch_so_it_cannot_run_twice(cfg):
    launched = []
    lines = scheduler.tick(cfg, [TASK], SUNDAY_10, launched.append)
    assert launched == ["weekly"] and lines[0].startswith("started: weekly")
    assert scheduler.tick(cfg, [TASK], SUNDAY_10 + timedelta(minutes=30), launched.append) == [] and len(launched) == 1
    late = scheduler.tick(cfg, [{**TASK, "name": "other"}], datetime(2026, 3, 10, 9, 0), launched.append)
    assert "h late" in late[0]


def test_task_file_validation(cfg, tmp_path):
    f = tmp_path / "t.json"

    def load(data):
        f.write_text(json.dumps(data))
        return scheduler.load_tasks(cfg, f)

    assert load({"tasks": [TASK]})[0]["name"] == "weekly"
    for bad in ({"tasks": [{**TASK, "name": "Bad Name"}]}, {"tasks": [{**TASK, "time": "9am"}]}, {"tasks": [{**TASK, "days": ["funday"]}]},
                {"tasks": [{**TASK, "command": ""}]}, {"tasks": [TASK, TASK]}, {"nope": 1}, []):
        with pytest.raises(ValueError):
            load(bad)
    f.write_text("{broken")
    with pytest.raises(ValueError):
        scheduler.load_tasks(cfg, f)
    assert scheduler.load_tasks(cfg, tmp_path / "absent.json") == []


# ---------- status ----------

def test_status_lines_for_boot(cfg):
    runner.write_state(cfg, "weekly", {"status": "failed", "error": "claude not found", "attempts": 2})
    cfg.to_review.mkdir(parents=True)
    (cfg.to_review / "p.md").write_text("x")
    reports = cfg.improvement / "reports"
    reports.mkdir(parents=True)
    (reports / "A.md").write_text("---\nstatus: unread\n---\nbody")
    (reports / "B.md").write_text("---\nstatus: read\n---\nbody")
    lines = status.lines_for_boot(cfg, [TASK], ["started: weekly (slot Sun 09:00)"])
    text = "\n".join(lines)
    assert "task weekly failed (2 attempt(s)): claude not found" in text
    assert "1 proposal(s) wait for your review" in text and "1 unread report(s)" in text and "started: weekly" in text
    status.write_boot_file(cfg, lines)
    assert (cfg.brain_dir / "state" / "boot.d" / "self-improve.md").exists()
    status.write_boot_file(cfg, [])
    assert not (cfg.brain_dir / "state" / "boot.d" / "self-improve.md").exists()


# ---------- jobs ----------

FAKE_JOB = """
args = sys.argv[1:]
prompt = sys.stdin.read()
open(os.path.join(os.getcwd(), "seen_args.json"), "w").write(json.dumps({"args": args, "prompt_len": len(prompt),
     "has_keys": any("API_KEY" in k for k in os.environ), "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")}))
if os.environ.get("FAKE_MODE") != "silent":
    open("REPORT.md", "w").write("# Report\\n- finding\\n")
    os.makedirs("proposals", exist_ok=True)
    good = {"id": "2026-03-08-x", "title": "t", "reason": "r", "source": "s", "changes": [{"file": "~/a.md", "content": "x"}]}
    open("proposals/good.json", "w").write(json.dumps(good))
    open("proposals/bad.json", "w").write(json.dumps({"id": "no-changes"}))
    open("proposals/garbage.json", "w").write("{{{")
"""


def test_job_command_confines_the_model(cfg):
    out = cfg.state / "jobs" / "scout" / "2026-03-08"
    cmd = jobs.command_for("scout", cfg, out, "claude")
    assert cmd[:2] == ["claude", "-p"] and "--permission-mode" in cmd and "acceptEdits" in cmd
    allowed = cmd[cmd.index("--allowedTools") + 1]
    assert "Edit(./**)" in allowed and "Bash" not in allowed
    deny = cmd[cmd.index("--disallowedTools") + 1]
    assert f"Edit(/{os.path.realpath(cfg.vault_path)}/**)" in deny and "mcp__whatsapp__send_message" in deny
    assert cmd[cmd.index("--add-dir") + 1] == os.path.realpath(cfg.vault_path)


def test_job_run_collects_report_and_valid_proposals_only(cfg, tmp_path):
    fake = make_fake_claude(tmp_path / "claude", FAKE_JOB)
    keyfile = cfg.brain_dir / "keys" / "claude_oauth_token"
    keyfile.parent.mkdir(parents=True)
    keyfile.write_text("sk-ant-fake-login")
    keyfile.chmod(0o600)
    env_key = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "must-not-leak"
    try:
        code = jobs.run_job("scout", cfg, str(fake), today="2026-03-08")
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        if env_key:
            os.environ["OPENAI_API_KEY"] = env_key
    assert code == 0
    report = (cfg.improvement / "reports" / "SCOUT_2026-03-08.md").read_text()
    assert report.startswith("---\ntype: scout\ndate: 2026-03-08\nstatus: unread\n---") and "finding" in report
    assert [p.name for p in cfg.proposals.glob("*.json")] == ["good.json"]          # invalid ones never reach the queue
    seen = json.loads((cfg.state / "jobs" / "scout" / "2026-03-08" / "seen_args.json").read_text())
    assert seen["has_keys"] is False and seen["token"] == "sk-ant-fake-login" and seen["prompt_len"] > 500
    assert "Write ONLY there" in (jobs.build_prompt("scout", cfg.state, cfg, "2026-03-08"))


def test_job_without_report_fails_even_if_claude_exits_zero(cfg, tmp_path, monkeypatch, capsys):
    fake = make_fake_claude(tmp_path / "claude", FAKE_JOB)
    monkeypatch.setenv("FAKE_MODE", "silent")
    assert jobs.run_job("improver", cfg, str(fake), today="2026-03-08") == 1
    assert "no report produced" in capsys.readouterr().out
    assert not (cfg.improvement / "reports").exists()


def test_job_token_file_with_loose_permissions_is_ignored(cfg):
    keyfile = cfg.brain_dir / "keys" / "claude_oauth_token"
    keyfile.parent.mkdir(parents=True)
    keyfile.write_text("sk-ant-x")
    keyfile.chmod(0o644)
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in jobs.login_env(cfg)


def test_job_missing_claude_and_unknown_job(cfg, capsys):
    assert jobs.run_job("scout", cfg, "/nonexistent/claude", today="2026-03-08") == 127
    with pytest.raises(ValueError):
        jobs.run_job("nope", cfg)
    assert jobs.run_job("scout", cfg, "claude", today="2026-03-09", dry_run=True) == 0


def test_prompts_have_no_personal_data_and_known_placeholders():
    for name in ("scout.md", "improver.md"):
        text = (jobs.prompts_dir() / name).read_text()
        assert "{OUT}" in text and "{VAULT}" in text and "{DATE}" in text
        assert not any(w in text.lower() for w in ("na" "tan", "/us" "ers/", "las" "ar"))


# ---------- bench ----------

FAKE_BENCH = """
judge = "--safe-mode" in sys.argv
sys.stdin.read()
text = os.environ.get("FAKE_JUDGE", '{"1": "YES", "2": "YES"}') if judge else os.environ.get("FAKE_ANSWER", "Canberra. Not the biggest city.")
if os.environ.get("FAKE_JUDGE_FAIL") and judge:
    sys.exit(3)
model = "claude-haiku-5-5" if judge else os.environ.get("FAKE_MODEL", "claude-opus-5-5")
print(json.dumps({"result": text, "total_cost_usd": 0.01, "is_error": False, "modelUsage": {model: {}}}))
"""


def write_case(folder, cid, quick=True, required=None, forbidden=None):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{cid}.json").write_text(json.dumps({
        "id": cid, "quick": quick, "title": cid, "source": "t", "prompt": "q?", "rules": ["short"],
        "mechanical": {"forbidden": forbidden or [], "required": required or []},
        "llm_criteria": ["first criterion", "second criterion"]}))


def run_bench(cases, results, fake, *args, env=None):
    cmd = [sys.executable, "-I", str(MAIN), "bench", "--command", str(fake), "--cases-dir", str(cases), "--results", str(results), *args]
    return subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})}, timeout=120)


def test_shipped_cases_are_well_formed_and_generic():
    cases = bench.load_cases()
    assert len(cases) >= 6 and sum(c.get("quick", False) for c in cases) >= 3
    for case in cases:
        assert {"id", "prompt", "rules", "llm_criteria"} <= set(case) and case["llm_criteria"]
        for rx in case["mechanical"]["forbidden"] + case["mechanical"]["required"]:
            __import__("re").compile(rx)
        assert not any(w in json.dumps(case).lower() for w in ("na" "tan", "/us" "ers/", "las" "ar"))
    for name, rx in bench.common_checks().items():
        assert __import__("re").compile(rx) and name


def test_verdict_parsing_is_strict():
    assert bench.read_verdicts('x {"1": "YES", "2": "no"} y', 2) == [True, False]
    for bad in ('{"1": "YES"}', '{"1": "YES", "2": "MAYBE"}', '{"1": "YES", "2": "NO", "3": "NO"}', "none", '{"1": "YES", "x": "NO"}'):
        assert bench.read_verdicts(bad, 2) is None


def test_mechanical_and_common_checks():
    case = {"mechanical": {"forbidden": ["bad"], "required": ["good"]}}
    results = bench.mechanical(case, "a good answer | with | table\n| a | b |", bench.DEFAULT_COMMON)
    ok = {r["name"]: r["ok"] for r in results}
    assert ok["no markdown table"] is False and ok["forbidden /bad/"] is True and ok["required /good/"] is True
    assert bench.mechanical(case, "bad \U0001F600", bench.DEFAULT_COMMON)[1]["ok"] is False   # emoji caught


def test_same_model_guard():
    assert bench.same_model("claude-haiku-5-5", "haiku") and not bench.same_model("claude-opus-5-5", "haiku") and not bench.same_model("", "haiku")


def test_full_bench_scores_and_records_reference(tmp_path):
    fake = make_fake_claude(tmp_path / "claude", FAKE_BENCH)
    cases, results = tmp_path / "cases", tmp_path / "results"
    write_case(cases, "a", required=["Canberra"])
    out = run_bench(cases, results, fake, "--reference")
    assert out.returncode == 0, out.stderr
    assert "Global score: 1.0 over 1 scored" in out.stdout and "reference recorded" in out.stdout
    assert (results / "REFERENCE.json").exists() and list(results.glob("*.txt"))


def test_quick_run_detects_a_drop_against_the_reference(tmp_path):
    fake = make_fake_claude(tmp_path / "claude", FAKE_BENCH)
    cases, results = tmp_path / "cases", tmp_path / "results"
    write_case(cases, "a", required=["Canberra"])
    assert run_bench(cases, results, fake, "--reference").returncode == 0
    same = run_bench(cases, results, fake, "--quick")
    assert same.returncode == 0 and "OK quick" in same.stdout
    worse = run_bench(cases, results, fake, "--quick", env={"FAKE_ANSWER": "Sydney", "FAKE_JUDGE": '{"1": "NO", "2": "NO"}'})
    assert worse.returncode == 1 and "DROP quick" in worse.stdout


def test_quick_run_without_reference_is_undecidable(tmp_path):
    fake = make_fake_claude(tmp_path / "claude", FAKE_BENCH)
    write_case(tmp_path / "cases", "a")
    out = run_bench(tmp_path / "cases", tmp_path / "results", fake, "--quick")
    assert out.returncode == 2 and "no reference" in out.stdout


def test_failing_judge_never_gives_a_default_score(tmp_path):
    fake = make_fake_claude(tmp_path / "claude", FAKE_BENCH)
    write_case(tmp_path / "cases", "a")
    out = run_bench(tmp_path / "cases", tmp_path / "results", fake, "--reference", env={"FAKE_JUDGE_FAIL": "1"})
    assert "NOT_JUDGED" in out.stdout and "Global score: none" in out.stdout
    assert out.returncode == 2 and not (tmp_path / "results" / "REFERENCE.json").exists()


def test_judge_equal_to_tested_model_is_an_error(tmp_path):
    fake = make_fake_claude(tmp_path / "claude", FAKE_BENCH)
    write_case(tmp_path / "cases", "a")
    out = run_bench(tmp_path / "cases", tmp_path / "results", fake, env={"FAKE_MODEL": "claude-haiku-5-5"})
    assert "same model" in out.stdout and out.returncode == 2


def test_compare_two_results(tmp_path):
    def res(score, date):
        return {"date": date, "global": {"score": score}, "cases": [{"id": "a", "score": score, "status": "scored"}]}

    lines, dropped = bench.compare(res(0.9, "d1"), res(0.7, "d2"))
    assert dropped and "WORSE" in "\n".join(lines)
    assert not bench.compare(res(0.7, "d1"), res(0.9, "d2"))[1]


# ---------- CLI ----------

def run_main(*args, env=None, home=None):
    e = {**os.environ, **(env or {})}
    return subprocess.run([sys.executable, "-I", str(MAIN), *args], capture_output=True, text=True, env=e, timeout=60)


def test_cli_boot_catches_up_applies_pending_and_writes_boot_note(cfg, tmp_path):
    (cfg.brain_dir / "config.json").write_text(json.dumps({"vault": str(cfg.vault_path)}))
    skill = cfg.vault_path / "00_System" / "skills" / "s.md"
    skill.write_text("old\n")
    cfg.proposals.mkdir(parents=True)
    (cfg.proposals / "one.json").write_text(json.dumps({"id": "cli-1", "title": "t", "reason": "r", "source": "s",
                                                         "changes": [{"file": str(skill), "old": "old", "new": "new"}]}))
    (cfg.proposals / "two.json").write_text("{broken")
    task = {"tasks": [{"name": "later", "command": "true", "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "time": "00:00", "window_h": 30}]}
    (cfg.brain_dir / "config.d" / "self-improve-tasks.json").write_text(json.dumps(task))
    out = run_main("boot", env={"HOME": str(cfg.home)})
    assert out.returncode == 0, out.stderr
    assert skill.read_text() == "new\n"
    assert sorted(p.name for p in (cfg.proposals / "done").iterdir()) == ["one.json", "two.json"]
    note = (cfg.brain_dir / "state" / "boot.d" / "self-improve.md").read_text()
    assert "started: later" in note and "proposal one.json: applied (auto)" in note and "two.json: refused" in note


def test_cli_boot_never_fails_with_a_broken_task_file(cfg):
    (cfg.brain_dir / "config.d" / "self-improve-tasks.json").write_text("{broken")
    out = run_main("boot", env={"HOME": str(cfg.home)})
    assert out.returncode == 0
    assert "task list invalid" in (cfg.brain_dir / "state" / "boot.d" / "self-improve.md").read_text()


def test_cli_init_never_overwrites_and_examples_are_valid(cfg):
    run_main("init", env={"HOME": str(cfg.home)})
    tasks_file = cfg.brain_dir / "config.d" / "self-improve-tasks.json"
    assert len(scheduler.load_tasks(cfg, tasks_file)) == 2
    tasks_file.write_text('{"tasks": []}')
    out = run_main("init", env={"HOME": str(cfg.home)})
    assert "kept" in out.stdout and tasks_file.read_text() == '{"tasks": []}'
    settings = json.loads((cfg.brain_dir / "config.d" / "self-improve.json").read_text())
    assert set(settings["tiers"]) == {"auto", "review"}


def test_cli_apply_dry_run_undo_and_usage(cfg, tmp_path):
    target = cfg.home / ".claude" / "agents" / "a.md"
    target.write_text("hello\n")
    pfile = tmp_path / "p.json"
    pfile.write_text(json.dumps({"id": "cli-apply", "title": "t", "reason": "r", "source": "s", "changes": [{"file": str(target), "old": "hello", "new": "bye"}]}))
    env = {"HOME": str(cfg.home)}
    assert run_main("apply", str(pfile), "--dry-run", env=env).returncode == 0 and target.read_text() == "hello\n"
    assert run_main("apply", str(pfile), env=env).returncode == 0 and target.read_text() == "bye\n"
    assert run_main("undo", "cli-apply", env=env).returncode == 0 and target.read_text() == "hello\n"
    assert run_main("apply", "/nonexistent.json", env=env).returncode == 1
    assert run_main("bogus", env=env).returncode == 2 and run_main(env=env).returncode == 2
    assert run_main("run-task", "nope", env=env).returncode == 78


def test_cli_status_reports_clean_state(cfg):
    out = run_main("status", env={"HOME": str(cfg.home)})
    assert out.returncode == 0 and "Nothing needs your attention" in out.stdout
