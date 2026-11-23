"""Repo-level tests: TOML subset, settings merge, CLAUDE.md block, and install/uninstall in a temp HOME."""
import copy
import json
import shlex
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

ROOT = support.ROOT

import carlo_modules as mods  # noqa: E402
import carlo_settings as st  # noqa: E402
import carlo_toml  # noqa: E402

USER_SETTINGS = {
    "model": "opus",
    "permissions": {"allow": ["Bash(ls:*)"]},
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine", "timeout": 3}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}],
    },
}


def carlo(env: "support.BrainEnv", *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "carlo"), *args], capture_output=True, text=True,
                          env=env.env(), timeout=120, stdin=subprocess.DEVNULL)


class TomlTest(unittest.TestCase):
    def test_mini_parser_matches_real_parser_on_every_module(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib not available (the mini parser is what runs here)")
        for file in (ROOT / "modules").glob("*/module.toml"):
            text = file.read_text()
            self.assertEqual(carlo_toml._mini_loads(text), tomllib.loads(text), file.parent.name)

    def test_mini_parser_features(self):
        data = carlo_toml._mini_loads('a = "x" # c\nb = [\n  "p",\n  "q",\n]\nn = 5\nok = true\n[[h]]\ne = "1"\n[[h]]\ne = "2"\n[t]\nk = \'v\'\n')
        self.assertEqual(data, {"a": "x", "b": ["p", "q"], "n": 5, "ok": True, "h": [{"e": "1"}, {"e": "2"}], "t": {"k": "v"}})

    def test_mini_parser_rejects_garbage(self):
        with self.assertRaises(carlo_toml.TomlError):
            carlo_toml._mini_loads("this is not toml")

    def test_every_module_loads_and_follows_contract(self):
        found = mods.discover(ROOT)
        self.assertTrue({"memory", "security", "sync"} <= set(found))
        for name, module in found.items():
            self.assertTrue((module.path / "README.md").exists(), f"{name} README")
            self.assertTrue(module.summary, name)
            for script in ("install.sh", "uninstall.sh"):
                self.assertTrue((module.path / script).exists(), f"{name}/{script}")
            for hook in module.hooks:
                script = hook["command"].split("{CODE}/")[1].split()[0]
                self.assertTrue((module.path / "src" / script).exists(), f"{name}: hook script {script}")


class SettingsTest(unittest.TestCase):
    ENTRIES = [{"event": "SessionStart", "matcher": "startup", "command": "python3 /x/boot.py", "timeout": 10},
               {"event": "Stop", "command": "python3 /x/stop.py"}]

    def test_add_is_pure_idempotent_and_preserves_user_entries(self):
        original = copy.deepcopy(USER_SETTINGS)
        once = st.add_module_hooks(USER_SETTINGS, "memory", self.ENTRIES)
        self.assertEqual(USER_SETTINGS, original, "input must not be mutated")
        twice = st.add_module_hooks(once, "memory", self.ENTRIES)
        self.assertEqual(once, twice)
        self.assertEqual(once["model"], "opus")
        self.assertEqual(len(once["hooks"]["Stop"]), 2)
        self.assertEqual(len(st.installed_commands(once, "memory")), 2)

    def test_remove_restores_original_exactly(self):
        added = st.add_module_hooks(USER_SETTINGS, "memory", self.ENTRIES)
        added = st.add_module_hooks(added, "security", self.ENTRIES[:1])
        self.assertEqual(st.remove_module_hooks(added, "memory")["hooks"]["SessionStart"][0]["hooks"][0]["command"].split("#")[-1].strip(), "carlo-brain:security")
        self.assertEqual(st.remove_module_hooks(st.remove_module_hooks(added, "memory"), "security"), USER_SETTINGS)
        self.assertEqual(st.remove_module_hooks(added), USER_SETTINGS)

    def test_empty_settings_roundtrip(self):
        added = st.add_module_hooks({}, "m", self.ENTRIES)
        self.assertEqual(st.remove_module_hooks(added), {})

    def test_command_tag_is_shell_safe_comment(self):
        tagged = st.tag_command("python3 -I /a/b.py arg", "memory")
        self.assertEqual(st.owner_of(tagged), "memory")
        self.assertEqual(st.tag_command(tagged, "memory"), tagged)
        self.assertEqual(subprocess.run(tagged.replace("python3 -I /a/b.py arg", "echo ran"), shell=True, capture_output=True, text=True).stdout, "ran\n")

    def test_block_insert_replace_remove(self):
        base = "# My rules\n\nBe nice.\n"
        with_block = st.with_block(base, "ONE")
        self.assertEqual(st.with_block(with_block, "TWO").count("carlo-brain:begin"), 1)
        self.assertIn("TWO", st.with_block(with_block, "TWO"))
        self.assertNotIn("ONE", st.with_block(with_block, "TWO"))
        self.assertEqual(st.without_block(with_block).strip(), base.strip())
        self.assertEqual(st.without_block(base), base)

    def test_broken_settings_raises_and_is_not_touched(self):
        with support.BrainEnv() as env:
            path = env.claude / "settings.json"
            path.write_text("{ not json")
            with self.assertRaises(st.SettingsError):
                st.load_settings()
            self.assertEqual(path.read_text(), "{ not json")

    def test_wrongly_shaped_hooks_are_refused_not_dropped(self):
        shapes = ({"hooks": {"Stop": "oops"}}, {"hooks": ["x"]}, {"hooks": "x"}, {"hooks": {"Stop": [1]}},
                  {"hooks": {"Stop": [{"hooks": "x"}]}})
        for shape in shapes:
            with support.BrainEnv(with_vault=False) as env:
                path = env.claude / "settings.json"
                original = json.dumps({**shape, "model": "opus"})
                path.write_text(original)
                with self.assertRaises(st.SettingsError) as ctx:
                    st.load_settings()
                self.assertIn("nothing was changed", str(ctx.exception))
                res = subprocess.run([sys.executable, str(ROOT / "carlo"), "init", "--yes", "--vault", str(env.vault),
                                      "--modules", "memory"], capture_output=True, text=True, env=env.env(),
                                     timeout=120, stdin=subprocess.DEVNULL)
                self.assertNotEqual(res.returncode, 0)
                self.assertEqual(path.read_text(), original)

    def test_rendered_hook_command_pins_the_interpreter_and_legacy_hooks_still_uninstall(self):
        import carlo_modules as mods
        with support.BrainEnv(with_vault=False):
            rendered = mods.render("{PY} -I {CODE}/run.py", "memory")
            self.assertTrue(rendered.startswith(shlex.quote(sys.executable) + " -I "), rendered)
        legacy = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 -I /x/a.py # carlo-brain:memory"}]}]}}
        self.assertEqual(st.remove_module_hooks(legacy, "memory"), {})
        replaced = st.add_module_hooks(legacy, "memory", [{"event": "Stop", "command": rendered}])
        self.assertEqual(len(st.installed_commands(replaced, "memory")), 1)
        self.assertNotIn("python3 -I /x", json.dumps(replaced))


class EndToEndTest(unittest.TestCase):
    def init(self, env, modules="memory,security,sync"):
        return carlo(env, "init", "--yes", "--vault", str(env.vault), "--name", "Testy", "--user", "Sam", "--modules", modules)

    def test_missing_user_name_uses_neutral_wording(self):
        with support.BrainEnv(with_vault=False) as env:
            res = carlo(env, "init", "--yes", "--vault", str(env.vault), "--name", "Testy", "--modules", "none")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("Chief of Staff for the user", (env.claude / "CLAUDE.md").read_text())
            self.assertNotIn("friend", (env.claude / "CLAUDE.md").read_text())

    def test_init_ends_with_the_map_hint(self):
        with support.BrainEnv(with_vault=False) as env:
            for modules in ("none", "memory"):
                res = self.init(env, modules)
                self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
                last = res.stdout.strip().splitlines()[-1]
                self.assertEqual(last, f"Next: fill {env.vault / '00_System' / 'MAP.md'} (5 min), then run claude")

    def test_install_doctor_remove_uninstall_leaves_user_files_intact(self):
        with support.BrainEnv(with_vault=False) as env:
            settings = env.claude / "settings.json"
            settings.write_text(json.dumps(USER_SETTINGS, indent=2) + "\n")
            claude_md = env.claude / "CLAUDE.md"
            claude_md.write_text("# My own rules\n\nKeep answers short.\n")

            res = self.init(env)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("installed memory", res.stdout)

            data = json.loads(settings.read_text())
            self.assertEqual(data["model"], "opus")
            tagged = sum(len(st.installed_commands(data, m)) for m in ("memory", "security", "sync"))
            self.assertEqual(tagged, 3 + 7 + 2)
            self.assertIn("echo mine", json.dumps(data))
            text = claude_md.read_text()
            self.assertIn("Keep answers short.", text)
            self.assertIn(f"@{env.vault}/00_System/SYSTEM_PROMPT.md", text)
            self.assertNotIn("{{", text)
            prompt = (env.vault / "00_System" / "SYSTEM_PROMPT.md").read_text()
            self.assertIn("Testy", prompt)
            self.assertNotIn("{{", prompt)
            self.assertTrue(list(env.claude.glob("settings.json.bak-carlo-*")), "backup taken")
            self.assertTrue((env.brain / "memory" / "boot.py").exists())
            self.assertTrue((env.home / ".local" / "bin" / "carlo").is_symlink())

            doctor = carlo(env, "doctor")
            self.assertEqual(doctor.returncode, 0, doctor.stdout)
            self.assertIn("memory: 3/3 hooks", doctor.stdout)
            self.assertIn("audit chain", doctor.stdout)

            again = self.init(env)  # idempotent
            self.assertEqual(again.returncode, 0, again.stdout)
            self.assertEqual(json.loads(settings.read_text()), data)
            self.assertEqual(claude_md.read_text(), text)

            blocked = carlo(env, "remove", "memory")
            self.assertEqual(blocked.returncode, 1, "sync requires memory")
            self.assertIn("requires memory", blocked.stdout)
            removed = carlo(env, "remove", "sync")
            self.assertEqual(removed.returncode, 0, removed.stdout)
            self.assertEqual(st.installed_commands(json.loads(settings.read_text()), "sync"), [])
            self.assertFalse((env.brain / "sync").exists())

            res = carlo(env, "uninstall")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertEqual(json.loads(settings.read_text()), USER_SETTINGS)
            self.assertEqual(claude_md.read_text().strip(), "# My own rules\n\nKeep answers short.".strip())
            self.assertTrue((env.vault / "00_System" / "SYSTEM_PROMPT.md").exists(), "vault is never deleted")
            self.assertFalse((env.home / ".local" / "bin" / "carlo").exists())
            self.assertFalse((env.brain / "memory").exists())

    def test_fresh_machine_uninstall_removes_files_we_created(self):
        with support.BrainEnv(with_vault=False) as env:
            self.assertEqual(self.init(env, "memory").returncode, 0)
            self.assertEqual(carlo(env, "uninstall", "--purge").returncode, 0)
            self.assertFalse((env.claude / "CLAUDE.md").exists())
            self.assertEqual(json.loads((env.claude / "settings.json").read_text()), {})
            self.assertFalse(env.brain.exists())

    def test_requires_installs_dependency_first(self):
        with support.BrainEnv(with_vault=False) as env:
            self.assertEqual(self.init(env, "sync").returncode, 0)
            self.assertIn("memory", json.loads((env.brain / "config.json").read_text())["modules"])

    def test_broken_settings_aborts_init_without_changes(self):
        with support.BrainEnv(with_vault=False) as env:
            path = env.claude / "settings.json"
            path.write_text("{ broken")
            res = self.init(env)
            self.assertEqual(res.returncode, 1)
            self.assertIn("not valid JSON", res.stdout)
            self.assertEqual(path.read_text(), "{ broken")
            self.assertFalse((env.claude / "CLAUDE.md").exists())

    def test_unknown_module_and_list_and_status(self):
        with support.BrainEnv(with_vault=False) as env:
            self.assertEqual(self.init(env, "memory").returncode, 0)
            self.assertEqual(carlo(env, "add", "nope").returncode, 1)
            listing = carlo(env, "list").stdout
            self.assertRegex(listing, r"memory\s+installed")
            self.assertRegex(listing, r"security\s+available")
            self.assertIn("memory: 3 hook(s)", carlo(env, "status").stdout)

    def test_config_get_set(self):
        with support.BrainEnv(with_vault=False) as env:
            self.assertEqual(self.init(env, "none").returncode, 0)
            self.assertEqual(carlo(env, "config", "set", "memory.extract_facts", "false").returncode, 0)
            self.assertEqual(carlo(env, "config", "get", "memory.extract_facts").stdout.strip(), "false")
            self.assertEqual(carlo(env, "config", "get", "nope.nothing").returncode, 1)

    def test_doctor_flags_missing_hooks_and_loose_key_permissions(self):
        with support.BrainEnv(with_vault=False) as env:
            self.assertEqual(self.init(env, "memory").returncode, 0)
            key = env.brain / "keys" / "demo_key"
            key.write_text("value")
            key.chmod(0o644)
            out = carlo(env, "doctor").stdout
            self.assertIn("permissions too open", out)
            self.assertNotIn("value", out)
            key.chmod(0o600)
            key.write_text("")
            self.assertIn("empty", carlo(env, "doctor").stdout)
            (env.claude / "settings.json").write_text("{}")
            doctor = carlo(env, "doctor")
            self.assertEqual(doctor.returncode, 1)
            self.assertIn("0/3 hooks", doctor.stdout)


class ThirdPartyModuleTest(unittest.TestCase):
    """A module written by someone else, following only the contract, must install and uninstall cleanly."""

    def make_repo(self, root: Path, toml: str) -> Path:
        repo = root / "repo"
        shutil.copytree(ROOT / "core", repo / "core")
        shutil.copy2(ROOT / "carlo", repo / "carlo")
        module = repo / "modules" / "extra"
        (module / "src").mkdir(parents=True)
        (module / "src" / "run.py").write_text("print('hi')\n")
        (module / "module.toml").write_text(toml)
        (module / "install.sh").write_text('#!/usr/bin/env bash\necho installed > "$CARLO_BRAIN_HOME/state/extra_installed"\n')
        (module / "uninstall.sh").write_text('#!/usr/bin/env bash\necho gone > "$CARLO_BRAIN_HOME/state/extra_uninstalled"\n')
        return repo

    TOML = ('name = "extra"\nsummary = "third party"\nversion = "1.2.3"\nrequires = []\ndeps = ["python3"]\n'
            '[[hooks]]\nevent = "SessionStart"\ncommand = "{PY} -I {CODE}/run.py"\n'
            '[[launchd]]\nlabel = "nightly"\ncommand = "{PY} {CODE}/run.py"\nhour = 3\nminute = 30\n'
            '[[mcp]]\nname = "demo"\nnote = "add the demo MCP server with claude mcp add"\n')

    def run_carlo(self, repo, env, *args):
        return subprocess.run([sys.executable, str(repo / "carlo"), *args], capture_output=True, text=True,
                              env=env.env(CARLO_REPO=str(repo)), timeout=120, stdin=subprocess.DEVNULL)

    def test_full_lifecycle(self):
        with support.BrainEnv(with_vault=False) as env:
            repo = self.make_repo(env.root, self.TOML)
            res = self.run_carlo(repo, env, "init", "--yes", "--vault", str(env.vault), "--modules", "extra")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertTrue((env.brain / "state" / "extra_installed").exists())
            self.assertTrue((env.brain / "extra" / "run.py").exists())
            plist = env.home / "Library" / "LaunchAgents" / "com.carlo-brain.extra.nightly.plist"
            if sys.platform == "darwin":
                import plistlib
                data = plistlib.loads(plist.read_bytes())
                self.assertEqual(data["StartCalendarInterval"], {"Hour": 3, "Minute": 30})
                self.assertIn(str(env.brain / "extra" / "run.py"), data["ProgramArguments"][-1])
            else:
                self.assertIn("cron", res.stdout)
            self.assertIn("demo", self.run_carlo(repo, env, "status").stdout)
            self.assertEqual(self.run_carlo(repo, env, "doctor").returncode, 0)
            res = self.run_carlo(repo, env, "remove", "extra")
            self.assertEqual(res.returncode, 0, res.stdout)
            self.assertTrue((env.brain / "state" / "extra_uninstalled").exists())
            self.assertFalse(plist.exists())
            self.assertFalse((env.brain / "extra").exists())
            self.assertEqual(st.installed_commands(st.load_settings(), "extra"), [])

    def test_missing_dependency_and_wrong_platform_refuse(self):
        with support.BrainEnv(with_vault=False) as env:
            repo = self.make_repo(env.root, self.TOML.replace('deps = ["python3"]', 'deps = ["definitely-not-a-binary-xyz"]'))
            res = self.run_carlo(repo, env, "init", "--yes", "--vault", str(env.vault), "--modules", "extra")
            self.assertEqual(res.returncode, 1)
            self.assertIn("definitely-not-a-binary-xyz", res.stdout)
            self.assertEqual(st.installed_commands(st.load_settings(), "extra"), [])
            forced = self.run_carlo(repo, env, "add", "extra", "--force")
            self.assertEqual(forced.returncode, 0, forced.stdout)
        with support.BrainEnv(with_vault=False) as env:
            repo = self.make_repo(env.root, self.TOML.replace('version = "1.2.3"', 'version = "1.2.3"\nplatforms = ["windows"]'))
            res = self.run_carlo(repo, env, "init", "--yes", "--vault", str(env.vault), "--modules", "extra")
            self.assertEqual(res.returncode, 1)
            self.assertIn("supports windows only", res.stdout)

    def test_circular_requires_detected(self):
        available = {"a": mods.Module("a", "", "1", Path("."), requires=("b",)), "b": mods.Module("b", "", "1", Path("."), requires=("a",))}
        with self.assertRaises(mods.ModuleError):
            mods.resolve_install_order(["a"], available)


if __name__ == "__main__":
    unittest.main()
