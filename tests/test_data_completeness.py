import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

from jd_taobao_mcp.extractors.detail import extract_product_detail


URL = "https://item.taobao.com/item.htm?id=123456"

BODY = (
    "\u7528\u6237\u8bc4\u4ef7 "
    "\u53c2\u6570\u4fe1\u606f \u56fe\u6587\u8be6\u60c5 "
    "\u53c2\u6570\u4fe1\u606f "
    "\u5343\u5146 \u9002\u7528\u7f51\u7edc\u7c7b\u578b "
    "M.2 \u7f51\u5361\u63d2\u53e3 "
    "\u662f \u662f\u5426\u65e0\u7ebf "
    "3000Mbps \u4f20\u8f93\u901f\u5ea6 "
    "\u54c1\u724c WTXUP "
    "\u578b\u53f7 MT7925 "
    "\u552e\u540e\u670d\u52a1 \u5e97\u94fa\u4e09\u5305 "
    "\u9002\u7528\u573a\u666f \u53f0\u5f0f\u673a "
    "\u65e0\u7ebf\u534f\u8bae 802.11be "
    "\u9891\u6bb5\u7c7b\u578b 6GHz "
    "\u6210\u8272 \u5168\u65b0 "
    "\u56fe\u6587\u8be6\u60c5"
)

MODEL = "\u578b\u53f7"
INTERFACE = "\u63a5\u53e3\u7c7b\u578b"
BLUETOOTH = "\u84dd\u7259\u7248\u672c"


def make_raw():
    return {
        "title": "MT7925",
        "price_text": "\u00a585.00",
        "body_text": BODY,
        "body_text_all": BODY,
        "meta": {},
        "product_parameters": [],
        "detail_product_parameters": [],
        "json_ld": [],
    }


def make_page(raw):
    page = Mock()
    page.url = URL
    page.title = AsyncMock(return_value="MT7925")
    page.evaluate = AsyncMock(return_value=deepcopy(raw))
    return page


