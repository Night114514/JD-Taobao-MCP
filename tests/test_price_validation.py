import json
import unittest

from jd_taobao_mcp.extractors.detail import extract_product_detail, _taobao_price_from_url
from test_detail_navigation import make_page


URL = "https://item.taobao.com/item.htm?id=123456&skuId=654321"
INVALID = ("NaN", "nan", "Infinity", "inf", "-Infinity", "1e999", "-1e999", "bad", "0", "-5")


class PriceValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_nonfinite_prices_do_not_override_dom_and_serialize_strictly(self):
        for value in INVALID:
            with self.subTest(value=value):
                result = await extract_product_detail(make_page(), "taobao", original_url=URL + "&upStreamPrice=" + value)
                self.assertEqual(result["price"], 35.0)
                self.assertEqual(result["price_source"], "dom")
                self.assertEqual(result["selected_sku_id"], "654321")
                json.dumps(result, allow_nan=False)

    async def test_finite_positive_metadata_keeps_existing_contract(self):
        result = await extract_product_detail(make_page(), "taobao", original_url=URL + "&upStreamPrice=8500")
        self.assertEqual(result["price"], 85.0)
        self.assertEqual(result["price_source"], "url_upStreamPrice")
        json.dumps(result, allow_nan=False)

    def test_parser_rejects_nonfinite_values_and_keeps_sku(self):
        for value in INVALID:
            with self.subTest(value=value):
                self.assertEqual(_taobao_price_from_url(URL + "&upStreamPrice=" + value), (None, "654321"))


if __name__ == "__main__":
    unittest.main()
