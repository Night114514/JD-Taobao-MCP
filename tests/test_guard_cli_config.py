"""Only temporary .env/state fixtures; never invoke the resume command."""
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class GuardCLIConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        (self.root / "scripts").mkdir()
        shutil.copyfile(ROOT / "server.py", self.root / "server.py")
        shutil.copyfile(ROOT / "scripts/taobao_guard_admin.py", self.root / "scripts/taobao_guard_admin.py")
        self.old_cwd = Path.cwd()
        self.old_path = list(sys.path)
        self.addCleanup(os.chdir, self.old_cwd)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), self.old_path))
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ}
        env.update({"HOME": str(self.root / "home"), "USERPROFILE": str(self.root / "home")})
        replacement = patch.dict(os.environ, env, clear=True)
        replacement.start()
        self.addCleanup(replacement.stop)
        # A sentinel ensures even an accidental test change cannot call resume.
        forbidden = patch("jd_taobao_mcp.taobao_guard.TaobaoNavigationGuard.resume_after_manual_verification",
                          side_effect=AssertionError("RESUME_FORBIDDEN"))
        forbidden.start()
        self.addCleanup(forbidden.stop)

    def load_server(self):
        with patch("playwright.async_api.async_playwright", side_effect=AssertionError("NO_BROWSER")):
            return runpy.run_path(str(self.root / "server.py"), run_name="config_fixture")["settings"]

    def cli_status(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["taobao_guard_admin.py", "status"]), redirect_stdout(output):
            namespace = runpy.run_path(str(self.root / "scripts/taobao_guard_admin.py"))
            self.assertEqual(namespace["main"](), 0)
        return output.getvalue()

    def test_cli_and_server_resolve_dotenv_profile_identically_without_mutation(self):
        (self.root / ".env").write_text(
            "BROWSER_PROFILE_DIR=.tmp/configured\nARTIFACTS_DIR=.tmp/artifacts\nFIXTURE_PRIVATE_VALUE=synthetic-only\n",
            encoding="utf-8",
        )
        state = self.root / ".tmp/configured/taobao/taobao-safety-state.json"
        state.parent.mkdir(parents=True)
        state.write_text('{"paused":true,"navigation_times":[1000]}', encoding="utf-8")
        before = state.read_bytes()
        # CLI runs first so it cannot inherit dotenv values loaded by server.
        output = self.cli_status()
        self.assertIn("paused: True", output)
        self.assertIn(str(state), output)
        self.assertNotIn("synthetic-only", output)
        settings = self.load_server()
        self.assertEqual(settings.profile_dir, self.root / ".tmp/configured")
        self.assertEqual(settings.artifacts_dir, self.root / ".tmp/artifacts")
        self.assertEqual(state.read_bytes(), before)

    def test_explicit_environment_wins_and_cli_does_not_change_cwd(self):
        (self.root / ".env").write_text("BROWSER_PROFILE_DIR=ignored-profile\n", encoding="utf-8")
        os.environ["BROWSER_PROFILE_DIR"] = "explicit-profile"
        elsewhere = self.root / "caller"
        elsewhere.mkdir()
        os.chdir(elsewhere)
        output = self.cli_status()
        self.assertEqual(Path.cwd(), elsewhere)
        expected = self.root / "explicit-profile"
        self.assertIn(str(expected / "taobao/taobao-safety-state.json"), output)
        self.assertEqual(self.load_server().profile_dir, expected)
        self.assertFalse(expected.exists())

    def test_no_dotenv_uses_same_defaults_without_creating_profile(self):
        output = self.cli_status()
        settings = self.load_server()
        self.assertIn(str(settings.profile_dir / "taobao/taobao-safety-state.json"), output)
        self.assertFalse(settings.profile_dir.exists())


if __name__ == "__main__":
    unittest.main()
