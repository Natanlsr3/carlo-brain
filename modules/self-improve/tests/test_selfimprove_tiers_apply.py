import json
import os

import pytest

from selfimprove import apply as apply_mod
from selfimprove import journal, tiers, undo
from selfimprove.settings import Settings


def proposal(pid="p1", **kw):
    base = {"id": pid, "title": "t", "reason": "r", "source": "s", "changes": []}
    base.update(kw)
    return base


def agent(cfg, name="helper.md", text="# Helper\nBe brief.\n"):
    path = cfg.home / ".claude" / "agents" / name
    path.write_text(text)
    return path


# ---------- tiers ----------

def test_tier_table(cfg):
    home, vault = cfg.home, cfg.vault_path
    cases = {
        home / ".claude/agents/x.md": "auto",
        vault / "00_System/skills/deep/y.md": "auto",
        vault / "00_System/memory/MEMORY.md": "auto",
        vault / "00_System/SYSTEM_PROMPT.md": "review",
        home / ".claude/CLAUDE.md": "review",
        home / ".claude/settings.json": "review",
        home / ".claude/agents/send-reminders.md": "review",          # a name that suggests sending
        home / ".carlo-brain/keys/anything.txt": "manual",
        home / ".carlo-brain/self-improve/tiers.json": "manual",
        home / ".carlo-brain/config.d/telegram.json": "manual",
        home / ".carlo-brain/config.d/self-improve.json": "manual",
        home / ".carlo-brain/config.d/proactive.json": "auto",
        home / ".claude/agents/api_key_notes.md": "manual",           # sensitive name beats the auto folder
        home / "Documents/random.md": "review",                        # unknown path = review
    }
    for path, expected in cases.items():
        assert tiers.tier_of(path, cfg) == expected, path


def test_batch_takes_the_strictest_tier(cfg):
    paths = [cfg.home / ".claude/agents/a.md", cfg.vault_path / "00_System/SYSTEM_PROMPT.md"]
    assert tiers.tier_of_all(paths, cfg) == "review"
    assert tiers.tier_of_all(paths + [cfg.home / ".ssh/id_rsa"], cfg) == "manual"
    assert tiers.tier_of_all([], cfg) == "review"


def test_symlink_cannot_smuggle_a_file_into_a_looser_tier(cfg, tmp_path):
    secret_area = cfg.home / ".carlo-brain" / "keys"
    secret_area.mkdir(parents=True)
    (secret_area / "stored.txt").write_text("x")
    link = cfg.home / ".claude" / "agents" / "innocent.md"
    os.symlink(secret_area / "stored.txt", link)
    assert tiers.tier_of(link, cfg) == "manual"


def test_config_cannot_weaken_hard_manual_rules(cfg):
    weak = Settings(home=cfg.home, brain=cfg.brain, vault_path=cfg.vault_path,
                    tiers={"auto": ["~/.carlo-brain/keys/**", "~/.carlo-brain/self-improve/**"], "review": []})
    assert tiers.tier_of(cfg.home / ".carlo-brain/keys/a.txt", weak) == "manual"
    assert tiers.tier_of(cfg.home / ".carlo-brain/self-improve/main.py", weak) == "manual"


def test_vault_patterns_are_ignored_without_a_vault(cfg):
    novault = Settings(home=cfg.home, brain=cfg.brain, vault_path=None)
    assert tiers.tier_of(cfg.home / ".claude/agents/a.md", novault) == "auto"
    assert tiers.tier_of(cfg.home / "vault/00_System/skills/a.md", novault) == "review"


