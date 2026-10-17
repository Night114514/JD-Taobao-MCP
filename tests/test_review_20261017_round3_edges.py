"""Additional offline boundaries for Round 3; no real browser."""
import unittest
from unittest.mock import AsyncMock, Mock

from jd_taobao_mcp.service import _requires_extraction_verification
from jd_taobao_mcp.safety import SafetyError


class ReviewEdges(unittest.TestCase):
    def test_short_chinese_review_content_is_not_a_new_name(self):
        from jd_taobao_mcp.extractors.detail import _fallback_reviews_from_text
        rows = _fallback_reviews_from_text(
            "买家评价\n张三\n质量不错\n李四\n安装方便\n全部评价", positive=True)
        self.assertEqual([(r["user"], r["content"]) for r in rows],
                         [("张三", "质量不错"), ("李四", "安装方便")])

    def test_description_labels_and_sentences_are_not_names(self):
        from jd_taobao_mcp.extractors.detail import _fallback_reviews_from_text
        for text in ("商品描述", "产品介绍", "这是一段商品描述没有买家身份", "这个商品很好用"):
            with self.subTest(text=text):
                self.assertEqual(_fallback_reviews_from_text(
                    f"买家评价\n{text}\n很好用，非常满意\n全部评价", positive=True), [])


class ParameterEdges(unittest.TestCase):
    def test_adjacent_sections_keep_best_candidate(self):
        from jd_taobao_mcp.extractors.detail import _taobao_parameters_from_text
        text = "商品参数 品牌 Navigation 规格参数 品牌 Real 型号 K100 额定功率 1500W 额定电压 220V 商品详情"
        rows = _taobao_parameters_from_text(text)
        self.assertEqual({r["name"]: r["value"] for r in rows},
                         {"品牌": "Real", "型号": "K100", "额定功率": "1500W", "额定电压": "220V"})

    def test_end_boundaries_exclude_description_and_reviews(self):
        from jd_taobao_mcp.extractors.detail import _taobao_parameters_from_text
        for end in ("商品详情", "图文详情", "买家评价", "用户评价"):
            with self.subTest(end=end):
                rows = _taobao_parameters_from_text(
                    f"宝贝参数 品牌 Real 型号 K100 额定功率 1500W {end} 商品描述 品牌 Wrong 型号 Wrong")
                self.assertEqual({r["name"]: r["value"] for r in rows},
                                 {"品牌": "Real", "型号": "K100", "额定功率": "1500W"})

    def test_unterminated_section_remains_insufficient(self):
        from jd_taobao_mcp.extractors.detail import _taobao_parameters_from_text
        self.assertEqual(_taobao_parameters_from_text("商品参数 品牌 Real 型号 K100 额定功率 1500W"), [])


class VerificationEdges(unittest.IsolatedAsyncioTestCase):
    def page(self, **changes):
        signals = {"has_product_identity": False, "has_search_identity": False,
                   "has_challenge_ui": False, "outside_product_text": ""}
        signals.update(changes)
        page = Mock(url="https://search.jd.com/Search?keyword=synthetic")
        page.evaluate = AsyncMock(return_value=signals)
        return page

    async def test_empty_search_without_identity_is_allowed(self):
        page = self.page()
        self.assertFalse(await _requires_extraction_verification(page, "", "jd", context="search"))
        page.evaluate.assert_awaited_once()

    async def test_empty_search_challenge_is_blocked(self):
        page = self.page(has_challenge_ui=True)
        self.assertTrue(await _requires_extraction_verification(page, "", "jd", context="search"))

    async def test_malformed_probe_is_not_safe(self):
        for value in (None, [], {}, {"has_challenge_ui": False},
                      {"has_search_identity": 0, "has_challenge_ui": False, "outside_product_text": ""}):
            with self.subTest(value=value):
                page = self.page()
                page.evaluate.return_value = value
                self.assertTrue(await _requires_extraction_verification(page, "", "jd", context="search"))

    async def test_probe_exception_propagates(self):
        page = self.page()
        page.evaluate.side_effect = RuntimeError("synthetic DOM reload")
        with self.assertRaisesRegex(RuntimeError, "synthetic DOM reload"):
            await _requires_extraction_verification(page, "", "jd", context="search")

    async def test_cross_platform_change_after_probe_blocks(self):
        page = self.page()
        async def redirected(*args):
            page.url = "https://item.taobao.com/item.htm?id=1"
            return {"has_search_identity": False, "has_challenge_ui": False, "outside_product_text": ""}
        page.evaluate.side_effect = redirected
        with self.assertRaises(SafetyError):
            await _requires_extraction_verification(page, "", "jd", context="search")

    async def test_challenge_url_after_probe_blocks(self):
        page = self.page()
        async def redirected(*args):
            page.url = "https://passport.jd.com/new/login.aspx"
            return {"has_search_identity": False, "has_challenge_ui": False, "outside_product_text": ""}
        page.evaluate.side_effect = redirected
        self.assertTrue(await _requires_extraction_verification(page, "", "jd", context="search"))

    async def test_text_risk_without_identity_still_blocks(self):
        page = self.page()
        self.assertTrue(await _requires_extraction_verification(page, "安全验证", "jd", context="search"))
