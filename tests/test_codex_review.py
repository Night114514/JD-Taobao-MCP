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

    def test_p2_masked_names_and_boundaries(self):
        text = "t***3 2026-09-01 产品很好用 a**8 2026-09-02 非常满意推荐"
        reviews = _fallback_reviews_from_text(text, positive=True)
        self.assertEqual([r["user"] for r in reviews], ["t***3", "a**8"])
        self.assertEqual([r["content"] for r in reviews], ["产品很好用", "非常满意推荐"])

    def test_p2_unmasked_then_masked_not_merged(self):
        text = "买家甲 2026-09-01 产品很好用 t***3 2026-09-02 质量太糟糕"
        reviews = _fallback_reviews_from_text(text, positive=True)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["content"], "产品很好用")

    def test_p2_neutral_not_positive(self):
        self.assertEqual(_fallback_reviews_from_text("买家甲 2026-09-01 昨天收到包裹", positive=True), [])

    def test_p2_unknown_complaint_not_positive(self):
        self.assertEqual(_fallback_reviews_from_text("买家甲 2026-09-01 质量太糟糕", positive=True), [])

    def test_p2_positive_and_negative_controls(self):
        text = "买家甲 2026-09-01 非常满意很好用 买家乙 2026-09-02 非常差评不能用"
        self.assertEqual(len(_fallback_reviews_from_text(text, positive=True)), 1)
        self.assertEqual(len(_fallback_reviews_from_text(text, positive=False)), 1)

    async def test_p2_heading_selector_falls_back_to_body(self):
        body = "用户评价·2 买家甲 2026-09-01 非常满意很好用 买家乙 2026-09-02 非常差评不能用 查看全部评价"
        result = await self.extract(body, "用户评价 2")
        self.assertEqual(len(result["high_praise_reviews"]), 1)
        self.assertEqual(len(result["high_dissatisfied_reviews"]), 1)

    async def test_p2_valid_selector_control(self):
        result = await self.extract("No reviews", "买家甲 2026-09-01 非常满意很好用")
        self.assertEqual(len(result["high_praise_reviews"]), 1)


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