def test_settings_load_and_reject_bad_values(cfg, monkeypatch):
    from selfimprove import settings

    (cfg.brain / "config.json").write_text(json.dumps({"vault": str(cfg.vault_path)}))
    (cfg.brain / "config.d" / "self-improve.json").write_text(json.dumps({
        "tiers": {"auto": ["~/x/**"], "review": "oops"}, "verify": {"forbidden_in_markdown": ["!"], "test_timeout_s": 99999}}))
    loaded = settings.load(cfg.home)
    assert loaded.vault_path == cfg.vault_path and loaded.tiers["auto"] == ["~/x/**"]
    assert loaded.tiers["review"] == settings.DEFAULT_TIERS["review"]   # wrong type ignored
    assert loaded.test_timeout == 60 and loaded.forbidden_in_markdown == ["!"]


# ---------- apply ----------

def test_auto_change_is_applied_backed_up_and_journaled(cfg):
    path = agent(cfg)
    entry = apply_mod.process(proposal(changes=[{"file": str(path), "old": "Be brief.", "new": "Be brief and precise."}]), cfg)
    assert entry["verdict"] == "applied" and entry["tier"] == "auto"
    assert "precise" in path.read_text()
    archive = cfg.archives / "p1"
    assert json.loads((archive / "manifest.json").read_text())["status"] == "applied"
    assert any("Be brief.\n" in f.read_text() for f in archive.glob("*helper.md"))      # original saved
    assert "applied (tier auto)" in (cfg.improvement / "CHANGELOG.md").read_text()
    assert json.loads((cfg.state / "journal.jsonl").read_text().splitlines()[0])["verdict"] == "applied"


def test_failed_check_restores_every_file_byte_for_byte(cfg):
    good = agent(cfg, "a.md", "alpha\n")
    bad_json = cfg.home / ".carlo-brain" / "config.d" / "thing.json"
    bad_json.write_text('{"ok": true}')
    entry = apply_mod.process(proposal(changes=[
        {"file": str(good), "old": "alpha", "new": "beta"},
        {"file": str(bad_json), "content": "{not json"}]), cfg)
    assert entry["verdict"] == "restored" and "invalid .json" in entry["reason"]
    assert good.read_text() == "alpha\n" and bad_json.read_text() == '{"ok": true}'


def test_new_file_created_by_a_failed_proposal_is_removed(cfg):
    new = cfg.home / ".claude" / "agents" / "new.md"
    entry = apply_mod.process(proposal(changes=[{"file": str(new), "content": "---\nname x\n---\nbody"}]), cfg)
    assert entry["verdict"] == "restored" and not new.exists()


def test_test_command_failure_restores(cfg):
    path = agent(cfg)
    entry = apply_mod.process(proposal(changes=[{"file": str(path), "old": "Be brief.", "new": "Changed."}],
                                       test_command=f"{os.sys.executable} -c 'import sys; sys.exit(3)'"), cfg)
    assert entry["verdict"] == "restored" and "failed (3)" in entry["reason"]
    assert "Be brief." in path.read_text()
    ok = apply_mod.process(proposal("p2", changes=[{"file": str(path), "old": "Be brief.", "new": "Changed."}],
                                    test_command=f"{os.sys.executable} -c 'pass'"), cfg)
    assert ok["verdict"] == "applied"


def test_python_change_is_syntax_and_test_checked(cfg):
    tool = cfg.home / ".claude" / "skills" / "tool"
    tool.mkdir(parents=True)
    script = tool / "helper.py"
    script.write_text("def f():\n    return 1\n")
    (tool / "test_helper.py").write_text("import helper\n\ndef test_f():\n    assert helper.f() == 1\n")
    broken = apply_mod.process(proposal(changes=[{"file": str(script), "old": "return 1", "new": "return 2"}]), cfg)
    assert broken["verdict"] == "restored" and script.read_text().endswith("return 1\n")    # the neighbouring test failed
    fine = apply_mod.process(proposal("p2", changes=[{"file": str(script), "old": "return 1", "new": "return 1  # same"}]), cfg)
    assert fine["verdict"] == "applied"


