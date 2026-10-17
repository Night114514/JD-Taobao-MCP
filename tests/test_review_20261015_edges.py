"""Additional offline edge cases for the four confirmed findings."""
import unittest
from unittest.mock import AsyncMock, patch
import test_cross_platform_guard as fixtures
from jd_taobao_mcp.extractors.detail import _product_identity, extract_product_detail
from jd_taobao_mcp.safety import SafetyError, VerificationRequired
from jd_taobao_mcp.taobao_guard import TaobaoNavigationGuard


class InspectionEdges(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    def browser(self):
        b = self.service.taobao_browser
        b._context = self.jd._context
        b._page = self.page
        b._start_unlocked = AsyncMock()
        self.page.url = fixtures.TAOBAO
        b.settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.page.screenshot.return_value = b'synthetic'
        return b

    async def blocked_navigation(self):
        b = self.browser()
        with patch.object(b._taobao_guard, 'reserve_navigation') as reserve:
            with self.assertRaises(SafetyError):
                await b.navigate(fixtures.TAOBAO)
            reserve.assert_not_called()
        self.page.goto.assert_not_awaited()
        self.assertTrue(TaobaoNavigationGuard(b._taobao_guard.state_path).is_paused())

    async def test_dedicated_ui_without_text_blocks_navigation(self):
        self.locator.evaluate.return_value = True
        await self.blocked_navigation()

    async def test_oversized_inspection_is_not_safe(self):
        self.locator.inner_text.return_value = 'x' * 1_000_001
        await self.blocked_navigation()

    async def test_invalid_ui_scan_fails_closed(self):
        self.locator.evaluate.return_value = {'truncated': True}
        await self.blocked_navigation()

    async def test_ui_scan_failure_blocks_screenshot_file(self):
        b = self.browser()
        self.locator.evaluate.side_effect = RuntimeError('synthetic DOM lost')
        with self.assertRaises(SafetyError) as caught:
            await b.screenshot()
        self.assertIn('synthetic DOM lost', repr(caught.exception.__cause__))
        self.page.screenshot.assert_not_awaited()
        self.assertEqual(list(b.settings.artifacts_dir.iterdir()), [])
        self.assertTrue(TaobaoNavigationGuard(b._taobao_guard.state_path).is_paused())

    async def test_challenge_appearing_during_title_pauses(self):
        b = self.browser()
        async def title():
            self.locator.inner_text.return_value = 'CAPTCHA 安全验证'
            return 'Synthetic'
        self.page.title.side_effect = title
        await b.status()
        self.assertTrue(TaobaoNavigationGuard(b._taobao_guard.state_path).is_paused())
        self.page.goto.assert_not_awaited()

    async def test_post_screenshot_scan_failure_does_not_publish(self):
        b = self.browser()
        async def screenshot(**kwargs):
            self.locator.evaluate.side_effect = RuntimeError('synthetic post-read failure')
            return b'synthetic'
        self.page.screenshot.side_effect = screenshot
        with self.assertRaises(SafetyError):
            await b.screenshot()
        self.assertEqual(list(b.settings.artifacts_dir.iterdir()), [])
        self.assertTrue(TaobaoNavigationGuard(b._taobao_guard.state_path).is_paused())

    async def test_scan_and_pause_errors_both_preserved(self):
        b = self.browser()
        original = RuntimeError('synthetic DOM lost')
        self.locator.evaluate.side_effect = original
        with patch.object(b._taobao_guard, 'pause', side_effect=OSError('synthetic disk denied')):
            with self.assertRaises(RuntimeError) as caught:
                await b.screenshot()
        self.assertIs(caught.exception, original)
        self.assertIn('synthetic disk denied', repr(caught.exception.__cause__))
        self.assertEqual(list(b.settings.artifacts_dir.iterdir()), [])

    async def test_ordinary_item_error_continues(self):
        self.service.get_product_detail = AsyncMock(side_effect=[ValueError('synthetic bad data'), {'success': True}])
        items = [{'url': fixtures.JD}, {'url': 'https://item.jd.com/222.html'}]
        await self.service._enrich_search_results_with_details('jd', items)
        self.assertEqual(self.service.get_product_detail.await_count, 2)
        self.assertFalse(items[0]['detail_success'])
        self.assertTrue(items[1]['detail_success'])

    async def test_structured_verification_result_aborts(self):
        self.service.get_product_detail = AsyncMock(return_value={'success': False, 'requires_user_verification': True})
        with self.assertRaises(VerificationRequired):
            await self.service._enrich_search_results_with_details('jd', [{'url': fixtures.JD}, {'url': fixtures.JD}])
        self.service.get_product_detail.assert_awaited_once()

    async def test_evaluated_document_differs_even_if_url_returns(self):
        self.page.url = fixtures.JD
        self.page.evaluate.return_value = {'document_url': 'https://item.jd.com/222.html', 'title': 'Other'}
        with self.assertRaises(SafetyError):
            await extract_product_detail(self.page, 'jd')
        self.page.title.assert_not_awaited()

    async def test_tracking_change_during_title_is_allowed(self):
        self.page.url = fixtures.TAOBAO
        self.page.evaluate.return_value = {'document_url': fixtures.TAOBAO, 'title': 'Original'}
        async def title():
            self.page.url = fixtures.TAOBAO + '&spm=synthetic#details'
            return 'Original'
        self.page.title.side_effect = title
        result = await extract_product_detail(self.page, 'taobao')
        self.assertEqual(result['title'], 'Original')


class ProductIdentityTests(unittest.TestCase):
    def test_tracking_fragment_and_normalization(self):
        for first, second in [
            ('https://item.taobao.com/item.htm?id=1&skuId=2', 'http://ITEM.TAOBAO.COM./item.htm?spm=a&skuId=2&id=1#details'),
            ('https://item.jd.com/123.html', 'https://item.jd.com/123.html?utm_source=x#reviews'),
            ('https://detail.tmall.com/item.htm?id=1', 'https://detail.m.tmall.com/item.htm?id=1&spm=x'),
        ]:
            with self.subTest(first=first):
                self.assertEqual(_product_identity(first), _product_identity(second))

    def test_sku_item_and_marketplace_are_distinct(self):
        first = 'https://item.taobao.com/item.htm?id=1&skuId=2'
        for other in [first.replace('skuId=2', 'skuId=3'), first.replace('id=1&', 'id=9&'),
                      first.replace('item.taobao.com', 'detail.tmall.com'), first.replace('&skuId=2', '')]:
            with self.subTest(other=other):
                self.assertNotEqual(_product_identity(first), _product_identity(other))

    def test_conflicting_ids_fail_closed(self):
        for query in ('id=1&id=2', 'id=1&skuId=2&sku_id=3'):
            with self.subTest(query=query), self.assertRaises(SafetyError):
                _product_identity('https://item.taobao.com/item.htm?' + query)

    def test_unknown_pages_keep_query_identity(self):
        self.assertNotEqual(_product_identity('https://www.jd.com/path?a=1'),
                            _product_identity('https://www.jd.com/path?a=2'))
