import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import install_agents as ia

MODULE = Path(__file__).resolve().parents[1]
SRC = MODULE / "src"
AGENT_FILES = sorted((SRC / "agents").glob("*.md"))
SKILL_FILES = sorted((SRC / "skills").glob("*/SKILL.md"))
EXPECTED_AGENTS = {"researcher", "cto", "reader", "listener", "improver", "video-quiz", "reviewer"}
EXPECTED_SKILLS = {"writer", "docs", "explainer", "browse"}


def front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no front matter"
    block = text.split("\n---\n", 1)[0][4:]
    out = {}
    for line in block.splitlines():
        match = re.match(r"^([A-Za-z-]+):\s*(.*)$", line)
        if match:
            out[match.group(1)] = match.group(2).strip().strip('"')
    return out


# ---------- content ----------

def test_the_expected_agents_and_skills_exist():
    assert {p.stem for p in AGENT_FILES} == EXPECTED_AGENTS
    assert {p.parent.name for p in SKILL_FILES} == EXPECTED_SKILLS


@pytest.mark.parametrize("path", AGENT_FILES, ids=lambda p: p.stem)
def test_agent_front_matter(path):
    meta = front_matter(path)
    assert meta["name"] == path.stem and len(meta["description"]) > 40
    assert meta["model"] in {"sonnet", "opus", "haiku", "inherit"}
    tools = [t.strip() for t in re.split(r",(?![^()]*\))", meta["tools"])]
    assert tools and all(re.fullmatch(r"[A-Za-z]+(\([^)]*\))?", t) for t in tools), tools


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_front_matter(path):
    meta = front_matter(path)
    assert meta["name"] == path.parent.name and len(meta["description"]) > 40


def test_read_only_agents_have_no_write_tools():
    for name in ("reader", "listener", "researcher", "reviewer"):
        tools = front_matter(SRC / "agents" / f"{name}.md")["tools"]
        assert not re.search(r"\b(Write|Edit|Bash)\b", tools), name


def test_no_personal_data_dashes_or_private_paths_anywhere():
    banned = ("/users/", "@gmail", "\u2014", "\u2013") + tuple([t.strip().lower() for t in os.environ.get("CARLO_BRAIN_BANNED", "").split(",") if t.strip()])  # extra private terms: CARLO_BRAIN_BANNED=a,b (maintainer, local)
    for path in MODULE.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts and path.name != "test_agents_skills.py":
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for word in banned:
                assert word.lower() not in text, f"{word!r} in {path}"


def test_agents_never_hardcode_a_home_directory():
    for path in list(AGENT_FILES) + SKILL_FILES:
        assert not re.search(r"/home/\w+|C:\\\\Users", path.read_text())


def test_improver_points_at_the_prompt_the_self_improve_module_ships():
    text = (SRC / "agents" / "improver.md").read_text()
    assert "~/.carlo-brain/self-improve/prompts/improver.md" in text
    shipped = MODULE.parent / "self-improve" / "src" / "prompts" / "improver.md"
    if shipped.exists():
        assert shipped.is_file()


def test_video_quiz_points_at_the_script_this_module_ships():
    text = (SRC / "agents" / "video-quiz.md").read_text()
    assert "~/.carlo-brain/agents-skills/scripts/transcribe.sh" in text and (SRC / "scripts" / "transcribe.sh").exists()


# ---------- installer ----------

