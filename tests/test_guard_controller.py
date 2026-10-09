import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from jd_taobao_mcp.browser import BrowserController
from jd_taobao_mcp.config import Settings
from jd_taobao_mcp.safety import SafetyError
from jd_taobao_mcp.taobao_guard import TaobaoNavigationGuard


PRODUCT_URL = "https://item.taobao.com/item.htm?id=123456"
LOGIN_URL = "https://login.taobao.com/member/login.jhtml"


class BrowserGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.settings = replace(
            Settings.from_env(),
            profile_dir=Path(self.temp.name) / "taobao",
        )
        self.browser = BrowserController(
            self.settings, taobao_safe_mode=True
        )

        self.page = Mock()
        self.page.url = "about:blank"
        self.page.title = AsyncMock(return_value="Test page")
        self.page.evaluate = AsyncMock(
            return_value={"x": 0, "y": 900, "height": 1500}
        )
        self.page.mouse.wheel = AsyncMock()

        body = Mock()
        body.count = AsyncMock(return_value=1)
        body.inner_text = AsyncMock(
            return_value="Normal product page"
        )
        self.page.locator.return_value = body

        async def fake_goto(url, **kwargs):
            self.page.url = url
            return SimpleNamespace(status=200)

        self.page.goto = AsyncMock(side_effect=fake_goto)

        self.browser._active_page_unlocked = AsyncMock(
            return_value=self.page
        )
        self.browser._settle = AsyncMock()
        self.browser._navigation_result = AsyncMock(
            return_value={
                "success": True,
                "url": PRODUCT_URL,
                "requires_user_verification": False,
            }
        )

    async def test_navigation_cooldown_blocks_second_call(self):
        result = await self.browser.navigate(PRODUCT_URL)
        self.assertTrue(result["success"])

        with self.assertRaises(SafetyError):
            await self.browser.navigate(PRODUCT_URL)

        self.assertEqual(self.page.goto.await_count, 1)

    async def test_verification_redirect_persists_pause(self):
        self.browser._navigation_result.return_value = {
            "success": True,
            "url": LOGIN_URL,
            "requires_user_verification": True,
        }

        result = await self.browser.navigate(PRODUCT_URL)

        self.assertTrue(result["automation_paused"])
        self.assertTrue(self.browser._taobao_guard.is_paused())

        restarted_guard = TaobaoNavigationGuard(
            self.browser._taobao_guard.state_path
        )
        self.assertTrue(restarted_guard.is_paused())

        with self.assertRaises(SafetyError):
            await self.browser.navigate(PRODUCT_URL)

        self.assertEqual(self.page.goto.await_count, 1)

    async def test_existing_login_page_blocks_navigation(self):
        self.page.url = LOGIN_URL

        with self.assertRaises(SafetyError):
            await self.browser.navigate(PRODUCT_URL)

        self.page.goto.assert_not_awaited()
        self.assertTrue(self.browser._taobao_guard.is_paused())

    async def test_interactive_tools_are_blocked(self):
        actions = (
            self.browser.click("e1"),
            self.browser.type_text("e1", "hello"),
            self.browser.scroll("down", 900),
            self.browser.go_back(),
        )

        for action in actions:
            with self.assertRaises(SafetyError):
                await action

        self.page.mouse.wheel.assert_not_awaited()
        self.page.goto.assert_not_awaited()

    async def test_check_login_does_not_navigate(self):
        result = await self.browser.check_login("taobao")

        self.assertEqual(result["platform"], "taobao")
        self.page.goto.assert_not_awaited()

    async def test_jd_scrolling_remains_available(self):
        jd = BrowserController(
            self.settings, taobao_safe_mode=False
        )
        jd._active_page_unlocked = AsyncMock(
            return_value=self.page
        )
        jd._settle = AsyncMock()

        result = await jd.scroll("down", 900)

        self.assertTrue(result["success"])
        self.page.mouse.wheel.assert_awaited_once_with(0, 900)

class ManualRecoveryTests(unittest.TestCase):
    def test_manual_resume_preserves_navigation_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / "state.json"
            guard = TaobaoNavigationGuard(state)
            guard.reserve_navigation(now=1000)
            guard.pause()

            self.assertTrue(guard.is_paused())
            guard.resume_after_manual_verification()
            self.assertFalse(guard.is_paused())

            with self.assertRaises(SafetyError):
                guard.reserve_navigation(now=1001)


if __name__ == "__main__":
    unittest.main()
