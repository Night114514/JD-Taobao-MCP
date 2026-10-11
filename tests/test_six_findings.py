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


class LoginConsistencyTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    async def check(self, url, cookies=False, transition=None, text="Product", expected=False, dom_transition=None):
        browser = self.service.taobao_browser
        browser._context = self.jd._context
        browser._page = self.page
        browser._start_unlocked = AsyncMock()
        self.page.url = url
        self.locator.inner_text.return_value = text
        if dom_transition:
            async def change_dom(*args, **kwargs):
                self.page.url = dom_transition
                return text
            self.locator.inner_text.side_effect = change_dom
        names = [{"name": "tracknick", "domain": ".taobao.com", "value": "SYNTHETIC_SECRET"}] if cookies else []
        browser._context.cookies.return_value = names
        if transition:
            async def redirect():
                self.page.url = transition
                return names
            browser._context.cookies.side_effect = redirect
        result = await browser.check_login("taobao")
        self.assertEqual(result["requires_user_verification"], expected)
        self.assertEqual(result["likely_logged_in"], cookies and not expected)
        self.assertNotIn("SYNTHETIC_SECRET", str(result))
        self.assertEqual(TaobaoNavigationGuard(browser._taobao_guard.state_path).is_paused(), expected)
        self.page.goto.assert_not_awaited()

    async def test_login_without_keywords(self):
        await self.check(LOGIN, expected=True)

    async def test_login_with_stale_cookie_names(self):
        await self.check(LOGIN, cookies=True, expected=True)

    async def test_verification_url_with_stale_cookies(self):
        await self.check(VERIFY, cookies=True, expected=True)

    async def test_normal_logged_in_control(self):
        await self.check(fixtures.TAOBAO, cookies=True)

    async def test_normal_logged_out_control(self):
        await self.check(fixtures.TAOBAO)

    async def test_redirect_during_cookie_await(self):
        await self.check(fixtures.TAOBAO, cookies=True, transition=LOGIN, expected=True)

    async def test_verification_body_is_not_logged_in(self):
        await self.check(fixtures.TAOBAO, cookies=True, text="安全验证", expected=True)

    async def test_redirect_during_dom_await(self):
        await self.check(fixtures.TAOBAO, cookies=True, dom_transition=LOGIN, expected=True)

    async def test_observed_auth_not_erased_by_later_redirect(self):
        await self.check(LOGIN, cookies=True, transition=fixtures.TAOBAO, expected=True)
