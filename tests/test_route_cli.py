"""`carlo route` and its doctor rows, in a fake HOME with the connectors module copied in."""
import io
import json
import shutil
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import support  # noqa: E402

import carlo_cli  # noqa: E402

AGENT = '---\nname: researcher\ndescription: "x"\nmodel: sonnet\n---\nBody\n'


class RouteCliTest(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = carlo_cli.main(list(argv))
        return code, out.getvalue()

    def test_route_sync_status_undo_and_doctor(self):
        with support.BrainEnv() as env:
            code, out = self.run_cli("route", "status")
            self.assertEqual(code, 1)
            self.assertIn("carlo add connectors", out)
            shutil.copytree(ROOT / "modules" / "connectors" / "src", env.brain / "connectors")
            self.assertEqual(carlo_cli.check_routing(), [])
            (env.claude / "agents").mkdir()
            agent = env.claude / "agents" / "researcher.md"
            agent.write_text(AGENT)
            (env.brain / "config.d").mkdir()
            (env.brain / "config.d" / "routing.json").write_text(json.dumps(
                {"agents": {"researcher": "claude:haiku", "bulk": "openrouter:v/m"}}))
            self.assertIn("NOT synced", self.run_cli("route", "status")[1])
            self.assertTrue(any(level == carlo_cli.WARN for level, _ in carlo_cli.check_routing()))
            code, out = self.run_cli("route", "sync")
            self.assertEqual(code, 0, out)
            self.assertIn("model: haiku", agent.read_text())
            self.assertTrue((env.claude / "agents" / "bulk-routed.md").exists())
            self.assertEqual([level for level, _ in carlo_cli.check_routing()], [carlo_cli.OK])
            code, out = self.run_cli("route", "sync", "--undo")
            self.assertEqual(code, 0, out)
            self.assertEqual(agent.read_text(), AGENT)
            self.assertFalse((env.claude / "agents" / "bulk-routed.md").exists())


if __name__ == "__main__":
    unittest.main()
