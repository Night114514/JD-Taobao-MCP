"""Verification gates use synthetic snapshots and a temporary guard state."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from jd_taobao_mcp.config import Settings
from jd_taobao_mcp.safety import SafetyError
from jd_taobao_mcp.service import ShoppingBrowserService


URL = "https://item.taobao.com/item.htm?id=123456"


class CurrentPageVerificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        settings = replace(Settings.from_env(), profile_dir=Path(temp.name))
        self.service = ShoppingBrowserService(settings)
        self.browser = self.service.taobao_browser
        self.page = Mock(url=URL)
        self.page.locator.return_value.count = AsyncMock(return_value=1)
        self.page.locator.return_value.inner_text = AsyncMock(return_value="Product")
        self.browser.get_page = AsyncMock(return_value=self.page)
        self.browser.snapshot = AsyncMock(return_value={"url": URL, "text": "Product"})
        self.extractor = AsyncMock(return_value={"platform": "taobao", "url": URL})
        replacement = patch("jd_taobao_mcp.service.extract_product_detail", self.extractor)
        replacement.start()
        self.addCleanup(replacement.stop)

    async def assert_blocked(self):
        result = await self.service.extract_current_page()
        self.assertFalse(result["success"])
        self.assertTrue(result["requires_user_verification"])
        detail = result["product_like_data"]
        self.assertEqual(detail["parameter_evidence_status"], "not_extracted")
        self.assertEqual(detail["product_parameters"], [])
        self.assertEqual(detail["product_parameters_status"]["reason"], "requires_user_verification")
        self.extractor.assert_not_awaited()
        self.assertTrue(self.browser._taobao_guard.is_paused())

    async def test_snapshot_flag_blocks_extraction(self):
        self.browser.snapshot.return_value["requires_user_verification"] = True
        await self.assert_blocked()

    async def test_current_body_is_rechecked_after_snapshot(self):
        self.page.locator.return_value.inner_text.return_value = "請完成驗證"
        await self.assert_blocked()

    async def test_snapshot_risk_text_is_not_ignored(self):
        self.browser.snapshot.return_value["text"] = "访问过于频繁"
        await self.assert_blocked()

    async def test_taobao_login_url_is_blocked_without_captcha_text(self):
        self.page.url = "https://login.taobao.com/member/login.jhtml"
        self.browser.snapshot.return_value["url"] = self.page.url
        await self.assert_blocked()

    async def test_tmall_login_url_is_blocked_without_captcha_text(self):
        self.page.url = "https://login.tmall.com/"
        self.browser.snapshot.return_value["url"] = self.page.url
        await self.assert_blocked()

    async def test_inspection_failure_is_fail_closed(self):
        self.page.locator.return_value.inner_text.side_effect = RuntimeError("synthetic DOM failure")
        with self.assertRaises(SafetyError):
            await self.service.extract_current_page()
        self.extractor.assert_not_awaited()
        self.assertTrue(self.browser._taobao_guard.is_paused())

    async def test_normal_page_keeps_successful_contract(self):
        result = await self.service.extract_current_page()
        self.assertTrue(result["success"])
        self.extractor.assert_awaited_once()
        self.assertFalse(self.browser._taobao_guard.is_paused())

    async def test_login_host_normalization_and_tmall_login_paths(self):
        for url in ("https://LOGIN.TAOBAO.COM./member/login.jhtml",
                    "https://www.tmall.com/login", "https://tmall.com/member/login"):
            with self.subTest(url=url):
                self.page.url = url
                self.browser.snapshot.return_value["url"] = url
                await self.assert_blocked()

    async def test_jd_login_page_does_not_return_product_data(self):
        self.page.url = "https://passport.jd.com/new/login.aspx"
        self.browser.snapshot.return_value["url"] = self.page.url
        self.service.browser = self.service.jd_browser
        self.service.jd_browser.snapshot = self.browser.snapshot
        self.service.jd_browser.get_page = self.browser.get_page
        result = await self.service.extract_current_page()
        self.assertFalse(result["success"])
        self.assertTrue(result["requires_user_verification"])
        self.extractor.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
