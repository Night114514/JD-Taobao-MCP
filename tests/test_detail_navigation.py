"""Offline V7 regressions; fixture text is synthetic, not live Taobao evidence."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, Mock, patch

from jd_taobao_mcp.config import Settings
from jd_taobao_mcp.extractors.detail import extract_product_detail
from jd_taobao_mcp.safety import SafetyError
from jd_taobao_mcp.service import ShoppingBrowserService, _canonical_detail_url


CANONICAL = "https://item.taobao.com/item.htm?id=623937911339&skuId=5455243929341"
ORIGINAL = (
    "https://item.taobao.com/item.htm?addressId=14849490262&areaId=810202"
    "&detailAlgoParam=MT7925&id=623937911339&latitude=22.297238&longitude=114.178614"
    "&mi_id=0000SvBf3YRkKCiHmRNQnYczrZtp_jQdjMfTwXIytdfr0J0%2C0000SvBf3YRkKCiHmRNQnYczrZtp_jQdjMfTwXIytdfr0J0"
    "&search_ver=ssr&sid=235d91a329625e3c6c997fcdd1252435&skuId=5455243929341"
    "&skuPriceType=3&ttid=600000%40taobao_android_10.7.0&upStreamPrice=8500&xxc=taobaoSearch"
)
TITLE = "MT7925 WIFI7千兆5G/6G三双频内置M.2无线网卡5.4蓝牙BE200 AX210"
BODY = (
    "用户评价 参数信息 图文详情 本店推荐 看了又看 "
    "用户评价·2 买家甲 2026-09-01 网卡很好用，连接稳定 "
    "买家乙 2026-09-02 安装简单，速度满意 查看全部评价 "
    "参数信息 千兆 适用网络类型 M.2 网卡插口 是 是否无线 3000Mbps 传输速度 "
    "品牌 WTXUP 型号 MT7925 售后服务 店铺三包 适用场景 台式机 "
    "无线协议 802.11be 频段类型 6GHz 成色 全新 图文详情"
)
RAW = {
    "title": "参数信息", "price_text": "¥35.00", "shop": "网特讯 WTXUP",
    "body_text": BODY, "body_text_all": BODY, "meta": {},
}


def make_page(url=CANONICAL, raw=None):
    page = Mock()
    page.url = url
    page.evaluate = AsyncMock(return_value=deepcopy(RAW if raw is None else raw))
    page.title = AsyncMock(return_value=TITLE + "- 淘宝网")
    page.locator.return_value.count = AsyncMock(return_value=1)
    page.locator.return_value.inner_text = AsyncMock(return_value=BODY)
    return page


class CanonicalTests(unittest.TestCase):
    def test_search_url_keeps_only_item_and_sku(self):
        self.assertEqual(_canonical_detail_url(ORIGINAL + "#tracking"), CANONICAL)

    def test_canonical_url_is_idempotent(self):
        self.assertEqual(_canonical_detail_url(CANONICAL), CANONICAL)

    def test_no_sku(self):
        self.assertEqual(
            _canonical_detail_url("https://item.taobao.com/item.htm?id=123&sid=abc"),
            "https://item.taobao.com/item.htm?id=123",
        )

    def test_unrelated_urls_unchanged(self):
        for url in (
            "https://item.jd.com/123.html?skuId=456",
            "https://detail.tmall.com/item.htm?id=123&skuId=456&sid=abc",
            "https://s.taobao.com/search?id=123&skuId=456",
            "https://item.taobao.com/item.htm?skuId=456&sid=abc",
        ):
            with self.subTest(url=url):
                self.assertEqual(_canonical_detail_url(url), url)


class MetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_metadata_survives_redirect_losing_all_query(self):
        page = make_page("https://item.taobao.com/item.htm")
        result = await extract_product_detail(page, "taobao", original_url=ORIGINAL)
        self.assertEqual(result["price"], 85.0)
        self.assertEqual(result["price_text"], "¥85.00")
        self.assertEqual(result["price_source"], "url_upStreamPrice")
        self.assertEqual(result["selected_sku_id"], "5455243929341")
        self.assertEqual(result["title"], TITLE)
        self.assertEqual(result["shop"], "网特讯 WTXUP")
        self.assertEqual(len(result["product_parameters"]), 11)
        self.assertEqual(len(result["high_praise_reviews"]), 2)
        self.assertEqual(result["high_dissatisfied_reviews"], [])

    async def test_legacy_current_page_extraction(self):
        result = await extract_product_detail(make_page(ORIGINAL), "taobao")
        self.assertEqual(result["price"], 85.0)
        self.assertEqual(result["selected_sku_id"], "5455243929341")

    async def test_missing_or_invalid_original_price_uses_dom(self):
        for suffix in ("", "&upStreamPrice=oops", "&upStreamPrice=0", "&upStreamPrice=-1"):
            with self.subTest(suffix=suffix):
                result = await extract_product_detail(
                    make_page(), "taobao", original_url=CANONICAL + suffix
                )
                self.assertEqual(result["price"], 35.0)
                self.assertEqual(result["price_text"], "¥35.00")
                self.assertEqual(result["price_source"], "dom")
                self.assertEqual(result["selected_sku_id"], "5455243929341")

    async def test_metadata_does_not_leak_to_next_request(self):
        page = make_page()
        await extract_product_detail(page, "taobao", original_url=ORIGINAL)
        result = await extract_product_detail(
            page, "taobao", original_url="https://item.taobao.com/item.htm?id=789"
        )
        self.assertEqual(result["price"], 35.0)
        self.assertIsNone(result["selected_sku_id"])

    async def test_jd_does_not_use_taobao_price_metadata(self):
        result = await extract_product_detail(make_page(), "jd", original_url=ORIGINAL)
        self.assertEqual(result["price"], 35.0)
        self.assertIsNone(result["selected_sku_id"])


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = ShoppingBrowserService(Settings.from_env())
        self.page = make_page("https://item.taobao.com/item.htm?id=623937911339")
        self.browser = Mock()
        self.browser.lock = asyncio.Lock()
        self.browser.navigate = AsyncMock(return_value={})
        self.browser.get_page = AsyncMock(return_value=self.page)
        self.service.taobao_browser = self.browser
        self.service.jd_browser = self.browser
        self.service._prepare_product_detail_page = AsyncMock()

    async def test_end_to_end_service_contract_with_synthetic_dom(self):
        result = await self.service.get_product_detail(ORIGINAL)
        self.browser.navigate.assert_awaited_once_with(CANONICAL)
        self.assertEqual(result["original_url"], ORIGINAL)
        self.assertEqual(result["product_url"], self.page.url)
        self.assertEqual(result["price"], 85.0)
        self.assertEqual(result["selected_sku_id"], "5455243929341")
        self.assertEqual(result["title"], TITLE)
        self.assertEqual(result["shop"], "网特讯 WTXUP")
        self.assertEqual(len(result["product_parameters"]), 11)
        self.assertEqual(len(result["good_reviews"]), 2)
        self.assertEqual(result["bad_reviews"], [])
        self.assertFalse(result["requires_user_verification"])

    async def test_jd_navigation_unchanged(self):
        url = "https://item.jd.com/123.html?foo=bar"
        await self.service.get_product_detail(url)
        self.browser.navigate.assert_awaited_once_with(url)

    async def test_original_scheme_validated_before_canonicalizing(self):
        with self.assertRaises(SafetyError):
            await self.service.get_product_detail(ORIGINAL.replace("https://", "ftp://"))
        self.browser.navigate.assert_not_awaited()

    async def test_verification_gate_is_preserved(self):
        self.page.locator.return_value.inner_text = AsyncMock(return_value="请完成验证")
        with patch("jd_taobao_mcp.service.extract_product_detail", new_callable=AsyncMock) as extract:
            result = await self.service.get_product_detail(ORIGINAL)
        self.assertFalse(result["success"])
        self.assertTrue(result["requires_user_verification"])
        self.assertEqual(result["original_url"], ORIGINAL)
        self.service._prepare_product_detail_page.assert_not_awaited()
        extract.assert_not_awaited()


class MobileSearchCanonicalTests(unittest.TestCase):
    def test_mobile_search_url_canonicalizes_to_desktop_detail(self):
        url = (
            "https://new.m.taobao.com/detail.htm?"
            "id=623937911339"
            "&search_ver=ssr"
            "&sid=test"
            "&skuId=5455243929341"
            "&skuPriceType=3"
            "&upStreamPrice=8500"
            "&xxc=taobaoSearch"
        )

        self.assertEqual(
            _canonical_detail_url(url),
            "https://item.taobao.com/item.htm?"
            "id=623937911339&skuId=5455243929341",
        )

    def test_mobile_url_without_sku_keeps_only_item_id(self):
        url = (
            "https://new.m.taobao.com/detail.htm?"
            "id=623937911339&sid=test"
        )

        self.assertEqual(
            _canonical_detail_url(url),
            "https://item.taobao.com/item.htm?id=623937911339",
        )


class VisibleTextParameterTests(unittest.IsolatedAsyncioTestCase):
    async def test_visible_inner_text_preserves_summary_parameters(self):
        raw = deepcopy(RAW)

        # Real Taobao can preserve layout separators in innerText while
        # textContent collapses the summary-card boundaries.
        raw["body_text"] = BODY
        raw["body_text_all"] = BODY.replace(" ", "")

        result = await extract_product_detail(
            make_page(raw=raw),
            "taobao",
            original_url=ORIGINAL,
        )

        parameters = {
            item["name"]: item["value"]
            for item in result["product_parameters"]
        }

        self.assertEqual(
            parameters["\u9002\u7528\u7f51\u7edc\u7c7b\u578b"],
            "\u5343\u5146",
        )
        self.assertEqual(
            parameters["\u7f51\u5361\u63d2\u53e3"],
            "M.2",
        )
        self.assertEqual(
            parameters["\u662f\u5426\u65e0\u7ebf"],
            "\u662f",
        )
        self.assertEqual(
            parameters["\u4f20\u8f93\u901f\u5ea6"],
            "3000Mbps",
        )
        self.assertEqual(
            parameters["\u578b\u53f7"],
            "MT7925",
        )
        self.assertEqual(len(parameters), 11)


class RegionalAvailabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_hk_page_skips_taobao_tab_search(self):
        service = ShoppingBrowserService(Settings.from_env())

        page = Mock()
        body = Mock()
        body.inner_text = AsyncMock(
            return_value="\u8a72\u5546\u54c1\u4e2d\u570b\u9999\u6e2f\u4e0d\u53ef\u552e\u8ce3"
        )
        page.locator.return_value = body
        page.get_by_text = Mock()

        await service._prepare_taobao_detail_page(page)

        page.locator.assert_not_called()
        page.get_by_text.assert_not_called()


class TaobaoPreparationSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_taobao_page_without_tabs_never_wheel_scrolls(self):
        service = ShoppingBrowserService(Settings.from_env())

        page = Mock()

        body = Mock()
        body.inner_text = AsyncMock(return_value="normal product page")
        page.locator.return_value = body

        missing = Mock()
        missing.count = AsyncMock(return_value=0)
        page.get_by_text.return_value = missing

        page.mouse = Mock()
        page.mouse.wheel = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        await service._prepare_product_detail_page(page, "taobao")

        page.mouse.wheel.assert_not_awaited()
        page.get_by_text.assert_not_called()

    async def test_taobao_existing_tabs_do_not_use_wheel_scanning(self):
        service = ShoppingBrowserService(Settings.from_env())

        page = Mock()

        body = Mock()
        body.inner_text = AsyncMock(return_value="normal product page")
        page.locator.return_value = body

        node = Mock()
        node.is_visible = AsyncMock(return_value=True)
        node.scroll_into_view_if_needed = AsyncMock()
        node.click = AsyncMock()

        locator = Mock()
        locator.count = AsyncMock(return_value=1)
        locator.nth.return_value = node
        page.get_by_text.return_value = locator

        page.mouse = Mock()
        page.mouse.wheel = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        await service._prepare_product_detail_page(page, "taobao")

        page.mouse.wheel.assert_not_awaited()
        node.click.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
