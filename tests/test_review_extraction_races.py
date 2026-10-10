"""Verification introduced inside synthetic extraction or preparation."""
import unittest
from unittest.mock import AsyncMock, patch

import test_current_page_verification as fixtures
from jd_taobao_mcp.safety import SafetyError


class ExtractionRaceTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CurrentPageVerificationTests.setUp

    def configure(self):
        self.browser.navigate = AsyncMock(return_value={"url": fixtures.URL})
        self.service._open_search_page = AsyncMock(return_value={"url": fixtures.URL})
        self.service._prepare_product_detail_page = AsyncMock()
        self.page.mouse.wheel = AsyncMock()
        self.page.wait_for_timeout = AsyncMock()

    async def assert_late_verification(self, operation, login=False, missing=False):
        self.configure()
        async def late(*args, **kwargs):
            if login:
                self.page.url = "https://login.taobao.com/member/login.jhtml"
            elif missing:
                self.page.locator.return_value.inner_text.side_effect = RuntimeError("synthetic lost DOM")
            else:
                self.page.locator.return_value.inner_text.return_value = "請完成驗證"
            return {"platform": "taobao", "url": fixtures.URL,
                    "product_parameters": [{"name": "Model", "value": "synthetic"}],
                    "parameter_evidence_status": "provided"}
        self.extractor.side_effect = late
        with self.assertRaises(SafetyError):
            await operation()
        self.assertTrue(self.browser._taobao_guard.is_paused())

    async def test_current_page_discards_results_after_verification(self):
        await self.assert_late_verification(self.service.extract_current_page)

    async def test_current_page_discards_results_after_login_redirect(self):
        await self.assert_late_verification(self.service.extract_current_page, login=True)

    async def test_current_page_inspection_failure_after_extraction_pauses(self):
        await self.assert_late_verification(self.service.extract_current_page, missing=True)

    async def test_detail_discards_results_after_verification(self):
        await self.assert_late_verification(lambda: self.service.get_product_detail(fixtures.URL))

    async def test_detail_discards_results_after_login_redirect(self):
        await self.assert_late_verification(lambda: self.service.get_product_detail(fixtures.URL), login=True)

    async def test_detail_stops_before_extractor_when_preparation_reveals_verification(self):
        self.configure()
        async def preparation(*args):
            self.page.locator.return_value.inner_text.return_value = "安全驗證"
        self.service._prepare_product_detail_page.side_effect = preparation
        with self.assertRaises(SafetyError):
            await self.service.get_product_detail(fixtures.URL)
        self.extractor.assert_not_awaited()
        self.assertTrue(self.browser._taobao_guard.is_paused())

    async def test_search_discards_results_after_verification(self):
        self.configure()
        async def late(*args):
            self.page.locator.return_value.inner_text.return_value = "安全驗證"
            return [{"url": fixtures.URL, "price": 1}]
        with patch("jd_taobao_mcp.service.extract_taobao_search", AsyncMock(side_effect=late)):
            with self.assertRaises(SafetyError):
                await self.service.search_products("taobao", "synthetic")
        self.assertTrue(self.browser._taobao_guard.is_paused())
        self.page.mouse.wheel.assert_not_awaited()

    async def test_search_discards_results_after_login_redirect(self):
        self.configure()
        async def late(*args):
            self.page.url = "https://login.tmall.com/"
            return [{"url": fixtures.URL}]
        with patch("jd_taobao_mcp.service.extract_taobao_search", AsyncMock(side_effect=late)):
            with self.assertRaises(SafetyError):
                await self.service.search_products("taobao", "synthetic")
        self.assertTrue(self.browser._taobao_guard.is_paused())

    async def test_search_new_verification_after_navigation_persists_pause(self):
        self.configure()
        self.page.locator.return_value.inner_text.return_value = "請完成驗證"
        result = await self.service.search_products("taobao", "synthetic")
        self.assertFalse(result["success"])
        self.assertEqual(result["items"], [])
        self.assertTrue(self.browser._taobao_guard.is_paused())

    async def test_detail_new_verification_after_navigation_persists_pause(self):
        self.configure()
        self.page.locator.return_value.inner_text.return_value = "請完成驗證"
        result = await self.service.get_product_detail(fixtures.URL)
        self.assertFalse(result["success"])
        self.extractor.assert_not_awaited()
        self.assertTrue(self.browser._taobao_guard.is_paused())

    async def jd_late_verification(self, operation):
        self.configure()
        browser = self.service.jd_browser
        browser.get_page = self.browser.get_page
        browser.snapshot = AsyncMock(return_value={"url": "https://item.jd.com/123.html", "text": "Product"})
        browser.navigate = self.browser.navigate
        self.service.browser = browser
        self.page.url = "https://item.jd.com/123.html"
        async def late(*args, **kwargs):
            self.page.locator.return_value.inner_text.return_value = "安全驗證"
            return [{"url": self.page.url}] if operation == "search" else {"platform": "jd", "url": self.page.url}
        self.extractor.side_effect = late
        with patch("jd_taobao_mcp.service.extract_jd_search", AsyncMock(side_effect=late)):
            with self.assertRaises(SafetyError):
                if operation == "search":
                    await self.service.search_products("jd", "synthetic", include_details=False)
                elif operation == "detail":
                    await self.service.get_product_detail(self.page.url)
                else:
                    await self.service.extract_current_page()
        self.assertFalse(self.service.taobao_browser._taobao_guard.is_paused())

    async def test_jd_current_page_discards_late_verification(self):
        await self.jd_late_verification("current")

    async def test_jd_detail_discards_late_verification(self):
        await self.jd_late_verification("detail")

    async def test_jd_search_discards_late_verification(self):
        await self.jd_late_verification("search")
