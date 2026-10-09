from __future__ import annotations

import json
import os
from contextlib import contextmanager
import time
from pathlib import Path
from urllib.parse import urlparse

from .safety import SafetyError


def is_taobao_auth_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()

    return host in {
        "login.taobao.com",
        "login.tmall.com",
        "passport.taobao.com",
        "passport.tmall.com",
    } or (
        host.endswith(".taobao.com")
        and path.startswith(("/member/login", "/login"))
    )


class TaobaoNavigationGuard:
    def __init__(
        self,
        state_path: Path,
        min_interval_seconds: float = 30.0,
        max_per_hour: int = 10,
    ) -> None:
        self.state_path = Path(state_path)
        self.min_interval_seconds = min_interval_seconds
        self.max_per_hour = max_per_hour

    @contextmanager
    def _locked_state(self):
        # Separate lock file: atomic JSON replacement must not replace
        # the file whose byte range is locked.
        lock_path = self.state_path.with_name(
            self.state_path.name + ".lock"
        )

        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = lock_path.open("a+b")
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(bytes([0]))
                handle.flush()
        except OSError as exc:
            raise SafetyError(
                "Cannot initialize Taobao state lock."
            ) from exc

        acquired = False

        try:
            deadline = time.monotonic() + 5.0

            while not acquired:
                try:
                    handle.seek(0)

                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(
                            handle.fileno(),
                            msvcrt.LK_NBLCK,
                            1,
                        )
                    else:
                        import fcntl
                        fcntl.flock(
                            handle.fileno(),
                            fcntl.LOCK_EX | fcntl.LOCK_NB,
                        )

                    acquired = True

                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise SafetyError(
                            "Taobao state lock unavailable; "
                            "operation refused."
                        ) from exc

                    time.sleep(0.05)

            yield

        finally:
            try:
                if acquired:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(
                            handle.fileno(),
                            msvcrt.LK_UNLCK,
                            1,
                        )
                    else:
                        import fcntl
                        fcntl.flock(
                            handle.fileno(),
                            fcntl.LOCK_UN,
                        )
            finally:
                handle.close()

    def _load(self) -> dict:
        try:
            data = json.loads(
                self.state_path.read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return {"paused": False, "navigation_times": []}
        except (OSError, ValueError) as exc:
            raise SafetyError(
                "Taobao safety state cannot be read. "
                "Automation remains blocked."
            ) from exc

        if not isinstance(data, dict):
            raise SafetyError("Invalid Taobao safety state.")

        return data

    def _save(self, data: dict) -> None:
        self.state_path.parent.mkdir(
            parents=True, exist_ok=True
        )
        tmp = self.state_path.with_name(
            self.state_path.name + ".tmp"
        )
        tmp.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.state_path)

    def is_paused(self) -> bool:
        return bool(self._load().get("paused", False))

    def reserve_navigation(
        self, now: float | None = None
    ) -> None:
        with self._locked_state():
            now = time.time() if now is None else now
            data = self._load()

            if data.get("paused"):
                raise SafetyError(
                    "Taobao automation is paused after login "
                    "or security verification. Manual recovery is required."
                )

            stored = data.get("navigation_times", [])
            if not isinstance(stored, list):
                raise SafetyError("Invalid navigation history.")

            recent = [
                float(t)
                for t in stored
                if isinstance(t, (int, float))
                and not isinstance(t, bool)
                and float(t) > now - 3600
            ]

            if recent and now - max(recent) < self.min_interval_seconds:
                raise SafetyError(
                    "Taobao navigation cooldown active. "
                    "Do not retry automatically."
                )

            if len(recent) >= self.max_per_hour:
                raise SafetyError(
                    "Taobao hourly navigation limit reached. "
                    "Do not retry automatically."
                )

            data["navigation_times"] = recent + [now]
            self._save(data)

    def pause(self, reason: str = "verification_required") -> None:
        with self._locked_state():
            data = self._load()
            data["paused"] = True
            data["pause_reason"] = reason
            self._save(data)

    def resume_after_manual_verification(self) -> None:
        with self._locked_state():
            # Only invoked by the local interactive administrator CLI.
            # Navigation history is deliberately preserved.
            data = self._load()
            if not data.get("paused", False):
                return

            data["paused"] = False
            data.pop("pause_reason", None)
            self._save(data)
