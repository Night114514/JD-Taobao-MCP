import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from jd_taobao_mcp.config import Settings
from jd_taobao_mcp.service import ShoppingBrowserService


class TaobaoSafeModeTests(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.service = ShoppingBrowserService(Settings.from_env())

        self.page = Mock()
        self.page.url = "https://s.m.taobao.com/h5?q=MT7925"

        self.body = Mock()
        self.body.count = AsyncMock(return_value=1)
        self.body.inner_text = AsyncMock(return_value="Product listing")
        self.page.locator.return_value = self.body

        self.page.mouse.wheel = AsyncMock()
        self.page.wait_for_timeout = AsyncMock()

        self.browser = Mock()
        self.browser.lock = asyncio.Lock()
        self.browser.get_page = AsyncMock(return_value=self.page)
        self.browser.navigate = AsyncMock(return_value={
            "url": self.page.url,
            "requires_user_verification": False,
        })

        self.service._browser_for_platform = Mock(
            return_value=self.browser
        )

    async def test_search_does_not_scroll_or_enrich(self):
        self.service._open_search_page = AsyncMock(return_value={
            "url": self.page.url
        })
        self.service._enrich_search_results_with_details = AsyncMock()

        with (
            patch(
                "jd_taobao_mcp.service.extract_taobao_search",
                new_callable=AsyncMock,
                return_value=[{
                    "url": "https://item.taobao.com/item.htm?id=123456",
                    "price": 85.0,
                }],
            ) as extractor,
            patch(
                "jd_taobao_mcp.service.page_requires_user_verification",
                return_value=False,
            ),
        ):
            result = await self.service.search_products(
                "taobao",
                "MT7925",
                max_results=5,
                include_details=True,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        self.assertFalse(result["filters"]["include_details"])
        self.assertTrue(
            result["filters"]["details_skipped_for_safety"]
        )

        extractor.assert_awaited_once()
        self.page.mouse.wheel.assert_not_awaited()
        self.service._enrich_search_results_with_details.assert_not_awaited()

    async def test_verification_stops_before_extraction(self):
        self.service._open_search_page = AsyncMock(return_value={
            "url": self.page.url
        })

        with (
            patch(
                "jd_taobao_mcp.service.extract_taobao_search",
                new_callable=AsyncMock,
            ) as extractor,
            patch(
                "jd_taobao_mcp.service.page_requires_user_verification",
                return_value=True,
            ),
        ):
            result = await self.service.search_products(
                "taobao", "MT7925"
            )

        self.assertFalse(result["success"])
        self.assertTrue(result["requires_user_verification"])
        self.assertEqual(result["items"], [])
        self.page.mouse.wheel.assert_not_awaited()
        extractor.assert_not_awaited()

    async def test_hk_unavailable_is_reported(self):
        self.page.url = (
            "https://item.taobao.com/item.htm"
            "?id=593072983337&skuId=4186625228927"
        )

        unavailable = (
            "\u8a72\u5546\u54c1\u4e2d\u570b"
            "\u9999\u6e2f\u4e0d\u53ef\u552e\u8ce3"
        )

        self.body.inner_text = AsyncMock(
            return_value="Logitech M185 " + unavailable
        )
        self.service._prepare_product_detail_page = AsyncMock()

        with (
            patch(
                "jd_taobao_mcp.service.extract_product_detail",
                new_callable=AsyncMock,
                return_value={
                    "platform": "taobao",
                    "url": self.page.url,
                    "title": "Logitech M185",
                    "price": 39.0,
                    "product_parameters": [],
                    "good_reviews": [],
                    "bad_reviews": [],
                },
            ) as extractor,
            patch(
                "jd_taobao_mcp.service.page_requires_user_verification",
                return_value=False,
            ),
        ):
            result = await self.service.get_product_detail(
                self.page.url
            )

        self.assertTrue(result["success"])
        self.assertEqual(
            result["availability_status"],
            "unavailable_for_region",
        )
        self.assertEqual(
            result["availability_message"],
            unavailable,
        )

        self.browser.navigate.assert_awaited_once()
        self.page.mouse.wheel.assert_not_awaited()
        extractor.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