def test_markdown_checks_front_matter_links_and_configurable_characters(cfg):
    memory = cfg.vault_path / "00_System" / "memory" / "MEMORY.md"
    memory.write_text("- [Note](note.md): a note\n")
    (cfg.vault_path / "00_System" / "memory" / "note.md").write_text("n\n")
    broken_link = apply_mod.process(proposal(changes=[{"file": str(memory), "old": "- [Note](note.md): a note", "new": "- [Note](note.md): a note\n- [Ghost](ghost.md): missing"}]), cfg)
    assert broken_link["verdict"] == "restored" and "broken index link: ghost.md" in broken_link["reason"]
    skill = cfg.vault_path / "00_System" / "skills" / "s.md"
    bad_fm = apply_mod.process(proposal("p2", changes=[{"file": str(skill), "content": "---\nname: ok\nbroken line\n---\ntext"}]), cfg)
    assert bad_fm["verdict"] == "restored" and "front matter line 3" in bad_fm["reason"]
    strict = Settings(home=cfg.home, brain=cfg.brain, vault_path=cfg.vault_path, forbidden_in_markdown=["\u2014"])
    dash = apply_mod.process(proposal("p3", changes=[{"file": str(skill), "content": "a \u2014 b"}]), strict)
    assert dash["verdict"] == "restored"
    lenient = apply_mod.process(proposal("p4", changes=[{"file": str(skill), "content": "a \u2014 b"}]), cfg)
    assert lenient["verdict"] == "applied"


def test_review_tier_writes_a_diff_and_changes_nothing(cfg):
    prompt = cfg.vault_path / "00_System" / "SYSTEM_PROMPT.md"
    prompt.write_text("line one\nline two\n")
    entry = apply_mod.process(proposal(changes=[{"file": str(prompt), "old": "line two", "new": "line 2"}]), cfg)
    assert entry["verdict"] == "to review" and prompt.read_text() == "line one\nline two\n"
    review = (cfg.to_review / "p1.md").read_text()
    assert "Current (line 2)" in review and "line two" in review and "line 2" in review
    again = apply_mod.process(proposal(changes=[{"file": str(prompt), "old": "line two", "new": "x"}]), cfg)
    assert again["verdict"] == "refused" and "already used" in again["reason"]


def test_manual_tier_is_refused_and_untouched(cfg):
    key_file = cfg.home / ".carlo-brain" / "keys" / "k.txt"
    key_file.parent.mkdir(parents=True)
    key_file.write_text("keep")
    entry = apply_mod.process(proposal(changes=[{"file": str(key_file), "content": "overwritten"}]), cfg)
    assert entry["verdict"] == "refused" and entry["tier"] == "manual" and key_file.read_text() == "keep"


def test_a_batch_mixing_tiers_takes_the_strictest_for_all_files(cfg):
    a = agent(cfg)
    prompt = cfg.vault_path / "00_System" / "SYSTEM_PROMPT.md"
    prompt.write_text("x\n")
    entry = apply_mod.process(proposal(changes=[{"file": str(a), "old": "Be brief.", "new": "Short."},
                                                {"file": str(prompt), "old": "x", "new": "y"}]), cfg)
    assert entry["verdict"] == "to review" and "Be brief." in a.read_text()      # the auto file was NOT applied


@pytest.mark.parametrize("old,why", [("missing text", "not found"), ("e", "ambiguous")])
def test_old_text_must_match_exactly_once(cfg, old, why):
    path = agent(cfg, text="eee\n")
    entry = apply_mod.process(proposal(changes=[{"file": str(path), "old": old, "new": "z"}]), cfg)
    assert entry["verdict"] == "refused" and why in entry["reason"] and path.read_text() == "eee\n"


def test_two_changes_to_the_same_file_compose(cfg):
    path = agent(cfg, text="one\ntwo\n")
    entry = apply_mod.process(proposal(changes=[{"file": str(path), "old": "one", "new": "1"}, {"file": str(path), "old": "two", "new": "2"}]), cfg)
    assert entry["verdict"] == "applied" and path.read_text() == "1\n2\n"


