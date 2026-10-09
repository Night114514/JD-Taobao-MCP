from __future__ import annotations

import json
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
        data = self._load()
        data["paused"] = True
        data["pause_reason"] = reason
        self._save(data)

    def resume_after_manual_verification(self) -> None:
        # Only invoked by the local interactive administrator CLI.
        # Navigation history is deliberately preserved.
        data = self._load()
        if not data.get("paused", False):
            return

        data["paused"] = False
        data.pop("pause_reason", None)
        self._save(data)
