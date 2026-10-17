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
        self.page.evaluate = AsyncMock(return_value={
            "has_product_identity": False, "has_search_identity": False,
            "has_challenge_ui": False, "outside_product_text": "",
        })
        await self.check_normal("jd")


class PriceTrustTests(unittest.IsolatedAsyncioTestCase):
    async def check(self, dom, metadata, expected, source, body="Product"):
        url = fixtures.TAOBAO + "&skuId=654321" + ("&upStreamPrice=" + metadata if metadata is not None else "")
        result = await extract_product_detail(make_page(raw={"title": "Product", "price_text": dom, "body_text": body}), "taobao", original_url=url)
        self.assertEqual(result["price"], expected)
        self.assertEqual(result["price_source"], source)
        self.assertEqual(result["selected_sku_id"], "654321")

    async def test_unverified_url_cannot_override_dom_sku_price(self):
        await self.check("¥35.00", "100", 35.0, "dom")

    async def test_missing_url_price(self):
        await self.check("¥35.00", None, 35.0, "dom")

    async def test_missing_dom_uses_url_fallback(self):
        await self.check("", "8500", 85.0, "url_upStreamPrice")

    async def test_invalid_url_keeps_dom(self):
        for value in ("NaN", "Infinity", "-1", "0", "bad"):
            with self.subTest(value=value):
                await self.check("¥35.00", value, 35.0, "dom")

    async def test_matching_price_keeps_page_provenance(self):
        await self.check("¥35.00", "3500", 35.0, "dom")

    async def test_visible_body_price_precedes_url(self):
        await self.check("", "100", 35.0, "visible_product_text", body="Product ¥35.00")


class JDVerificationContextTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    async def check(self, text, signals, blocked, url=fixtures.JD, platform="jd"):
        self.page.url = url
        self.locator.inner_text.return_value = text
        self.page.evaluate.return_value = signals
        browser = self.service._browser_for_platform(platform)
        if blocked:
            with self.assertRaises(SafetyError):
                await self.service._assert_extraction_page(browser, self.page, platform)
        else:
            await self.service._assert_extraction_page(browser, self.page, platform)

    async def test_product_description_and_review_mentions_allowed(self):
        for term in ("安全验证", "验证码错误"):
            with self.subTest(term=term):
                await self.check("商品编号 123 商品详情 " + term,
                    {"has_product_identity": True, "has_challenge_ui": False, "outside_product_text": "Product ¥35"}, False)

    async def test_verification_with_product_words_still_blocked(self):
        await self.check("商品详情 安全验证", {"has_product_identity": False, "has_challenge_ui": True, "outside_product_text": "安全验证"}, True)

    async def test_overlay_on_real_product_still_blocked(self):
        await self.check("商品编号 123 安全验证", {"has_product_identity": True, "has_challenge_ui": True, "outside_product_text": ""}, True)

    async def test_outside_product_verification_still_blocked(self):
        await self.check("商品编号 123 安全验证", {"has_product_identity": True, "has_challenge_ui": False, "outside_product_text": "安全验证"}, True)

    async def test_login_url_never_exempted(self):
        await self.check("商品编号 123", {}, True, url="https://passport.jd.com/new/login.aspx")

    async def test_taobao_never_gets_jd_exemption(self):
        await self.check("商品编号 123 安全验证", {"has_product_identity": True, "has_challenge_ui": False, "outside_product_text": ""}, True, url=fixtures.TAOBAO, platform="taobao")

    async def test_detail_caller_preserves_success_contract(self):
        self.page.url = fixtures.JD
        self.locator.inner_text.return_value = "商品编号 123 商品详情 安全验证"
        self.page.evaluate.return_value = {"has_product_identity": True, "has_challenge_ui": False, "outside_product_text": "Product"}
        self.jd.navigate = AsyncMock(return_value={"success": True})
        self.jd.get_page = AsyncMock(return_value=self.page)
        self.service._prepare_product_detail_page = AsyncMock()
        with patch("jd_taobao_mcp.service.extract_product_detail", new_callable=AsyncMock, return_value={"product_url": fixtures.JD, "product_parameters": [], "price": 35.0}):
            result = await self.service.get_product_detail(fixtures.JD)
        self.assertTrue(result["success"])
        self.assertEqual(result["price"], 35.0)
        self.assertIn("product_parameters_status", result)

    async def test_current_page_caller_uses_live_context(self):
        self.service.browser = self.jd
        self.page.url = fixtures.JD
        self.locator.inner_text.return_value = "商品详情 安全验证"
        self.page.evaluate.return_value = {"has_product_identity": True, "has_challenge_ui": False, "outside_product_text": "Product"}
        self.jd.snapshot = AsyncMock(return_value={"url": fixtures.JD, "text": "商品详情 安全验证", "requires_user_verification": True})
        self.jd.get_page = AsyncMock(return_value=self.page)
        with patch("jd_taobao_mcp.service.extract_product_detail", new_callable=AsyncMock, return_value={"product_url": fixtures.JD, "product_parameters": []}):
            result = await self.service.extract_current_page()
        self.assertTrue(result["success"])

    async def test_context_inspection_exception_still_blocks(self):
        self.page.url = fixtures.JD
        self.locator.inner_text.return_value = "商品详情 安全验证"
        self.page.evaluate.side_effect = RuntimeError("synthetic context lost")
        with self.assertRaises(SafetyError) as caught:
            await self.service._assert_extraction_page(self.jd, self.page, "jd")
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)

    async def test_context_redirect_is_not_exempted(self):
        self.page.url = fixtures.JD
        self.locator.inner_text.return_value = "商品详情 安全验证"
        async def redirect(*args):
            self.page.url = "https://passport.jd.com/new/login.aspx"
            return {"has_product_identity": True, "has_challenge_ui": False, "outside_product_text": ""}
        self.page.evaluate.side_effect = redirect
        with self.assertRaises(SafetyError):
            await self.service._assert_extraction_page(self.jd, self.page, "jd")
