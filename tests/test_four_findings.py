"""Offline snapshot/search/price/JD verification regressions; temporary state only."""
import unittest
from unittest.mock import AsyncMock, patch

import server
import test_cross_platform_guard as fixtures
from test_detail_navigation import make_page
from jd_taobao_mcp.extractors.detail import extract_product_detail
from jd_taobao_mcp.safety import SafetyError
from jd_taobao_mcp.taobao_guard import TaobaoNavigationGuard

LOGIN = "https://login.taobao.com/member/login.jhtml"


class SnapshotPauseTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    async def check(self, url, text="Product", paused=False, redirect=None, error=False, jd=False):
        browser = self.jd if jd else self.service.taobao_browser
        browser._context = self.jd._context
        browser._page = self.page
        browser._start_unlocked = AsyncMock()
        self.service.browser = browser
        self.page.url = url
        failure = RuntimeError("synthetic snapshot document reload")

        async def evaluate(*args):
            if redirect:
                self.page.url = redirect
            if error:
                raise failure
            return {"url": self.page.url, "text": text, "title": "Synthetic", "links": [], "forms": []}

        self.page.evaluate.side_effect = evaluate
        guard = self.service.taobao_browser._taobao_guard
        with patch.object(guard, "reserve_navigation") as reserve, patch.object(server, "service", self.service):
            if error:
                with self.assertRaises(RuntimeError) as caught:
                    await server.page_snapshot()
                self.assertIs(caught.exception, failure)
            else:
                result = await server.page_snapshot()
                self.assertEqual(result["requires_user_verification"], paused)
            self.assertEqual(TaobaoNavigationGuard(guard.state_path).is_paused(), paused)
            reserve.assert_not_called()
            self.page.goto.assert_not_awaited()
            self.page.evaluate.assert_awaited_once()

    async def test_restored_login_without_keywords(self):
        await self.check(LOGIN, paused=True)

    async def test_manual_verification_page(self):
        await self.check(fixtures.TAOBAO, text="安全验证", paused=True)

    async def test_redirect_to_login_during_snapshot(self):
        await self.check(fixtures.TAOBAO, redirect=LOGIN, paused=True)

    async def test_initial_login_not_erased_by_redirect(self):
        await self.check(LOGIN, redirect=fixtures.TAOBAO, paused=True)

    async def test_dom_failure_pauses(self):
        await self.check(fixtures.TAOBAO, error=True, paused=True)

    async def test_normal_taobao_control(self):
        await self.check(fixtures.TAOBAO)

    async def test_blank_control(self):
        await self.check("about:blank", text="")

    async def test_jd_control(self):
        await self.check(fixtures.JD, jd=True)


class SearchInspectionTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    async def check_failure(self, operation, target):
        browser = self.service.taobao_browser
        browser.get_page = AsyncMock(return_value=self.page)
        self.page.url = fixtures.TAOBAO
        self.service._open_search_page = AsyncMock(return_value={"success": True})
        error = RuntimeError("synthetic search reload")

        async def fail(*args, **kwargs):
            self.page.url = target
            raise error

        getattr(self.locator, operation).side_effect = fail
        guard = browser._taobao_guard
        with patch.object(guard, "reserve_navigation") as reserve, patch(
            "jd_taobao_mcp.service.extract_taobao_search", new_callable=AsyncMock
        ) as extract:
            with self.assertRaises(RuntimeError) as caught:
                await self.service.search_products("taobao", "fixture")
            self.assertIs(caught.exception, error)
            self.assertTrue(TaobaoNavigationGuard(guard.state_path).is_paused())
            extract.assert_not_awaited()
            self.service._open_search_page.assert_awaited_once()
            reserve.assert_not_called()
            self.page.goto.assert_not_awaited()

    async def test_count_reload_pauses(self):
        await self.check_failure("count", fixtures.TAOBAO)

    async def test_count_login_redirect_pauses(self):
        await self.check_failure("count", LOGIN)

    async def test_text_reload_pauses(self):
        await self.check_failure("inner_text", fixtures.TAOBAO)

    async def test_text_verification_redirect_pauses(self):
        await self.check_failure("inner_text", "https://item.taobao.com/captcha")

    async def check_normal(self, platform):
        browser = self.service._browser_for_platform(platform)
        self.page.url = fixtures.TAOBAO if platform == "taobao" else fixtures.JD
        browser.get_page = AsyncMock(return_value=self.page)
        self.service._open_search_page = AsyncMock(return_value={"success": True})
        with patch(f"jd_taobao_mcp.service.extract_{platform}_search", new_callable=AsyncMock, return_value=[]):
            result = await self.service.search_products(platform, "fixture", include_details=False)
        self.assertTrue(result["success"])
        self.assertFalse(self.service.taobao_browser._taobao_guard.is_paused())

    async def test_normal_taobao(self):
        await self.check_normal("taobao")

    async def test_normal_jd(self):
        await self.check_normal("jd")