class DataCompletenessTests(unittest.IsolatedAsyncioTestCase):

    async def test_visible_and_dom_parameters_merge(self):
        raw = make_raw()
        raw["product_parameters"] = [
            {
                "name": INTERFACE,
                "value": "M.2 PCIe",
                "group": "DOM",
            },
            {
                "name": MODEL,
                "value": "INCORRECT",
                "group": "DOM",
            },
        ]

        result = await extract_product_detail(
            make_page(raw), "taobao"
        )
        values = {
            p["name"]: p["value"]
            for p in result["product_parameters"]
        }

        self.assertEqual(values[MODEL], "MT7925")
        self.assertEqual(values[INTERFACE], "M.2 PCIe")

    async def test_json_ld_adds_missing_parameters(self):
        raw = make_raw()
        raw["json_ld"] = [{
            "@type": "Product",
            "name": "MT7925",
            "additionalProperty": [
                {"name": BLUETOOTH, "value": "5.4"},
                {"name": MODEL, "value": "INCORRECT"},
            ],
        }]

        result = await extract_product_detail(
            make_page(raw), "taobao"
        )
        values = {
            p["name"]: p["value"]
            for p in result["product_parameters"]
        }

        self.assertEqual(values[MODEL], "MT7925")
        self.assertEqual(values[BLUETOOTH], "5.4")

    async def test_invalid_json_ld_properties_ignored(self):
        raw = make_raw()
        raw["body_text"] = ""
        raw["body_text_all"] = ""
        raw["json_ld"] = [{
            "@type": "Product",
            "additionalProperty": [
                {"name": BLUETOOTH, "value": "5.4"},
                {"name": "invalid", "value": {"nested": 1}},
                {"name": "flag", "value": True},
            ],
        }]

        result = await extract_product_detail(
            make_page(raw), "taobao"
        )
        values = {
            p["name"]: p["value"]
            for p in result["product_parameters"]
        }

        self.assertEqual(values, {BLUETOOTH: "5.4"})


    async def test_source_priority_and_duplicates(self):
        raw = make_raw()

        raw["product_parameters"] = [
            {"name": MODEL, "value": "DOM_WRONG"},
            {"name": INTERFACE, "value": "M.2 PCIe"},
        ]
        raw["detail_product_parameters"] = [
            {"name": MODEL, "value": "DETAIL_WRONG"},
            {"name": BLUETOOTH, "value": "5.2"},
        ]
        raw["json_ld"] = [{
            "@type": "Product",
            "additionalProperty": [
                {"name": MODEL, "value": "JSON_WRONG"},
                {"name": INTERFACE, "value": "USB"},
                {"name": BLUETOOTH, "value": "5.1"},
            ],
        }]

        result = await extract_product_detail(
            make_page(raw), "taobao"
        )
        parameters = result["product_parameters"]

        values = {
            item["name"]: item["value"]
            for item in parameters
        }

        self.assertEqual(values[MODEL], "MT7925")
        self.assertEqual(values[INTERFACE], "M.2 PCIe")
        self.assertEqual(values[BLUETOOTH], "5.2")

        names = [item["name"] for item in parameters]
        self.assertEqual(len(names), len(set(names)))

    async def test_dom_priority_when_visible_text_missing(self):
        raw = make_raw()
        raw["body_text"] = ""
        raw["body_text_all"] = ""

        raw["product_parameters"] = [
            {"name": MODEL, "value": "DOM_MODEL"},
        ]
        raw["detail_product_parameters"] = [
            {"name": MODEL, "value": "DETAIL_MODEL"},
        ]
        raw["json_ld"] = [{
            "@type": "Product",
            "additionalProperty": [
                {"name": MODEL, "value": "JSON_MODEL"},
                {"name": BLUETOOTH, "value": "5.4"},
            ],
        }]

        page = make_page(raw)
        result = await extract_product_detail(page, "taobao")

        values = {
            item["name"]: item["value"]
            for item in result["product_parameters"]
        }

        self.assertEqual(values[MODEL], "DOM_MODEL")
        self.assertEqual(values[BLUETOOTH], "5.4")
        page.evaluate.assert_awaited_once()
        page.goto.assert_not_called()


    async def test_parameter_evidence_and_conflicts(self):
        raw = make_raw()
        raw["product_parameters"] = [
            {"name": MODEL, "value": "DIFFERENT_MODEL"},
            {"name": INTERFACE, "value": "M.2 PCIe"},
        ]
        raw["json_ld"] = [{
            "@type": "Product",
            "additionalProperty": [
                {"name": BLUETOOTH, "value": "5.4"},
            ],
        }]

        result = await extract_product_detail(
            make_page(raw), "taobao"
        )

        evidence = {
            item["name"]: item
            for item in result["product_parameter_evidence"]
        }

        self.assertEqual(
            evidence[MODEL]["source"], "visible_text"
        )
        self.assertEqual(
            evidence[INTERFACE]["source"], "dom_parameters"
        )
        self.assertEqual(
            evidence[BLUETOOTH]["source"], "json_ld"
        )

        conflicts = result["product_parameter_conflicts"]
        model_conflict = next(
            c for c in conflicts if c["name"] == MODEL
        )

        self.assertEqual(
            model_conflict["selected_value"], "MT7925"
        )
        self.assertIn(
            {
                "source": "dom_parameters",
                "value": "DIFFERENT_MODEL",
            },
            model_conflict["alternatives"],
        )

    async def test_matching_sources_not_conflicts(self):
        raw = make_raw()
        raw["product_parameters"] = [
            {"name": MODEL, "value": "MT7925"},
        ]
        raw["json_ld"] = [{
            "@type": "Product",
            "additionalProperty": [
                {"name": MODEL, "value": "MT7925"},
            ],
        }]

        result = await extract_product_detail(
            make_page(raw), "taobao"
        )

        model = next(
            item
            for item in result["product_parameter_evidence"]
            if item["name"] == MODEL
        )

        self.assertEqual(model["source"], "visible_text")
        self.assertIn(
            "dom_parameters", model["corroborated_by"]
        )
        self.assertIn(
            "json_ld", model["corroborated_by"]
        )
        self.assertEqual(
            result["product_parameter_conflicts"], []
        )

    async def test_dom_conflict_without_visible_text(self):
        raw = make_raw()
        raw["body_text"] = ""
        raw["body_text_all"] = ""

        raw["product_parameters"] = [
            {"name": MODEL, "value": "DOM_MODEL"},
        ]
        raw["detail_product_parameters"] = [
            {"name": MODEL, "value": "DETAIL_MODEL"},
        ]

        result = await extract_product_detail(
            make_page(raw), "taobao"
        )

        model = next(
            item
            for item in result["product_parameter_evidence"]
            if item["name"] == MODEL
        )

        self.assertEqual(model["value"], "DOM_MODEL")
        self.assertEqual(model["source"], "dom_parameters")

        conflict = result["product_parameter_conflicts"][0]
        self.assertIn(
            {
                "source": "dom_detail",
                "value": "DETAIL_MODEL",
            },
            conflict["alternatives"],
        )

    async def test_jd_output_contract_unchanged(self):
        result = await extract_product_detail(
            make_page(make_raw()), "jd"
        )

        self.assertNotIn(
            "product_parameter_evidence", result
        )
        self.assertNotIn(
            "product_parameter_conflicts", result
        )


if __name__ == "__main__":
    unittest.main()
