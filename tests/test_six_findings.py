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


class ActiveControllerTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    async def test_start_selects_taobao_for_generic_reads(self):
        tb = self.service.taobao_browser
        jd = self.service.jd_browser
        tb.start = AsyncMock(return_value={"success": True})
        for browser, name in ((tb, "taobao"), (jd, "jd")):
            browser.snapshot = AsyncMock(return_value={"controller": name})
            browser.list_elements = AsyncMock(return_value={"controller": name})
        self.assertIs(self.service.browser, jd)
        with patch.object(server, "service", self.service):
            await server.browser_start()
            self.assertEqual((await server.page_snapshot())["controller"], "taobao")
            self.assertEqual((await server.list_page_elements())["controller"], "taobao")
        jd.snapshot.assert_not_awaited()
        jd.list_elements.assert_not_awaited()
        tb.start.assert_awaited_once()
        self.assertNotEqual(tb.settings.profile_dir, jd.settings.profile_dir)

    async def test_start_keeps_taobao_interaction_denials(self):
        tb = self.service.taobao_browser
        tb.start = AsyncMock(return_value={"success": True})
        with patch.object(server, "service", self.service):
            await server.browser_start()
            for action in (lambda: server.click_page_element("e1"),
                           lambda: server.type_into_element("e1", "text"),
                           server.scroll_page, server.go_back):
                with self.subTest(action=action), self.assertRaises(SafetyError):
                    await action()
        self.jd._start_unlocked.assert_not_awaited()


class CanonicalEncodingTests(unittest.TestCase):
    def test_encoded_delimiters_keep_query_boundaries(self):
        for item, sku in (("123%26foo%3Dbar", "456%23fragment"),
                          ("123%3D456", "1%26x%3D2"), ("12%2526", "45%2B6")):
            with self.subTest(item=item, sku=sku):
                original = f"https://item.taobao.com/item.htm?id={item}&skuId={sku}"
                result = urlparse(_canonical_detail_url(original))
                self.assertEqual(parse_qs(result.query), parse_qs(urlparse(original).query))
                self.assertEqual(result.fragment, "")

    def test_normal_mobile_and_idempotence(self):
        original = "https://new.m.taobao.com/detail.htm?id=123&skuId=456&tracking=abc"
        result = _canonical_detail_url(original)
        self.assertEqual(result, "https://item.taobao.com/item.htm?id=123&skuId=456")
        self.assertEqual(_canonical_detail_url(result), result)


class ParameterSourceMergeTests(unittest.IsolatedAsyncioTestCase):
    async def extract(self, parameters, details=None):
        return await extract_product_detail(make_page(raw={
            "title": "Product", "body_text": TEXT, "body_text_all": TEXT,
            "product_parameters": parameters, "detail_product_parameters": details or [],
        }), "taobao")

    async def test_structured_extra_fields_survive_text(self):
        result = await self.extract([{"name": "颜色", "value": "蓝色"}],
                                    [{"name": "尺寸", "value": "10 cm"}])
        values = {p["name"]: p["value"] for p in result["product_parameters"]}
        self.assertEqual(values["颜色"], "蓝色")
        self.assertEqual(values["尺寸"], "10 cm")
        self.assertEqual(values["品牌"], "Example")

    async def test_same_values_deduplicated(self):
        result = await self.extract([{"name": "品牌", "value": "Example"}])
        self.assertEqual([p["value"] for p in result["product_parameters"] if p["name"] == "品牌"], ["Example"])

    async def test_conflicting_values_keep_text_precedence(self):
        result = await self.extract([{"name": "品牌", "value": "Other"},
                                     {"name": "颜色", "value": "蓝色"}],
                                    [{"name": "颜色", "value": "红色"}])
        values = {p["name"]: p["value"] for p in result["product_parameters"]}
        self.assertEqual(values["品牌"], "Example")
        self.assertEqual(values["颜色"], "蓝色")
        # PR #2 exposes evidence/conflicts; PR #1 retains its existing schema.
        if "product_parameter_conflicts" in result:
            conflicts = {c["name"]: c for c in result["product_parameter_conflicts"]}
            self.assertEqual(conflicts["品牌"]["selected_value"], "Example")
            self.assertIn({"source": "dom_parameters", "value": "Other"}, conflicts["品牌"]["alternatives"])
            self.assertIn({"source": "dom_detail", "value": "红色"}, conflicts["颜色"]["alternatives"])
            self.assertIn("dom_parameters", str(result["product_parameter_evidence"]))

    async def test_separated_review_and_parameters_parse(self):
        body = TEXT + " 用户评价·1 t***3\n2026-09-01\n很好用非常满意 查看全部评价"
        result = await extract_product_detail(make_page(raw={
            "title": "Product", "body_text": "Product", "body_text_all": body,
            "review_text": "用户评价 1",
        }), "taobao")
        self.assertEqual(len(result["product_parameters"]), 3)
        self.assertEqual(len(result["high_praise_reviews"]), 1)
