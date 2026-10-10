"""Offline regressions for the seven Codex inline review findings."""
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_cross_platform_guard as platforms
import test_current_page_verification as current
from test_detail_navigation import make_page, BODY
from jd_taobao_mcp.extractors.detail import extract_product_detail, _fallback_reviews_from_text
from jd_taobao_mcp.safety import SafetyError
from jd_taobao_mcp.taobao_guard import TaobaoNavigationGuard


class NavigationInspectionTests(unittest.IsolatedAsyncioTestCase):
    setUp = platforms.CrossPlatformGuardTests.setUp

    async def check_transition(self, target):
        browser = self.service.taobao_browser
        browser._context = self.jd._context
        browser._page = self.page
        browser._start_unlocked = AsyncMock()
        self.page.url = platforms.TAOBAO
        guard = browser._taobao_guard
        async def text(**kwargs):
            self.page.url = target
            return "Product"
        self.locator.inner_text.side_effect = text
        with patch.object(guard, "reserve_navigation", wraps=guard.reserve_navigation) as reserve:
            if target == platforms.TAOBAO:
                self.assertTrue((await browser.navigate(platforms.TAOBAO))["success"])
                reserve.assert_called_once()
                self.page.goto.assert_awaited_once()
                self.assertFalse(guard.is_paused())
            else:
                with self.assertRaises(SafetyError):
                    await browser.navigate(platforms.TAOBAO)
                reserve.assert_not_called()
                self.page.goto.assert_not_awaited()
                self.assertTrue(TaobaoNavigationGuard(guard.state_path).is_paused())
                self.page.go_back.assert_not_awaited()

    async def test_p1_login_during_dom_read(self):
        await self.check_transition("https://login.taobao.com/member/login.jhtml")

    async def test_p1_verification_during_dom_read(self):
        await self.check_transition("https://item.taobao.com/captcha")

    async def test_p1_jd_during_dom_read(self):
        await self.check_transition(platforms.JD)

    async def test_p1_normal_control(self):
        await self.check_transition(platforms.TAOBAO)

    async def test_p2_click_title_redirect(self):
        async def title():
            self.page.url = platforms.TAOBAO
            return "Foreign"
        self.page.title.side_effect = title
        with self.assertRaises(SafetyError):
            await self.jd.click("e1")
        self.locator.click.assert_awaited_once()
        self.page.go_back.assert_not_awaited()

    async def test_p2_click_normal_control(self):
        self.assertTrue((await self.jd.click("e1"))["success"])


class ParserReviewTests(unittest.IsolatedAsyncioTestCase):
    async def extract(self, body, selected=""):
        return await extract_product_detail(make_page(raw={
            "title": "Synthetic product", "body_text": body, "body_text_all": body,
            "review_text": selected, "meta": {},
        }), "taobao")

    async def test_p2_generic_parameters(self):
        result = await self.extract("参数信息 品牌 Example 型号 K100 额定功率 1500W 额定电压 220V 图文详情")
        self.assertEqual({p["name"]: p["value"] for p in result["product_parameters"]},
                         {"品牌": "Example", "型号": "K100", "额定功率": "1500W", "额定电压": "220V"})

    async def test_p2_network_card_control(self):
        result = await self.extract(BODY)
        params = {p["name"]: p["value"] for p in result["product_parameters"]}
        self.assertEqual(params["型号"], "MT7925")
        self.assertEqual(params["网卡插口"], "M.2")
        self.assertEqual(len(params), 11)









class ExtractionFailureTests(unittest.IsolatedAsyncioTestCase):
    setUp = current.CurrentPageVerificationTests.setUp

    async def check_failure(self, operation):
        error = RuntimeError("synthetic evaluate context destroyed")
        self.page.evaluate = AsyncMock(side_effect=error)
        self.browser.navigate = AsyncMock(return_value={"url": current.URL})
        self.service._prepare_product_detail_page = AsyncMock()
        self.service._open_search_page = AsyncMock(return_value={"url": current.URL})
        with patch("jd_taobao_mcp.service.extract_product_detail", extract_product_detail):
            with self.assertRaises(RuntimeError) as caught:
                if operation == "detail":
                    await self.service.get_product_detail(current.URL)
                elif operation == "current":
                    await self.service.extract_current_page()
                else:
                    await self.service.search_products("taobao", "synthetic")
        self.assertIs(caught.exception, error)
        self.page.evaluate.assert_awaited_once()
        self.assertTrue(TaobaoNavigationGuard(self.browser._taobao_guard.state_path).is_paused())

    async def test_p2_detail_evaluate_failure_pauses(self):
        await self.check_failure("detail")

    async def test_p2_current_evaluate_failure_pauses(self):
        await self.check_failure("current")

    async def test_p2_search_evaluate_failure_pauses(self):
        await self.check_failure("search")
