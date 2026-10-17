import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from jd_taobao_mcp.config import Settings
from jd_taobao_mcp.service import (
    ShoppingBrowserService,
    _apply_detail_output_contract,
    _detail_output_contract,
    _empty_detail_contract_fields,
)


URL = "https://item.taobao.com/item.htm?id=123456"


class OutputContractTests(unittest.TestCase):

    def test_taobao_evidence_preserved(self):
        evidence = [{
            "name": "Model",
            "value": "MT7925",
            "source": "visible_text",
            "corroborated_by": ["dom_parameters"],
        }]
        conflicts = [{
            "name": "Model",
            "selected_value": "MT7925",
            "selected_source": "visible_text",
            "alternatives": [{
                "source": "json_ld",
                "value": "OTHER",
            }],
        }]

        detail = {
            "platform": "taobao",
            "product_parameters": [{
                "name": "Model",
                "value": "MT7925",
            }],
            "product_parameter_evidence": evidence,
            "product_parameter_conflicts": conflicts,
        }

        _apply_detail_output_contract(detail)

        self.assertEqual(
            detail["parameter_evidence_status"], "provided"
        )
        self.assertEqual(
            detail["product_parameter_evidence"], evidence
        )
        self.assertEqual(
            detail["product_parameter_conflicts"], conflicts
        )
        self.assertIn(
            "product_parameter_evidence",
            detail["detail_output_contract"]["optional_fields"],
        )

    def test_missing_evidence_is_not_fabricated(self):
        detail = {
            "platform": "taobao",
            "product_parameters": [{
                "name": "Model",
                "value": "MT7925",
            }],
        }

        _apply_detail_output_contract(detail)

        self.assertEqual(
            detail["parameter_evidence_status"],
            "not_provided",
        )
        self.assertNotIn(
            "product_parameter_conflicts", detail
        )

    def test_empty_observed_evidence_is_distinct(self):
        detail = {
            "platform": "taobao",
            "product_parameters": [],
            "product_parameter_evidence": [],
            "product_parameter_conflicts": [],
        }

        _apply_detail_output_contract(detail)

        self.assertEqual(
            detail["parameter_evidence_status"], "provided"
        )
        self.assertFalse(
            detail["product_parameters_status"]["complete"]
        )

    def test_verification_has_explicit_status(self):
        fields = _empty_detail_contract_fields(
            "requires_user_verification",
            product_url=URL,
            platform="taobao",
        )

        self.assertEqual(
            fields["parameter_evidence_status"],
            "not_extracted",
        )
        self.assertNotIn(
            "product_parameter_evidence", fields
        )
        self.assertEqual(
            fields["product_parameters_status"]["reason"],
            "requires_user_verification",
        )

    def test_jd_contract_unchanged(self):
        detail = {
            "platform": "jd",
            "product_parameters": [],
        }

        _apply_detail_output_contract(detail)

        self.assertNotIn(
            "parameter_evidence_status", detail
        )
        self.assertNotIn(
            "optional_fields",
            detail["detail_output_contract"],
        )

        self.assertEqual(
            detail["detail_output_contract"],
            _detail_output_contract("jd"),
        )
        self.assertEqual(
            detail["detail_output_contract"]["empty_field_policy"],
            "Required fields are always present. Missing or partial fields include "
            "a status.reason explaining verification, visibility, or extraction limits.",
        )


class ServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):

    async def test_detail_service_propagates_evidence(self):
        service = ShoppingBrowserService(Settings.from_env())

        page = Mock()
        page.url = URL
        body = Mock()
        body.count = AsyncMock(return_value=1)
        body.inner_text = AsyncMock(
            return_value="Ordinary product page"
        )
        page.locator.return_value = body

        browser = Mock()
        browser.lock = asyncio.Lock()
        browser.navigate = AsyncMock(
            return_value={"url": URL}
        )
        browser.get_page = AsyncMock(return_value=page)

        service.taobao_browser = browser
        service._prepare_product_detail_page = AsyncMock()

        detail = {
            "platform": "taobao",
            "url": URL,
            "product_parameters": [{
                "name": "Model",
                "value": "MT7925",
            }],
            "product_parameter_evidence": [{
                "name": "Model",
                "value": "MT7925",
                "source": "visible_text",
                "corroborated_by": [],
            }],
            "product_parameter_conflicts": [],
        }

        with patch(
            "jd_taobao_mcp.service.extract_product_detail",
            new_callable=AsyncMock,
            return_value=detail,
        ) as extractor:
            result = await service.get_product_detail(URL)

        self.assertTrue(result["success"])
        self.assertEqual(
            result["parameter_evidence_status"], "provided"
        )
        self.assertEqual(
            result["product_parameter_conflicts"], []
        )
        self.assertIn(
            "parameter_source_priority",
            result["detail_output_contract"],
        )

        json.dumps(result)
        browser.navigate.assert_awaited_once_with(URL)
        extractor.assert_awaited_once()
        page.goto.assert_not_called()


if __name__ == "__main__":
    unittest.main()
