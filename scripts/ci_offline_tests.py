"""Run unittest with temporary settings and fail-closed offline I/O guards.

This is an accidental-I/O guard for our tests, not an OS security sandbox.
Only the reviewed stdio fixture may start a child; it installs its own guards.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from contextvars import ContextVar
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "stdio_fixture_server.py"
LOOPBACK = {"127.0.0.1", "::1"}


def validate_child(args, kwargs, runtime: Path) -> None:
    """Allow only the known Python stdio fixture, with isolated paths."""
    if not isinstance(args, (list, tuple)) or len(args) != 5:
        raise RuntimeError("CI_SUBPROCESS_BLOCKED")
    executable, flag, script, mode, report = args
    if (Path(executable).resolve() != Path(sys.executable).resolve()
            or flag != "-u" or Path(script).resolve() != FIXTURE
            or mode not in {"mock", "handshake"} or kwargs.get("shell")
            or kwargs.get("executable") is not None):
        raise RuntimeError("CI_SUBPROCESS_BLOCKED")
    env = kwargs.get("env") or {}
    paths = [report, kwargs.get("cwd"), env.get("BROWSER_PROFILE_DIR"),
             env.get("ARTIFACTS_DIR")]
    if any(not value or not Path(value).resolve().is_relative_to(runtime)
           for value in paths):
        raise RuntimeError("CI_CHILD_PATH_BLOCKED")
    if env.get("PYTHON_DOTENV_DISABLED") != "1":
        raise RuntimeError("CI_CHILD_DOTENV_BLOCKED")
    allowed_env = {
        "SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC", "PATHEXT",
        "PYTHONUTF8", "PYTHON_DOTENV_DISABLED", "BROWSER_PROFILE_DIR",
        "ARTIFACTS_DIR", "TAOBAO_SEARCH_MODE", "ALLOW_STATE_CHANGING_ACTIONS",
    }
    if set(env) - allowed_env or env.get("ALLOW_STATE_CHANGING_ACTIONS") != "false":
        raise RuntimeError("CI_CHILD_ENV_BLOCKED")
    for name in ("TEMP", "TMP"):
        if name in env and not Path(env[name]).resolve().is_relative_to(runtime):
            raise RuntimeError("CI_CHILD_PATH_BLOCKED")


class OfflineGuard:
    def __init__(self, runtime: Path):
        self.runtime = runtime
        self.violations = []
        self.spawns = 0
        self.ticket = ContextVar("ci_spawn_ticket", default=None)

    def guarded_init(self, original):
        def initialize(process, args, *positional, **kwargs):
            if positional:
                raise RuntimeError("CI_SUBPROCESS_BLOCKED")
            # Validate before Windows allocates overlapped pipe handles, and
            # again at the shared base constructor. Both paths use one policy.
            validate_child(args, kwargs, self.runtime)
            command = subprocess.list2cmdline(args) if sys.platform == "win32" else list(args)
            # Windows leaves executable=None and resolves the already-validated
            # absolute argv[0] from list2cmdline; POSIX reports argv[0].
            executable = None if sys.platform == "win32" else str(args[0])
            token = self.ticket.set((executable, command, os.fsdecode(kwargs["cwd"]),
                                     dict(kwargs["env"])))
            try:
                return original(process, args, **kwargs)
            finally:
                self.ticket.reset(token)
        return initialize

    def audit(self, event, args):
        blocked = event in {"os.system", "os.posix_spawn", "os.exec", "os.spawn"}
        if event == "subprocess.Popen":
            # A narrow, context-local ticket is bound to the exact audited
            # executable, command, cwd and environment, never a global bypass.
            blocked = self.ticket.get() is None or tuple(args) != self.ticket.get()
            if not blocked:
                self.spawns += 1
        elif event in {"socket.connect", "socket.bind"}:
            address = args[1]
            blocked = not isinstance(address, tuple) or address[0] not in LOOPBACK
        elif event == "socket.getaddrinfo":
            blocked = args[0] not in LOOPBACK
        elif event in {"socket.sendto", "socket.sendmsg"}:
            # No UDP traffic is needed for unittest or MCP pipes.
            blocked = True
        if blocked:
            self.violations.append(event)
            raise RuntimeError(f"CI_OFFLINE_IO_BLOCKED: {event}")

    def install(self, stack):
        stack.enter_context(patch.object(subprocess.Popen, "__init__",
                                         self.guarded_init(subprocess.Popen.__init__)))
        if sys.platform == "win32":
            from asyncio import windows_utils
            stack.enter_context(patch.object(windows_utils.Popen, "__init__",
                                             self.guarded_init(windows_utils.Popen.__init__)))
        sys.addaudithook(self.audit)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--stdio-only", action="store_true")
    selection.add_argument("--safety-only", action="store_true")
    options = parser.parse_args()
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    # Never open a checkout's real .env, even with older python-dotenv versions.
    if (ROOT / ".env").exists():
        raise RuntimeError("CI refuses a checkout containing .env")
    with tempfile.TemporaryDirectory(prefix="jd-taobao-ci-") as folder, ExitStack() as stack:
        runtime = Path(folder).resolve()
        guard = OfflineGuard(runtime)
        env = {key: os.environ[key] for key in (
            "SYSTEMROOT", "WINDIR", "PATH", "COMSPEC", "PATHEXT",
        ) if key in os.environ}
        env.update({
            "TEMP": str(runtime), "TMP": str(runtime),
            "PYTHONUTF8": "1", "PYTHON_DOTENV_DISABLED": "1",
            "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
            "PLAYWRIGHT_BROWSERS_PATH": str(runtime / "no-browsers"),
            "BROWSER_PROFILE_DIR": str(runtime / "profiles"),
            "ARTIFACTS_DIR": str(runtime / "artifacts"),
            "ALLOW_STATE_CHANGING_ACTIONS": "false",
        })
        stack.enter_context(patch.dict(os.environ, env, clear=True))
        stack.enter_context(patch.object(tempfile, "tempdir", str(runtime)))

        import dotenv
        original_dotenv = dotenv.load_dotenv

        def temporary_dotenv(dotenv_path=None, *args, **kwargs):
            if dotenv_path is None or not Path(dotenv_path).resolve().is_relative_to(runtime):
                return False
            # CLI regression tests clear the environment themselves and load
            # synthetic .env files. Keep this coverage; never read a real file.
            return original_dotenv(dotenv_path, *args, **kwargs)

        def no_browser(*args, **kwargs):
            guard.violations.append("playwright")
            raise RuntimeError("CI_BROWSER_BLOCKED")

        stack.enter_context(patch("dotenv.load_dotenv", temporary_dotenv))
        stack.enter_context(patch("playwright.async_api.async_playwright", no_browser))
        stack.enter_context(patch("playwright.sync_api.sync_playwright", no_browser))
        guard.install(stack)
        pattern = ("test_ci_offline.py" if options.safety_only else
                   "test_mcp_stdio.py" if options.stdio_only else "test*.py")
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern)
        count = suite.countTestCases()
        if count == 0 or (options.stdio_only and count != 4):
            raise RuntimeError(f"Unexpected test count: {count}")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        print(f"CI offline: tests={result.testsRun}, failures={len(result.failures)}, "
              f"errors={len(result.errors)}, skipped={len(result.skipped)}, "
              f"unexpected_io={len(guard.violations)}, audited_spawns={guard.spawns}", flush=True)
        if not options.safety_only and guard.spawns != 4:
            print("Expected exactly four audited Mock stdio child processes", file=sys.stderr)
            return 1
        return 0 if result.wasSuccessful() and not result.skipped and not guard.violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
