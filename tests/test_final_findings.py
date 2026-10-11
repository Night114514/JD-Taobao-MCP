"""Offline tests for missing DOM and independent cleanup; no browser starts."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import server
import test_cross_platform_guard as fixtures
from test_detail_navigation import make_page, BODY
from jd_taobao_mcp.extractors.detail import extract_product_detail
from jd_taobao_mcp.safety import SafetyError
from jd_taobao_mcp.taobao_guard import TaobaoNavigationGuard


class MissingBodyTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    async def check(self, source, missing, blocked):
        browser = self.service.taobao_browser
        browser._context = self.jd._context
        browser._page = self.page
        browser._start_unlocked = AsyncMock()
        self.page.url = source
        self.locator.count.return_value = 0 if missing else 1
        if source == "about:blank":
            async def load_product(url, **kwargs):
                self.page.url = url
                self.locator.count.return_value = 1
                return SimpleNamespace(status=200)
            self.page.goto.side_effect = load_product
        guard = browser._taobao_guard
        with patch.object(guard, "reserve_navigation", wraps=guard.reserve_navigation) as reserve:
            if blocked:
                with self.assertRaises(SafetyError):
                    await browser.navigate(fixtures.TAOBAO)
                reserve.assert_not_called()
                self.page.goto.assert_not_awaited()
                self.page.go_back.assert_not_awaited()
                self.assertTrue(TaobaoNavigationGuard(guard.state_path).is_paused())
            else:
                self.assertTrue((await browser.navigate(fixtures.TAOBAO))["success"])
                reserve.assert_called_once()
                self.page.goto.assert_awaited_once()
                self.assertFalse(guard.is_paused())

    async def test_missing_http_body_pauses_before_quota(self):
        await self.check(fixtures.TAOBAO, True, True)

    async def test_normal_body_control(self):
        await self.check(fixtures.TAOBAO, False, False)

    async def test_blank_without_body_control(self):
        await self.check("about:blank", True, False)
