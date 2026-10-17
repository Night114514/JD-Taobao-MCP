"""Round 3 E/F/G: offline regression specifications; no production changes."""
import unittest
from unittest.mock import AsyncMock, patch

import test_cross_platform_guard as browser_fixtures
import test_codex_review as parser_fixtures
from jd_taobao_mcp.extractors.detail import (
    _fallback_reviews_from_text,
    _taobao_parameters_from_text,
)
from jd_taobao_mcp.safety import SafetyError, VerificationRequired
from jd_taobao_mcp.service import _requires_extraction_verification
from jd_taobao_mcp.taobao_guard import TaobaoNavigationGuard


PARAMETERS = "品牌 Example 型号 K100 额定功率 1500W 额定电压 220V"
EXPECTED_PARAMETERS = {
    "品牌": "Example", "型号": "K100", "额定功率": "1500W", "额定电压": "220V",
}
POSITIVE = "很好用，非常满意"
NEGATIVE = "非常差评，坏了，不能用"
CONTROLS = (
    "#JDJRV-wrap",
    'iframe[src*="captcha"]',
    'input[autocomplete="one-time-code"]',
)


class FindingETests(unittest.IsolatedAsyncioTestCase):
    setUp = browser_fixtures.CrossPlatformGuardTests.setUp

    def page_signals(self, selector=None, *, visible=True, text="正常商品 品牌 Example 型号 K100 价格 99"):
        self.locator.inner_text.return_value = text

        async def evaluate(script, context="detail"):
            if selector:
                self.assertIn(selector, script)
            return {
                "has_product_identity": True,
                "has_search_identity": True,
                "has_challenge_ui": bool(selector and visible),
                "outside_product_text": "",
            }

        self.page.evaluate = AsyncMock(side_effect=evaluate)

    def service_fixture(self):
        self.service._prepare_product_detail_page = AsyncMock()

        async def navigate(url):
            self.page.url = url
            return {"url": url, "http_status": 200, "success": True}

        self.jd.navigate = AsyncMock(side_effect=navigate)
        self.service._open_search_page = AsyncMock(return_value={
            "url": "https://search.jd.com/Search?keyword=synthetic", "http_status": 200,
        })

    async def assert_refused(self, operation):
        try:
            result = await operation()
        except VerificationRequired:
            return
        self.assertFalse(result["success"], "Challenge page must not return ordinary success")
        self.assertTrue(result.get("requires_user_verification"))

    async def test_e_red_ui_only_controls_direct(self):
        for selector in CONTROLS:
            with self.subTest(selector=selector):
                self.page_signals(selector)
                self.assertTrue(await _requires_extraction_verification(
                    self.page, self.locator.inner_text.return_value, "jd"))

    async def test_e_red_search_controls_direct(self):
        self.page.url = "https://search.jd.com/Search?keyword=synthetic"
        self.page_signals("#JDJRV-wrap")
        self.assertTrue(await _requires_extraction_verification(
            self.page, "合法商品卡片 品牌 Example 99元", "jd", context="search"))

    async def test_e_red_detail_service_ui_only(self):
        self.service_fixture()
        for selector in CONTROLS:
            with self.subTest(selector=selector):
                self.page_signals(selector)
                with patch("jd_taobao_mcp.service.extract_product_detail", AsyncMock(
                    return_value={"title": "完整商品", "price": 99, "shop": "Synthetic shop"}
                )):
                    await self.assert_refused(lambda: self.service.get_product_detail(browser_fixtures.JD))

    async def test_e_red_search_service_ui_only(self):
        self.service_fixture()
        self.page.url = "https://search.jd.com/Search?keyword=synthetic"
        self.page_signals('iframe[src*="captcha"]')
        with patch("jd_taobao_mcp.service.extract_jd_search", AsyncMock(return_value=[
            {"url": browser_fixtures.JD, "title": "合法商品卡片", "price": 99}
        ])):
            await self.assert_refused(lambda: self.service.search_products(
                "jd", "synthetic", include_details=False))

    async def bulk_result(self, challenge):
        self.service_fixture()
        self.page.url = "https://search.jd.com/Search?keyword=synthetic"
        self.page_signals()
        items = [{"url": "https://item.jd.com/111.html", "price": 10},
                 {"url": "https://item.jd.com/222.html", "price": 20}]

        async def extract(*args, **kwargs):
            # Challenge appears during the first extraction; the post-check must stop item two.
            self.page_signals("#JDJRV-wrap" if challenge else None,
                              text="完整商品 品牌 Example 99元" if challenge else "商品说明 安全验证 验证码错误")
            return {"title": "Synthetic complete product", "price": 10}

        with patch("jd_taobao_mcp.service.extract_jd_search", AsyncMock(return_value=items)), patch(
            "jd_taobao_mcp.service.extract_product_detail", AsyncMock(side_effect=extract)
        ):
            # Intentionally omit include_details: exercise its public default True.
            return await self.service.search_products("jd", "synthetic")

    async def test_e_red_default_bulk_stops_after_first_challenge(self):
        result = await self.bulk_result(True)
        with self.subTest(safety="no_second_navigation"):
            self.assertEqual([call.args[0] for call in self.jd.navigate.await_args_list],
                             ["https://item.jd.com/111.html"])
        with self.subTest(safety="user_visible_verification"):
            self.assertFalse(result["success"])
            self.assertTrue(result.get("requires_user_verification"))
            self.assertEqual(result["items"], [])

    async def test_e_control_hidden_and_normal_direct(self):
        for selector in (None, *CONTROLS):
            with self.subTest(selector=selector):
                self.page_signals(selector, visible=False)
                self.assertFalse(await _requires_extraction_verification(self.page, "正常商品", "jd"))

    async def test_e_control_product_copy_direct(self):
        for phrase in ("安全验证", "验证码错误"):
            with self.subTest(phrase=phrase):
                self.page_signals(text="商品介绍 " + phrase)
                self.assertFalse(await _requires_extraction_verification(self.page, "商品介绍 " + phrase, "jd"))

    async def test_e_control_normal_and_hidden_detail_service(self):
        self.service_fixture()
        for selector in (None, "#JDJRV-wrap"):
            with self.subTest(selector=selector):
                self.page_signals(selector, visible=False)
                with patch("jd_taobao_mcp.service.extract_product_detail", AsyncMock(return_value={"title": "Normal", "price": 99})):
                    result = await self.service.get_product_detail(browser_fixtures.JD)
                self.assertTrue(result["success"])
                self.assertFalse(result["requires_user_verification"])

    async def test_e_control_bulk_product_copy(self):
        result = await self.bulk_result(False)
        self.assertTrue(result["success"])
        self.assertEqual(self.jd.navigate.await_count, 2)
        self.assertEqual(result["count"], 2)

    async def test_e_control_taobao_strict_pause(self):
        browser = self.service.taobao_browser
        browser._context = self.jd._context
        browser._page = self.page
        browser._start_unlocked = AsyncMock()
        self.page.url = browser_fixtures.TAOBAO
        self.locator.inner_text.return_value = "安全验证 CAPTCHA"
        with self.assertRaises(SafetyError):
            await self.service.get_product_detail(browser_fixtures.TAOBAO)
        self.page.goto.assert_not_awaited()
        self.assertTrue(TaobaoNavigationGuard(browser._taobao_guard.state_path).is_paused())