def tree(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_install_copies_everything_and_is_idempotent(isolated):
    lines = ia.install()
    claude = isolated / "claude"
    assert (claude / "agents" / "cto.md").exists() and (claude / "skills" / "writer" / "SKILL.md").exists()
    assert (claude / "skills" / "explainer" / "references" / "rules.md").exists()
    assert len([l for l in lines if l.startswith("installed:")]) == len(ia.sources())
    assert ia.install() == []                                                 # second run: nothing to do
    assert set(ia.load_manifest()) == {rel for rel, _ in ia.sources()}


def test_your_own_file_with_the_same_name_is_never_overwritten(isolated):
    claude = isolated / "claude"
    (claude / "agents").mkdir(parents=True)
    mine = claude / "agents" / "researcher.md"
    mine.write_text("my own researcher agent\n")
    lines = ia.install()
    assert mine.read_text() == "my own researcher agent\n"
    assert "kept yours: agents/researcher.md" in "\n".join(lines)
    assert (claude / "agents" / "researcher.md.new").read_text() == (SRC / "agents" / "researcher.md").read_text()
    assert "agents/researcher.md" not in ia.load_manifest()                   # not ours, so uninstall will not touch it
    ia.uninstall()
    assert mine.read_text() == "my own researcher agent\n"


def test_update_replaces_unedited_files_but_not_edited_ones(isolated, monkeypatch):
    work = isolated / "module_copy"
    shutil.copytree(SRC, work)
    monkeypatch.setattr(ia, "HERE", work)
    ia.install()
    claude = isolated / "claude"
    (work / "agents" / "reader.md").write_text((work / "agents" / "reader.md").read_text() + "\nNew rule.\n")
    (work / "agents" / "cto.md").write_text((work / "agents" / "cto.md").read_text() + "\nNew rule.\n")
    (claude / "agents" / "cto.md").write_text("edited by the user\n")
    lines = "\n".join(ia.install())
    assert "updated: agents/reader.md" in lines and "New rule." in (claude / "agents" / "reader.md").read_text()
    assert "kept yours: agents/cto.md" in lines and (claude / "agents" / "cto.md").read_text() == "edited by the user\n"


def test_uninstall_removes_ours_keeps_edits_and_prunes_folders(isolated):
    ia.install()
    claude = isolated / "claude"
    (claude / "skills" / "docs" / "SKILL.md").write_text("my edit\n")
    lines = "\n".join(ia.uninstall())
    assert "kept (you edited it): skills/docs/SKILL.md" in lines
    assert (claude / "skills" / "docs" / "SKILL.md").read_text() == "my edit\n"
    assert not (claude / "agents" / "cto.md").exists() and not (claude / "skills" / "writer").exists()   # empty folder pruned
    assert (claude / "skills").exists() and set(ia.load_manifest()) == {"skills/docs/SKILL.md"}


def test_skip_option_and_user_files_elsewhere_are_untouched(isolated):
    claude = isolated / "claude"
    (claude / "agents").mkdir(parents=True)
    (claude / "agents" / "unrelated.md").write_text("unrelated\n")
    ia.install(skip=("cto", "docs"))
    assert not (claude / "agents" / "cto.md").exists() and not (claude / "skills" / "docs").exists()
    ia.uninstall()
    assert (claude / "agents" / "unrelated.md").read_text() == "unrelated\n"


def test_status_reports_each_state(isolated):
    claude = isolated / "claude"
    assert all(line.endswith("missing") for line in ia.status())
    ia.install()
    assert all("installed, current" in line for line in ia.status())
    (claude / "agents" / "cto.md").write_text("changed\n")
    assert any(line.startswith("agents/cto.md") and "yours or edited" in line for line in ia.status())


def test_path_traversal_is_refused(isolated):
    root = isolated / "claude"
    root.mkdir()
    with pytest.raises(ValueError):
        ia.safe_target(root, "../outside.md")
    link_target = isolated / "elsewhere"
    link_target.mkdir()
    os.symlink(link_target, root / "agents")
    with pytest.raises(ValueError):
        ia.safe_target(root, "agents/x.md")


def test_cli_install_status_uninstall(isolated):
    env = {k: v for k, v in os.environ.items()}
    run = lambda *a: subprocess.run([sys.executable, "-I", str(SRC / "install_agents.py"), *a], capture_output=True, text=True, env=env)
    assert run("install").returncode == 0 and (isolated / "claude" / "agents" / "researcher.md").exists()
    assert "installed, current" in run("status").stdout
    assert "removed: agents/researcher.md" in run("uninstall").stdout
    assert run("bogus").returncode == 2


def test_module_toml_valid_for_core_cli():
    core_lib = MODULE.parents[1] / "core" / "lib"
    if not (core_lib / "carlo_modules.py").exists():
        pytest.skip("core CLI not present")
    sys.path.insert(0, str(core_lib))
    import carlo_modules

    module = carlo_modules.load_module(MODULE)
    assert module.name == "agents-skills" and not module.hooks and not module.launchd


# ---------- transcribe.sh ----------

TRANSCRIBE = SRC / "scripts" / "transcribe.sh"


def fake_toolchain(folder: Path, whisper_ok=True):
    folder.mkdir()
    (folder / "ffmpeg").write_text("#!/bin/sh\nfor last; do :; done\nprintf 'wav' > \"$last\"\n")
    out = "printf 'hello world' > \"$OF.txt\"; printf 'WEBVTT' > \"$OF.vtt\"" if whisper_ok else "exit 1"
    (folder / "whisper-cli").write_text(
        "#!/bin/sh\nOF=\nwhile [ $# -gt 0 ]; do [ \"$1\" = -of ] && OF=\"$2\"; shift; done\n" + out + "\n")
    for tool in folder.iterdir():
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)


def run_transcribe(isolated, *args, whisper_ok=True, model=True, tag="bin"):
    bin_dir = isolated / tag
    fake_toolchain(bin_dir, whisper_ok)
    model_file = isolated / f"{tag}_model.bin"
    if model:
        model_file.write_text("m")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "WHISPER_MODEL": str(model_file), "TRANSCRIBE_OUT": str(isolated / "out"), "HOME": str(isolated / "home")}
    return subprocess.run(["bash", str(TRANSCRIBE), *args], capture_output=True, text=True, env=env)


def test_transcribe_script_syntax_and_usage():
    assert subprocess.run(["bash", "-n", str(TRANSCRIBE)], capture_output=True).returncode == 0
    out = subprocess.run(["bash", str(TRANSCRIBE)], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"})
    assert out.returncode == 1 and "usage" in out.stderr


def test_transcribe_produces_txt_and_vtt(isolated):
    media = isolated / "talk.mp4"
    media.write_text("x")
    out = run_transcribe(isolated, str(media), "en", "my talk!")
    assert out.returncode == 0, out.stderr
    txt, vtt = out.stdout.split()
    assert Path(txt).name == "my_talk_.txt" and Path(txt).read_text() == "hello world" and Path(vtt).read_text() == "WEBVTT"


def test_transcribe_failures_are_explicit(isolated):
    media = isolated / "talk.mp4"
    media.write_text("x")
    failed = run_transcribe(isolated, str(media), whisper_ok=False, tag="bin_failing")
    assert failed.returncode == 1 and "transcription failed" in failed.stderr
    missing = run_transcribe(isolated, str(isolated / "nope.mp4"), tag="bin_missing")
    assert missing.returncode == 1 and "file not found" in missing.stderr
    broken = subprocess.run(["bash", str(TRANSCRIBE), str(media)], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"})
    assert broken.returncode == 1 and "not found in PATH" in broken.stderr
    no_model = run_transcribe(isolated, str(media), model=False, tag="bin_nomodel")
    assert no_model.returncode == 1 and "model missing" in no_model.stderr
