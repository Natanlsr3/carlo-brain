"""Tests for the planned-setup reminder at boot and the weekly map refresh (fake HOME only)."""
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
import support  # noqa: E402

support.module_src("memory")

import boot  # noqa: E402
import refresh  # noqa: E402
import carlo_config as cfg  # noqa: E402
import carlo_mapdiff as mapdiff  # noqa: E402
import carlo_scan as scanner  # noqa: E402
import carlo_setup as setup_state  # noqa: E402

REAL_MAP = ("# MAP: Sam\n\n**Who**: Sam.\n\n**Active projects**:\n- Oldproject: the old thing.\n\n"
            "**Where to look for more**:\n- Todo: x\n")


def fake_scan(roots, mode="quick", *a, **k):
    repo = lambda n, d: {"name": n, "path": f"/w/{n}", "last_commit_days": d, "remote_host": None, "readme_head": []}  # noqa: E731
    return {"projects": [repo("freshproj", 2), repo("oldproject", 120)], "recent_folders": [], "sources": {"mail": "readable"}}


class BootReminderTest(unittest.TestCase):
    def test_reminds_on_the_planned_day_only(self):
        with support.BrainEnv() as env:
            (env.vault / "00_System" / "MAP.md").write_text(REAL_MAP)
            setup_state.plan_session("2026-11-27", "18:00", today=datetime(2026, 11, 23).date())
            same = boot.build_context({}, now=datetime(2026, 11, 27, 9, 0))
            self.assertIn("Setup session planned today", same)
            self.assertIn("say 'setup' to continue", same)
            self.assertNotIn("Setup session planned today", boot.build_context({}, now=datetime(2026, 11, 26, 9, 0)))
            self.assertNotIn("Setup session planned today", boot.build_context({}, now=datetime(2026, 11, 28, 9, 0)))

    def test_unfinished_setup_is_offered_for_resume(self):
        with support.BrainEnv() as env:
            (env.vault / "00_System" / "MAP.md").write_text(REAL_MAP)
            setup_state.save_progress("consent", done=True)
            self.assertIn("left at step 'scan'", boot.build_context({}, now=datetime(2026, 11, 27)))
            setup_state.save_progress("done", done=True)
            self.assertNotIn("left at step", boot.build_context({}, now=datetime(2026, 11, 27)))


class RefreshJobTest(unittest.TestCase):
    def setup_consent(self, env):
        (env.vault / "00_System" / "MAP.md").write_text(REAL_MAP)
        (env.home / "Desktop").mkdir(exist_ok=True)
        scanner.save_consent([env.home / "Desktop"])

    def test_writes_three_suggestions_and_never_touches_the_map(self):
        with support.BrainEnv() as env:
            self.setup_consent(env)
            before = (env.vault / "00_System" / "MAP.md").read_text()
            result = refresh.run(now=datetime(2026, 11, 23, 10), scan_fn=fake_scan)
            self.assertEqual(result, "3 suggestion(s) written")
            text = (cfg.boot_dir() / "map-refresh.md").read_text()
            self.assertIn("add project freshproj", text)
            self.assertIn("archive project Oldproject", text)
            self.assertIn("connect Mail", text)
            self.assertEqual((env.vault / "00_System" / "MAP.md").read_text(), before)
            self.assertIn("Map refresh", boot.build_context({}, now=datetime(2026, 11, 24)))
            self.assertFalse((cfg.boot_dir() / "map-refresh.md").exists())  # shown once

    def test_runs_at_most_every_six_days_and_force_overrides(self):
        with support.BrainEnv() as env:
            self.setup_consent(env)
            refresh.run(now=datetime(2026, 11, 23, 10), scan_fn=fake_scan)
            self.assertIn("less than 6 days", refresh.run(now=datetime(2026, 11, 26, 10), scan_fn=fake_scan))
            self.assertIn("written", refresh.run(now=datetime(2026, 11, 29, 10), scan_fn=fake_scan))
            self.assertIn("written", refresh.run(force=True, now=datetime(2026, 11, 29, 11), scan_fn=fake_scan))

    def test_dismissed_items_are_not_proposed_again(self):
        with support.BrainEnv() as env:
            self.setup_consent(env)
            for item in ("project:freshproj", "archive:Oldproject", "source:mail"):
                mapdiff.dismiss(item)
            self.assertEqual(refresh.run(now=datetime(2026, 11, 23, 10), scan_fn=fake_scan), "nothing to suggest")
            self.assertFalse((cfg.boot_dir() / "map-refresh.md").exists())

    def test_skips_without_consent_template_or_map(self):
        with support.BrainEnv() as env:
            self.assertIn("setup was not done", refresh.run(scan_fn=fake_scan))  # vault still has the template map
            (env.vault / "00_System" / "MAP.md").write_text(REAL_MAP)
            self.assertIn("no consent", refresh.run(scan_fn=fake_scan))
        with support.BrainEnv(with_vault=False):
            self.assertIn("no MAP.md", refresh.run(scan_fn=fake_scan))

    def test_scans_only_consented_roots(self):
        with support.BrainEnv() as env:
            self.setup_consent(env)
            seen = []

            def spy(mode, roots, *a, **k):
                seen.append((mode, [str(r) for r in roots]))
                return fake_scan(roots)

            refresh.run(now=datetime(2026, 11, 23, 10), scan_fn=spy)
            self.assertEqual(seen, [("quick", [str(env.home / "Desktop")])])

    def test_memory_module_declares_the_weekly_job(self):
        text = (ROOT / "modules" / "memory" / "module.toml").read_text()
        self.assertIn('label = "map-refresh"', text)
        self.assertIn("refresh.py run", text)


if __name__ == "__main__":
    unittest.main()