class FindingFTests(unittest.IsolatedAsyncioTestCase):
    # Reuse the existing passing generic-parameter extraction fixture, not a new raw schema.
    extract = parser_fixtures.ParserReviewTests.extract

    def parameters(self, text):
        return {p["name"]: p["value"] for p in _taobao_parameters_from_text(text)}

    def test_f_red_alternate_headings_direct(self):
        for heading in ("商品参数", "宝贝参数", "规格参数"):
            with self.subTest(start=heading, end="图文详情"):
                self.assertEqual(self.parameters(f"{heading} {PARAMETERS} 图文详情"), EXPECTED_PARAMETERS)

    def test_f_red_alternate_end_direct(self):
        self.assertEqual(self.parameters(f"参数信息 {PARAMETERS} 商品详情"), EXPECTED_PARAMETERS)

    async def test_f_red_alternate_headings_extractor(self):
        for start, end in (("商品参数", "图文详情"), ("宝贝参数", "图文详情"),
                           ("规格参数", "图文详情"), ("参数信息", "商品详情")):
            with self.subTest(start=start, end=end):
                result = await self.extract(f"{start} {PARAMETERS} {end}")
                self.assertEqual({p["name"]: p["value"] for p in result["product_parameters"]}, EXPECTED_PARAMETERS)

    def test_f_red_multiple_heading_candidates(self):
        text = f"参数信息 图文详情 商品参数 {PARAMETERS} 图文详情"
        self.assertEqual(self.parameters(text), EXPECTED_PARAMETERS)

    def test_f_control_original_format(self):
        self.assertEqual(self.parameters(f"参数信息 {PARAMETERS} 图文详情"), EXPECTED_PARAMETERS)

    async def test_f_control_original_extractor(self):
        result = await self.extract(f"参数信息 {PARAMETERS} 图文详情")
        self.assertEqual({p["name"]: p["value"] for p in result["product_parameters"]}, EXPECTED_PARAMETERS)

    def test_f_control_duplicate_sections_not_duplicated(self):
        section = f"参数信息 {PARAMETERS} 图文详情"
        rows = _taobao_parameters_from_text(section + " " + section)
        self.assertEqual(len(rows), 4)
        self.assertEqual({p["name"]: p["value"] for p in rows}, EXPECTED_PARAMETERS)

    def test_f_control_existing_three_label_threshold(self):
        self.assertEqual(self.parameters("参数信息 品牌 Example 型号 K100 图文详情"), {})
        self.assertEqual(self.parameters("参数信息 品牌 Example 型号 K100 额定功率 1500W 图文详情"),
                         {k: EXPECTED_PARAMETERS[k] for k in ("品牌", "型号", "额定功率")})

    def test_f_control_description_and_review_boundaries(self):
        self.assertEqual(self.parameters("商品介绍 " + PARAMETERS + " 买家评价 非常满意"), {})
        self.assertEqual(self.parameters(f"参数信息 {PARAMETERS} 图文详情 商品介绍 评论 品牌 Other 型号 Wrong"), EXPECTED_PARAMETERS)

    def test_f_control_traditional_headings_not_existing_contract(self):
        # No heading/label traditional normalization exists in this parser's current contract.
        for heading in ("參數信息", "商品參數", "寶貝參數", "規格參數"):
            with self.subTest(heading=heading):
                self.assertEqual(self.parameters(f"{heading} {PARAMETERS} 圖文詳情"), {})


