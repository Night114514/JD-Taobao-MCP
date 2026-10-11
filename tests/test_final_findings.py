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






class BodyTransferContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_truncation_is_disclosed(self):
        page = make_page(raw={"title": "Product", "body_text": "Product",
                              "body_text_all": "x" * 80000, "body_text_all_truncated": True})
        result = await extract_product_detail(page, "taobao")
        self.assertTrue(result["body_text_all_truncated"])

    async def test_hidden_generic_parameters_preserved(self):
        page = make_page(raw={"title": "Product", "body_text": "Product",
            "body_text_all": "参数信息 品牌 Example 型号 K1 额定功率 100W 额定电压 220V 图文详情"})
        result = await extract_product_detail(page, "taobao")
        self.assertEqual(len(result["product_parameters"]), 4)

    async def test_hidden_network_and_review_fallback_preserved(self):
        page = make_page(raw={"title": "Product", "body_text": "Product",
                              "body_text_all": BODY, "review_text": "用户评价 2"})
        result = await extract_product_detail(page, "taobao")
        self.assertEqual(len(result["product_parameters"]), 11)
        self.assertEqual(len(result["high_praise_reviews"]), 2)

    async def test_absent_tail_not_fabricated(self):
        page = make_page(raw={"title": "Product", "body_text": "Product",
                              "body_text_all": "x" * 80000, "body_text_all_truncated": True})
        result = await extract_product_detail(page, "taobao")
        self.assertEqual(result["product_parameters"], [])
        self.assertEqual(result["high_praise_reviews"], [])
