import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from jd_taobao_mcp.browser import BrowserController
from jd_taobao_mcp.config import Settings
from jd_taobao_mcp.safety import SafetyError
from jd_taobao_mcp.taobao_guard import TaobaoNavigationGuard


TAOBAO_URL = "https://item.taobao.com/item.htm?id=123456"
JD_URL = "https://item.jd.com/123456.html"


class NavigationFailClosedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        self.settings = replace(
            Settings.from_env(),
            profile_dir=Path(temp.name) / "profile",
        )

        self.page = Mock()
        self.page.url = "about:blank"

        body = Mock()
        body.count = AsyncMock(return_value=1)
        body.inner_text = AsyncMock(
            return_value="Normal product page"
        )
        self.body = body
        self.page.locator.return_value = body

        async def fake_goto(url, **kwargs):
            self.page.url = url
            return SimpleNamespace(status=200)

        self.page.goto = AsyncMock(side_effect=fake_goto)

        self.controller = BrowserController(
            self.settings,
            taobao_safe_mode=True,
        )
        self.controller._active_page_unlocked = AsyncMock(
            return_value=self.page
        )
        self.controller._settle = AsyncMock()
        self.controller._navigation_result = AsyncMock(
            return_value={
                "success": True,
                "url": TAOBAO_URL,
                "requires_user_verification": False,
            }
        )

    def assert_persistently_paused(self):
        guard = self.controller._taobao_guard
        self.assertTrue(guard.is_paused())

        restarted = TaobaoNavigationGuard(guard.state_path)
        self.assertTrue(restarted.is_paused())

    async def test_taobao_timeout_pauses(self):
        self.page.goto.side_effect = PlaywrightTimeoutError(
            "Simulated timeout"
        )

        with self.assertRaises(SafetyError):
            await self.controller.navigate(TAOBAO_URL)

        self.assert_persistently_paused()

    async def test_missing_dom_pauses(self):
        self.body.count.return_value = 0

        with self.assertRaises(SafetyError):
            await self.controller.navigate(TAOBAO_URL)

        self.controller._navigation_result.assert_not_awaited()
        self.assert_persistently_paused()

    async def test_navigation_result_error_pauses(self):
        self.controller._navigation_result.side_effect = RuntimeError(
            "Simulated extraction failure"
        )

        with self.assertRaises(RuntimeError):
            await self.controller.navigate(TAOBAO_URL)

        self.assert_persistently_paused()

    async def test_cancelled_navigation_pauses(self):
        self.page.goto.side_effect = asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await self.controller.navigate(TAOBAO_URL)

        self.assert_persistently_paused()

    async def test_pre_navigation_inspection_error_pauses(self):
        self.page.url = TAOBAO_URL
        self.body.count.side_effect = RuntimeError(
            "Simulated inspection failure"
        )

        with self.assertRaises(SafetyError):
            await self.controller.navigate(TAOBAO_URL)

        self.page.goto.assert_not_awaited()
        self.assert_persistently_paused()

    async def test_unsuccessful_result_pauses(self):
        self.controller._navigation_result.return_value = {
            "success": False,
            "requires_user_verification": False,
        }

        with self.assertRaises(SafetyError):
            await self.controller.navigate(TAOBAO_URL)

        self.assert_persistently_paused()

    async def test_settle_error_pauses(self):
        self.controller._settle.side_effect = RuntimeError(
            "Simulated page settling failure"
        )

        with self.assertRaises(RuntimeError):
            await self.controller.navigate(TAOBAO_URL)

        self.assert_persistently_paused()

    async def test_jd_timeout_behavior_unchanged(self):
        jd = BrowserController(
            self.settings,
            taobao_safe_mode=False,
        )

        jd._active_page_unlocked = AsyncMock(
            return_value=self.page
        )
        jd._settle = AsyncMock()
        jd._navigation_result = AsyncMock(
            return_value={
                "success": True,
                "url": JD_URL,
                "requires_user_verification": False,
            }
        )

        async def jd_timeout_after_navigation(url, **kwargs):
            self.page.url = url
            raise PlaywrightTimeoutError("Simulated JD timeout")

        self.page.goto.side_effect = jd_timeout_after_navigation

        result = await jd.navigate(JD_URL)

        self.assertTrue(result["success"])
        jd._navigation_result.assert_awaited_once()
        self.assertIsNone(jd._taobao_guard)


if __name__ == "__main__":
    unittest.main()