class FindingGTests(unittest.IsolatedAsyncioTestCase):
    extract = parser_fixtures.ParserReviewTests.extract

    def parse(self, text, positive=True):
        return _fallback_reviews_from_text(text, positive=positive)

    def test_g_red_chinese_names_direct(self):
        for name in ("张三", "张小三", "欧阳小明", "陳大文"):
            with self.subTest(name=name):
                rows = self.parse(f"买家评价\n{name}\n{POSITIVE}")
                self.assertEqual([(r["user"], r["content"], r["time"]) for r in rows], [(name, POSITIVE, "")])

    def test_g_red_adjacent_chinese_records(self):
        rows = self.parse(f"买家评价\n张三\n{POSITIVE}\n李四\n安装方便，非常推荐\n全部评价")
        self.assertEqual([(r["user"], r["content"]) for r in rows], [("张三", POSITIVE), ("李四", "安装方便，非常推荐")])

    def test_g_red_mixed_ascii_chinese_records(self):
        rows = self.parse(f"买家评价\nAlice\n{POSITIVE}\n张三\n安装方便，非常推荐\nBob\n质量不错\n全部评价")
        self.assertEqual([(r["user"], r["content"]) for r in rows],
                         [("Alice", POSITIVE), ("张三", "安装方便，非常推荐"), ("Bob", "质量不错")])

    def test_g_red_positive_negative_classification(self):
        text = f"买家评价\n张三\n{POSITIVE}\n李四\n{NEGATIVE}\n全部评价"
        for positive, name, content in ((True, "张三", POSITIVE), (False, "李四", NEGATIVE)):
            with self.subTest(positive=positive):
                self.assertEqual([(r["user"], r["content"]) for r in self.parse(text, positive)], [(name, content)])

    async def test_g_red_extractor_undated_chinese_reviews(self):
        result = await self.extract(f"买家评价\n张三\n{POSITIVE}\n李四\n{NEGATIVE}\n全部评价")
        for field, name, content in (("high_praise_reviews", "张三", POSITIVE),
                                     ("high_dissatisfied_reviews", "李四", NEGATIVE)):
            with self.subTest(field=field):
                self.assertEqual([(r["user"], r["content"]) for r in result[field]], [(name, content)])

    def test_g_control_masked_name(self):
        self.assertEqual([(r["user"], r["content"]) for r in self.parse(f"买家评价 t***3 {POSITIVE} 全部评价")], [("t***3", POSITIVE)])

    def test_g_control_dated_chinese_names(self):
        text = f"买家评价 张三 2026-09-01 {POSITIVE} 陳大文 2026年9月2日 安装方便 全部评价"
        self.assertEqual([(r["user"], r["time"]) for r in self.parse(text)], [("张三", "2026-09-01"), ("陳大文", "2026年9月2日")])

    def test_g_control_ascii_line_boundaries(self):
        rows = self.parse(f"买家评价\nAlice\n{POSITIVE}\nBob\n安装方便\n全部评价")
        self.assertEqual([(r["user"], r["content"]) for r in rows], [("Alice", POSITIVE), ("Bob", "安装方便")])

    def test_g_control_description_not_reviewer(self):
        for text in (f"买家评价 本商品 {POSITIVE} 全部评价",
                     f"买家评价\n这是一段普通商品描述，介绍外观及尺寸。\n{POSITIVE}\n全部评价"):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text), [])

    def test_g_control_no_heading_no_invented_records(self):
        for name in ("张三", "陳大文", "Alice", "t***3"):
            with self.subTest(name=name):
                self.assertEqual(self.parse(f"商品说明\n{name}\n{POSITIVE}"), [])

    def test_g_control_section_end_bounds_reviews(self):
        rows = self.parse(f"买家评价\nAlice\n{POSITIVE}\n商品详情\n张三\n安装方便")
        self.assertEqual([(r["user"], r["content"]) for r in rows], [("Alice", POSITIVE)])

    def test_g_control_neutral_chinese_review_not_classified(self):
        text = "买家评价\n张三\n今天收到包裹\n全部评价"
        self.assertEqual(self.parse(text, True), [])
        self.assertEqual(self.parse(text, False), [])
