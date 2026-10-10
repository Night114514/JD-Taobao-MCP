"""Validate the CI subprocess allowlist without starting any process."""
from pathlib import Path
import asyncio
from contextlib import ExitStack
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.ci_offline_tests import FIXTURE, OfflineGuard, validate_child


class CIOfflineTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.runtime = Path(folder.name).resolve()
        self.args = [sys.executable, "-u", str(FIXTURE), "mock",
                     str(self.runtime / "report.json")]
        self.kwargs = {"cwd": str(self.runtime), "env": {
            "BROWSER_PROFILE_DIR": str(self.runtime / "profiles"),
            "ARTIFACTS_DIR": str(self.runtime / "artifacts"),
            "PYTHON_DOTENV_DISABLED": "1",
            "ALLOW_STATE_CHANGING_ACTIONS": "false",
        }}

    def test_only_reviewed_fixture_modes_are_allowed(self):
        for mode in ("mock", "handshake"):
            self.args[3] = mode
            validate_child(self.args, self.kwargs, self.runtime)

    def test_browser_shell_and_alternative_commands_are_blocked(self):
        for args in ("python server.py", ["msedge.exe"],
                     [sys.executable, "-u", "server.py", "mock", self.args[4]],
                     self.args + ["--extra"]):
            with self.subTest(args=args), self.assertRaises(RuntimeError):
                validate_child(args, self.kwargs, self.runtime)
        for override in ({"shell": True}, {"executable": "msedge.exe"}):
            with self.subTest(override=override), self.assertRaises(RuntimeError):
                validate_child(self.args, self.kwargs | override, self.runtime)

    def test_report_and_working_directory_cannot_escape_runtime(self):
        outside = str(self.runtime / ".." / "outside")
        with self.assertRaises(RuntimeError):
            validate_child(self.args[:-1] + [outside], self.kwargs, self.runtime)
        with self.assertRaises(RuntimeError):
            validate_child(self.args, self.kwargs | {"cwd": outside}, self.runtime)

    def test_profile_and_artifacts_cannot_escape_runtime(self):
        for key in ("BROWSER_PROFILE_DIR", "ARTIFACTS_DIR"):
            env = self.kwargs["env"] | {key: str(self.runtime.parent / "real-profile")}
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                validate_child(self.args, self.kwargs | {"env": env}, self.runtime)

    def test_child_must_disable_dotenv(self):
        env = self.kwargs["env"] | {"PYTHON_DOTENV_DISABLED": "0"}
        with self.assertRaises(RuntimeError):
            validate_child(self.args, self.kwargs | {"env": env}, self.runtime)

    def test_python_injection_environment_is_blocked(self):
        for key in ("PYTHONPATH", "PYTHONHOME", "BROWSER_EXECUTABLE_PATH", "PROXY"):
            env = self.kwargs["env"] | {key: "untrusted"}
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                validate_child(self.args, self.kwargs | {"env": env}, self.runtime)

    def test_non_loopback_network_is_rejected_by_audit_callback(self):
        guard = OfflineGuard(self.runtime)
        for event, args in (
            ("socket.connect", (None, ("203.0.113.1", 443))),
            ("socket.connect", (None, ("2001:db8::1", 443, 0, 0))),
            ("socket.bind", (None, ("0.0.0.0", 0))),
            ("socket.getaddrinfo", ("example.invalid", 443, 0, 0, 0)),
            ("socket.sendto", (None, b"synthetic", ("203.0.113.1", 443))),
        ):
            with self.subTest(event=event, args=args), self.assertRaises(RuntimeError):
                guard.audit(event, args)
        self.assertEqual(len(guard.violations), 5)
        for host in ("127.0.0.1", "::1"):
            guard.audit("socket.connect", (None, (host, 0)))

    def test_audit_requires_exact_ticket_and_restores_it_after_failure(self):
        guard = OfflineGuard(self.runtime)
        command = subprocess.list2cmdline(self.args) if sys.platform == "win32" else self.args
        executable = None if sys.platform == "win32" else self.args[0]
        event_args = (executable, command, self.kwargs["cwd"], self.kwargs["env"])
        with self.assertRaises(RuntimeError):
            guard.audit("subprocess.Popen", event_args)

        def synthetic_constructor(process, args, **kwargs):
            guard.audit("subprocess.Popen", event_args)
            with self.assertRaises(RuntimeError):
                guard.audit("subprocess.Popen", ("msedge.exe", *event_args[1:]))
            raise OSError("synthetic startup failure")

        with self.assertRaisesRegex(OSError, "synthetic startup failure"):
            guard.guarded_init(synthetic_constructor)(None, self.args, **self.kwargs)
        self.assertIsNone(guard.ticket.get())
        self.assertEqual(guard.spawns, 1)

    def test_windows_asyncio_rejection_precedes_pipe_allocation_and_closes_stderr(self):
        if sys.platform != "win32":
            # The workflow targets Windows; no skip hides this regression there.
            return
        from asyncio import windows_utils
        guard = OfflineGuard(self.runtime)
        log = self.runtime / "stderr.log"

        async def rejected_start(stderr):
            with self.assertRaisesRegex(RuntimeError, "CI_SUBPROCESS_BLOCKED"):
                await asyncio.create_subprocess_exec(
                    sys.executable, "-c", "raise SystemExit(99)",
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                    **self.kwargs,
                )

        with ExitStack() as stack:
            stack.enter_context(patch.object(windows_utils.Popen, "__init__",
                                             guard.guarded_init(windows_utils.Popen.__init__)))
            pipe = stack.enter_context(patch.object(windows_utils, "pipe",
                                                    side_effect=AssertionError("PIPE_ALLOCATED")))
            with log.open("w+", encoding="utf-8") as stderr:
                asyncio.run(rejected_start(stderr))
            pipe.assert_not_called()
        log.unlink()  # WinError 32 here would expose a leaked handle.
        self.assertFalse(log.exists())
