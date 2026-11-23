"""`carlo connect browser` and its doctor row, with fake `claude` and `npx` executables on PATH."""
import io
import os
import shutil
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import support  # noqa: E402

import carlo_cli  # noqa: E402

FAKE = """#!/bin/sh
echo "$@" >> "$FAKE_LOG"
if [ "$1" = "mcp" ] && [ "$2" = "get" ]; then [ -f "$FAKE_STATE" ]; exit $?; fi
if [ "$1" = "mcp" ] && [ "$2" = "add" ]; then touch "$FAKE_STATE"; fi
if [ "$1" = "mcp" ] && [ "$2" = "remove" ]; then rm -f "$FAKE_STATE"; fi
exit 0
"""


class ConnectBrowserCliTest(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = carlo_cli.main(list(argv))
        return code, out.getvalue()

    def test_connect_doctor_and_remove(self):
        with support.BrainEnv() as env:
            bin_dir = env.root / "bin"
            bin_dir.mkdir()
            for name in ("claude", "npx"):
                (bin_dir / name).write_text(FAKE)
                (bin_dir / name).chmod(0o755)
            saved = {k: os.environ.get(k) for k in ("PATH", "FAKE_LOG", "FAKE_STATE")}
            os.environ.update(PATH=f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin", FAKE_LOG=str(env.root / "log"),
                              FAKE_STATE=str(env.root / "registered"))
            try:
                code, out = self.run_cli("connect", "browser")
                self.assertEqual(code, 1, "connectors module not installed yet")
                self.assertIn("carlo add connectors", out)
                shutil.copytree(ROOT / "modules" / "connectors" / "src", env.brain / "connectors")
                code, out = self.run_cli("connect", "browser")
                self.assertEqual(code, 0, out)
                self.assertIn("registered playwright", out)
                self.assertEqual(self.run_cli("connect", "browser")[1].strip(), "[ok]   already registered")
                log = (env.root / "log").read_text()
                self.assertEqual(log.count("mcp add playwright -s user -- npx @playwright/mcp@latest"), 1)
                self.assertIn("browser: playwright MCP server registered", "\n".join(t for _, t in carlo_cli.check_browser()))
                (env.root / "registered").unlink()
                self.assertTrue(any(level == carlo_cli.WARN for level, _ in carlo_cli.check_browser()))
                self.run_cli("connect", "browser")
                code, out = self.run_cli("connect", "browser", "--remove")
                self.assertEqual((code, "removed" in out), (0, True))
                self.assertEqual(carlo_cli.check_browser(), [], "silent once removed")
            finally:
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