def test_dry_run_writes_nothing_not_even_the_journal(cfg):
    path = agent(cfg)
    entry = apply_mod.process(proposal(changes=[{"file": str(path), "old": "Be brief.", "new": "x"}]), cfg, dry_run=True)
    assert entry["verdict"] == "dry run" and "would be applied" in entry["reason"]
    assert "Be brief." in path.read_text() and not cfg.state.exists()


def test_dry_run_reports_failing_text_checks(cfg):
    entry = apply_mod.process(proposal(changes=[{"file": str(cfg.home / ".claude/agents/a.json"), "content": "{bad"}]), cfg, dry_run=True)
    assert "checks failed" in entry["reason"]


@pytest.mark.parametrize("patch", [
    {"id": "../escape"}, {"id": ""}, {"title": ""}, {"changes": []}, {"changes": [{"file": "x"}]},
    {"changes": [{"file": "x", "content": "a", "old": "b", "new": "c"}]}, {"changes": [{"file": "x", "old": "", "new": "c"}]},
    {"test_command": 5},
])
def test_malformed_proposals_are_rejected(cfg, patch):
    bad = proposal(changes=[{"file": "x", "content": "y"}])
    bad.update(patch)
    with pytest.raises(ValueError):
        apply_mod.validate(bad)
    with pytest.raises(ValueError):
        apply_mod.validate("not a dict")


def test_folder_target_and_binary_target_are_refused(cfg):
    folder = cfg.home / ".claude" / "agents" / "folder.md"
    folder.mkdir()
    assert apply_mod.process(proposal(changes=[{"file": str(folder), "content": "x"}]), cfg)["verdict"] == "refused"
    binary = cfg.home / ".claude" / "agents" / "bin.md"
    binary.write_bytes(b"\xff\xfe\x00bad")
    assert "not UTF-8" in apply_mod.process(proposal("p2", changes=[{"file": str(binary), "old": "a", "new": "b"}]), cfg)["reason"]


# ---------- undo ----------

def test_undo_restores_and_is_refused_when_file_changed_since(cfg):
    path = agent(cfg)
    apply_mod.process(proposal(changes=[{"file": str(path), "old": "Be brief.", "new": "Changed."}]), cfg)
    path.write_text("edited by the owner afterwards\n")
    ok, message = undo.undo("p1", cfg)
    assert not ok and "changed since" in message and "owner" in path.read_text()
    ok, message = undo.undo("p1", cfg, force=True)
    assert ok and "Be brief." in path.read_text()
    assert undo.undo("p1", cfg)[1].startswith("nothing to undo")


def test_undo_removes_a_file_the_proposal_created(cfg):
    new = cfg.home / ".claude" / "agents" / "created.md"
    apply_mod.process(proposal(changes=[{"file": str(new), "content": "# created\n"}]), cfg)
    assert new.exists()
    assert undo.undo("p1", cfg)[0] and not new.exists()


def test_undo_input_validation(cfg):
    assert undo.undo("../x", cfg) == (False, "invalid id")
    assert not undo.undo("nope", cfg)[0]


def test_journal_newest_first_and_hashes(cfg):
    path = agent(cfg)
    apply_mod.process(proposal("a", changes=[{"file": str(path), "old": "Be brief.", "new": "One."}]), cfg)
    apply_mod.process(proposal("b", changes=[{"file": str(path), "old": "One.", "new": "Two."}]), cfg)
    lines = (cfg.improvement / "CHANGELOG.md").read_text().splitlines()
    assert [l for l in lines if l.startswith("- ")][0].endswith("[b]: checks passed")
    entries = [json.loads(l) for l in (cfg.state / "journal.jsonl").read_text().splitlines()]
    assert entries[1]["hash_before"] == entries[0]["hash_after"]
