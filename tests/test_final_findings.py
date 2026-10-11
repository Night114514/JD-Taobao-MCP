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


class ServerCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def check(self, jd_fail=False, tb_fail=False, returned_failure=False):
        jd = AsyncMock(return_value={"success": True})
        tb = AsyncMock(return_value={"success": True})
        if jd_fail:
            jd.side_effect = RuntimeError("JD disconnected")
        if tb_fail:
            tb.side_effect = ValueError("Taobao disconnected")
        if returned_failure:
            jd.return_value = {"success": False, "errors": {"context": "synthetic"}}
        service = SimpleNamespace(jd_browser=SimpleNamespace(close=jd), taobao_browser=SimpleNamespace(close=tb))
        with patch.object(server, "service", service):
            result = await server.browser_close()
        jd.assert_awaited_once()
        tb.assert_awaited_once()
        self.assertEqual(result["success"], not (jd_fail or tb_fail or returned_failure))
        if jd_fail:
            self.assertIn("JD disconnected", str(result))
            self.assertIn("RuntimeError", str(result))
        if tb_fail:
            self.assertIn("Taobao disconnected", str(result))
            self.assertIn("ValueError", str(result))

    async def test_jd_failure_still_closes_taobao(self):
        await self.check(jd_fail=True)

    async def test_taobao_failure_reported(self):
        await self.check(tb_fail=True)

    async def test_both_failures_retained(self):
        await self.check(jd_fail=True, tb_fail=True)

    async def test_normal_close_control(self):
        await self.check()

    async def test_returned_failure_not_success(self):
        await self.check(returned_failure=True)


class ControllerCleanupTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    async def check(self, context_fail=False, driver_fail=False):
        context = Mock(close=AsyncMock())
        driver = Mock(stop=AsyncMock())
        self.jd._context = context
        self.jd._playwright = driver
        if context_fail:
            context.close.side_effect = RuntimeError("context disconnected")
        if driver_fail:
            driver.stop.side_effect = ValueError("driver disconnected")
        result = await self.jd.close()
        context.close.assert_awaited_once()
        driver.stop.assert_awaited_once()
        self.assertEqual(result["success"], not (context_fail or driver_fail))
        if context_fail:
            self.assertIn("context disconnected", str(result))
        if driver_fail:
            self.assertIn("driver disconnected", str(result))
        if not driver_fail:
            self.assertIsNone(self.jd._playwright)
            self.assertIsNone(self.jd._context)
            self.assertIsNone(self.jd._page)

    async def test_context_failure_still_stops_driver(self):
        await self.check(context_fail=True)

    async def test_driver_failure_reported(self):
        await self.check(driver_fail=True)

    async def test_both_cleanup_failures_retained(self):
        await self.check(context_fail=True, driver_fail=True)

    async def test_normal_cleanup_control(self):
        await self.check()


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
