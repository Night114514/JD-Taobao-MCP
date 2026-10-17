import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

import server
from jd_taobao_mcp.config import Settings
from jd_taobao_mcp.service import ShoppingBrowserService


URL = "https://item.taobao.com/item.htm?id=123456"

RAW = {
    "title": "MT7925",
    "price_text": "85.00",
    "body_text": "",
    "body_text_all": "",
    "meta": {},
    "product_parameters": [
        {"name": "Model", "value": "DOM_MODEL"},
    ],
    "detail_product_parameters": [
        {"name": "Model", "value": "DETAIL_MODEL"},
    ],
    "json_ld": [{
        "@type": "Product",
        "additionalProperty": [
            {"name": "Model", "value": "JSON_MODEL"},
            {"name": "Bluetooth", "value": "5.4"},
        ],
    }],
}


class MCPIntegrationTests(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.page = Mock()
        self.page.url = URL
        self.page.title = AsyncMock(return_value="MT7925")
        self.page.evaluate = AsyncMock(return_value=RAW)

        body = Mock()
        body.count = AsyncMock(return_value=1)
        body.inner_text = AsyncMock(
            return_value="Ordinary product page"
        )
        self.page.locator.return_value = body
        self.page.mouse.wheel = AsyncMock()

        self.browser = Mock()
        self.browser.lock = asyncio.Lock()
        self.browser.navigate = AsyncMock(
            return_value={"url": URL}
        )
        self.browser.get_page = AsyncMock(
            return_value=self.page
        )
        self.browser.snapshot = AsyncMock(
            return_value={"url": URL}
        )

        self.service = ShoppingBrowserService(
            Settings.from_env()
        )
        self.service.taobao_browser = self.browser
        self.service.browser = self.browser
        self.service._prepare_product_detail_page = AsyncMock()

        self.service_patch = patch.object(
            server, "service", self.service
        )
        self.service_patch.start()
        self.addCleanup(self.service_patch.stop)

    async def test_mcp_tools_registered(self):
        tools = await server.mcp.list_tools()
        names = {tool.name for tool in tools}

        self.assertTrue({
            "get_product_detail",
            "search_products",
            "extract_current_page",
        }.issubset(names))

    async def test_mcp_tool_descriptions_explain_evidence(self):
        tools = await server.mcp.list_tools()
        by_name = {tool.name: tool for tool in tools}

        detail_description = (
            by_name["get_product_detail"].description or ""
        )
        self.assertIn(
            "product_parameter_evidence", detail_description
        )
        self.assertIn(
            "product_parameter_conflicts", detail_description
        )
        self.assertIn(
            "parameter_evidence_status", detail_description
        )

        search_description = (
            by_name["search_products"].description or ""
        )
        self.assertIn(
            "detail_output_contract", search_description
        )

        current_description = (
            by_name["extract_current_page"].description or ""
        )
        self.assertIn(
            "product_like_data", current_description
        )

    async def test_mcp_product_detail_output(self):
        result = await server.get_product_detail(URL)

        self.assertTrue(result["success"])
        self.assertEqual(
            result["parameter_evidence_status"], "provided"
        )

        model = next(
            p for p in result["product_parameter_evidence"]
            if p["name"] == "Model"
        )
        self.assertEqual(model["source"], "dom_parameters")

        self.assertTrue(
            result["product_parameter_conflicts"]
        )
        self.assertIn(
            "parameter_interpretation",
            result["detail_output_contract"],
        )

        json.dumps(result)
        self.browser.navigate.assert_awaited_once()
        self.page.goto.assert_not_called()

    async def test_mcp_verification_stops_extraction(self):
        self.page.locator.return_value.inner_text = AsyncMock(
            return_value="\u8bf7\u5b8c\u6210\u9a8c\u8bc1"
        )

        with patch(
            "jd_taobao_mcp.service.extract_product_detail",
            new_callable=AsyncMock,
        ) as extractor:
            result = await server.get_product_detail(URL)

        self.assertFalse(result["success"])
        self.assertTrue(
            result["requires_user_verification"]
        )
        self.assertEqual(
            result["parameter_evidence_status"],
            "not_extracted",
        )
        extractor.assert_not_awaited()
        self.service._prepare_product_detail_page.assert_not_awaited()

    async def test_mcp_search_respects_safe_mode(self):
        self.service._open_search_page = AsyncMock(
            return_value={
                "url": "https://s.m.taobao.com/h5?q=MT7925"
            }
        )
        self.service._enrich_search_results_with_details = (
            AsyncMock()
        )

        with patch(
            "jd_taobao_mcp.service.extract_taobao_search",
            new_callable=AsyncMock,
            return_value=[{
                "url": URL,
                "title": "MT7925",
                "price": 85.0,
            }],
        ):
            result = await server.search_products(
                platform="taobao",
                keyword="MT7925",
                max_results=5,
                include_details=True,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        self.assertTrue(
            result["filters"]["details_skipped_for_safety"]
        )
        self.assertIn(
            "parameter_source_priority",
            result["detail_output_contract"],
        )

        self.service._enrich_search_results_with_details.assert_not_awaited()
        self.page.mouse.wheel.assert_not_awaited()
        self.browser.navigate.assert_not_awaited()

    async def test_mcp_current_page_nested_output(self):
        result = await server.extract_current_page()

        self.assertTrue(result["success"])

        data = result["product_like_data"]
        self.assertEqual(
            data["parameter_evidence_status"], "provided"
        )
        self.assertTrue(
            data["product_parameter_conflicts"]
        )
        self.assertIn(
            "optional_fields",
            result["detail_output_contract"],
        )

        json.dumps(result)
        self.browser.navigate.assert_not_awaited()
        self.page.goto.assert_not_called()


if __name__ == "__main__":
    unittest.main()
