import json
import unittest

from jd_taobao_mcp.extractors.detail import extract_product_detail
from jd_taobao_mcp.service import _apply_detail_output_contract, _detail_output_contract
from test_data_completeness import BODY, MODEL, make_page, make_raw


class TextSourceEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_hidden_only_parameter_has_text_content_source(self):
        raw = make_raw()
        raw["body_text"] = "Ordinary product page"
        result = await extract_product_detail(make_page(raw), "taobao")
        model = next(p for p in result["product_parameter_evidence"] if p["name"] == MODEL)
        self.assertEqual(model["source"], "text_content")
        self.assertEqual(model["value"], "MT7925")
        json.dumps(result, allow_nan=False)

    async def test_visible_and_text_content_conflict_is_retained(self):
        raw = make_raw()
        raw["body_text_all"] = BODY.replace("MT7925", "HIDDEN_OTHER")
        result = await extract_product_detail(make_page(raw), "taobao")
        model = next(p for p in result["product_parameters"] if p["name"] == MODEL)
        self.assertEqual(model["value"], "MT7925")
        conflict = next((p for p in result["product_parameter_conflicts"] if p["name"] == MODEL), None)
        self.assertIsNotNone(conflict, "The hidden conflicting value was discarded")
        self.assertEqual(conflict["selected_source"], "visible_text")
        self.assertIn({"source": "text_content", "value": "HIDDEN_OTHER"}, conflict["alternatives"])

    async def test_hidden_text_does_not_override_dom_or_lose_conflict(self):
        raw = make_raw()
        raw["body_text"] = "Product"
        raw["product_parameters"] = [{"name": MODEL, "value": "DOM_MODEL"}]
        result = await extract_product_detail(make_page(raw), "taobao")
        model = next(p for p in result["product_parameter_evidence"] if p["name"] == MODEL)
        self.assertEqual(model["source"], "dom_parameters")
        self.assertEqual(model["value"], "DOM_MODEL")
        conflict = next(p for p in result["product_parameter_conflicts"] if p["name"] == MODEL)
        self.assertIn({"source": "text_content", "value": "MT7925"}, conflict["alternatives"])

    async def test_missing_text_content_does_not_fabricate_corroboration(self):
        raw = make_raw()
        raw.pop("body_text_all")
        result = await extract_product_detail(make_page(raw), "taobao")
        for item in result["product_parameter_evidence"]:
            self.assertNotIn("text_content", item["corroborated_by"])

    async def test_matching_text_sources_are_same_page_agreement_only(self):
        result = await extract_product_detail(make_page(make_raw()), "taobao")
        self.assertEqual(result["product_parameter_conflicts"], [])
        model = next(p for p in result["product_parameter_evidence"] if p["name"] == MODEL)
        self.assertEqual(model["source"], "visible_text")
        self.assertIn("text_content", model["corroborated_by"])
        _apply_detail_output_contract(result)
        self.assertEqual(result["parameter_evidence_status"], "provided")
        self.assertIn("not independent", result["detail_output_contract"]["parameter_interpretation"]["corroborated_by"])

    def test_contract_adds_source_without_removing_legacy_fields_or_statuses(self):
        contract = _detail_output_contract("taobao")
        priority = contract["parameter_source_priority"]
        self.assertIn("text_content", priority)
        self.assertEqual([p for p in priority if p != "text_content"],
                         ["visible_text", "dom_parameters", "dom_detail", "json_ld", "fallback_text"])
        self.assertEqual(set(contract["parameter_evidence_status_values"]),
                         {"provided", "not_provided", "not_extracted"})
        self.assertEqual(contract["required_fields"], [
            "product_url", "product_parameters", "good_reviews", "bad_reviews",
            "product_parameters_status", "good_reviews_status", "bad_reviews_status",
        ])


if __name__ == "__main__":
    unittest.main()
