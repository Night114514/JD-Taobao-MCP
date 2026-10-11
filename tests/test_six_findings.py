"""Offline review regressions: synthetic pages, cookie names and temporary state only."""
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import server
import test_cross_platform_guard as fixtures
from test_detail_navigation import make_page
from jd_taobao_mcp.extractors.detail import extract_product_detail
from jd_taobao_mcp.service import _canonical_detail_url
from jd_taobao_mcp.safety import SafetyError
from jd_taobao_mcp.taobao_guard import TaobaoNavigationGuard

LOGIN = "https://login.taobao.com/member/login.jhtml"
VERIFY = "https://item.taobao.com/captcha"
TEXT = "参数信息 品牌 Example 型号 K1 额定功率 100W 图文详情"


class PostNavigationInspectionTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    async def check_failure(self, operation, target):
        browser = self.service.taobao_browser
        browser.get_page = AsyncMock(return_value=self.page)
        browser.navigate = AsyncMock(return_value={"success": True})
        self.page.url = fixtures.TAOBAO
        error = RuntimeError("synthetic document reloaded")

        async def fail(*args, **kwargs):
            self.page.url = target
            raise error

        getattr(self.locator, operation).side_effect = fail
        guard = browser._taobao_guard
        with patch.object(guard, "reserve_navigation") as reserve, patch(
            "jd_taobao_mcp.service.extract_product_detail", new_callable=AsyncMock
        ) as extract:
            with self.assertRaises(RuntimeError) as caught:
                await self.service.get_product_detail(fixtures.TAOBAO)
            self.assertIs(caught.exception, error)
            extract.assert_not_awaited()
            browser.navigate.assert_awaited_once()
            reserve.assert_not_called()
            self.assertTrue(TaobaoNavigationGuard(guard.state_path).is_paused())

    async def test_count_reload_pauses(self):
        await self.check_failure("count", fixtures.TAOBAO)

    async def test_count_login_redirect_pauses(self):
        await self.check_failure("count", LOGIN)

    async def test_text_verification_redirect_pauses(self):
        await self.check_failure("inner_text", VERIFY)

    async def test_text_reload_pauses(self):
        await self.check_failure("inner_text", fixtures.TAOBAO)
