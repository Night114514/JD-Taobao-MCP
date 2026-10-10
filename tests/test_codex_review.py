"""Offline regressions for the seven Codex inline review findings."""
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_cross_platform_guard as platforms
import test_current_page_verification as current
from test_detail_navigation import make_page, BODY
from jd_taobao_mcp.extractors.detail import extract_product_detail, _fallback_reviews_from_text
from jd_taobao_mcp.safety import SafetyError
from jd_taobao_mcp.taobao_guard import TaobaoNavigationGuard


class NavigationInspectionTests(unittest.IsolatedAsyncioTestCase):
    setUp = platforms.CrossPlatformGuardTests.setUp

    async def check_transition(self, target):
        browser = self.service.taobao_browser
        browser._context = self.jd._context
        browser._page = self.page
        browser._start_unlocked = AsyncMock()
        self.page.url = platforms.TAOBAO
        guard = browser._taobao_guard
        async def text(**kwargs):
            self.page.url = target
            return "Product"
        self.locator.inner_text.side_effect = text
        with patch.object(guard, "reserve_navigation", wraps=guard.reserve_navigation) as reserve:
            if target == platforms.TAOBAO:
                self.assertTrue((await browser.navigate(platforms.TAOBAO))["success"])
                reserve.assert_called_once()
                self.page.goto.assert_awaited_once()
                self.assertFalse(guard.is_paused())
            else:
                with self.assertRaises(SafetyError):
                    await browser.navigate(platforms.TAOBAO)
                reserve.assert_not_called()
                self.page.goto.assert_not_awaited()
                self.assertTrue(TaobaoNavigationGuard(guard.state_path).is_paused())
                self.page.go_back.assert_not_awaited()

    async def test_p1_login_during_dom_read(self):
        await self.check_transition("https://login.taobao.com/member/login.jhtml")

    async def test_p1_verification_during_dom_read(self):
        await self.check_transition("https://item.taobao.com/captcha")

    async def test_p1_jd_during_dom_read(self):
        await self.check_transition(platforms.JD)

    async def test_p1_normal_control(self):
        await self.check_transition(platforms.TAOBAO)
