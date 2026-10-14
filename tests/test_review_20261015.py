"""Offline review probes. Existing Fake Page and temporary Guard only."""
import unittest
from unittest.mock import AsyncMock, patch
import test_cross_platform_guard as fixtures
from jd_taobao_mcp.safety import SafetyError
from jd_taobao_mcp.taobao_guard import TaobaoNavigationGuard
from jd_taobao_mcp.extractors.detail import extract_product_detail


class NewReviewTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    def taobao(self):
        b = self.service.taobao_browser
        b._context = self.jd._context
        b._page = self.page
        b._start_unlocked = AsyncMock()
        self.page.url = fixtures.TAOBAO
        return b

    async def navigation(self, challenge):
        b = self.taobao()
        self.locator.inner_text.return_value = 'Normal product description. ' * 300 + (" 安全验证 CAPTCHA 请完成验证" if challenge else '')
        b._navigation_result = AsyncMock(return_value={'success': True})
        with patch.object(b._taobao_guard, 'reserve_navigation', wraps=b._taobao_guard.reserve_navigation) as reserve:
            try:
                await b.navigate('https://item.taobao.com/item.htm?id=999')
            except SafetyError:
                if not challenge:
                    raise
            self.assertEqual(reserve.call_count, 0 if challenge else 1)
            self.assertEqual(self.page.goto.await_count, 0 if challenge else 1)
        self.assertEqual(TaobaoNavigationGuard(b._taobao_guard.state_path).is_paused(), challenge)

    async def test_tail_challenge_before_navigation(self):
        await self.navigation(True)

    async def test_normal_long_page_navigation(self):
        await self.navigation(False)

    async def read_challenge(self, method, challenge, jd=False):
        b = self.jd if jd else self.taobao()
        b.settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.page.screenshot.return_value = b'synthetic'
        self.locator.inner_text.return_value = 'CAPTCHA 安全验证 请完成验证' if challenge else 'Normal product'
        guard = self.service.taobao_browser._taobao_guard
        with patch.object(guard, 'reserve_navigation') as reserve:
            try:
                await getattr(b, method)()
            except SafetyError:
                if jd or not challenge:
                    raise
            reserve.assert_not_called()
        self.page.goto.assert_not_awaited()
        self.assertEqual(TaobaoNavigationGuard(guard.state_path).is_paused(), challenge and not jd)

    async def test_same_url_status_challenge(self):
        await self.read_challenge('status', True)

    async def test_same_url_screenshot_challenge(self):
        await self.read_challenge('screenshot', True)

    async def test_normal_read_controls(self):
        for method in ('status', 'screenshot'):
            with self.subTest(method=method):
                await self.read_challenge(method, False)

    async def test_jd_read_not_taobao_paused(self):
        await self.read_challenge('status', True, jd=True)

    async def bulk(self, mode):
        self.page.url = 'https://search.jd.com/Search?keyword=synthetic'
        self.service._open_search_page = AsyncMock(return_value={})
        self.service._prepare_product_detail_page = AsyncMock()
        items = [{'url': 'https://item.jd.com/111.html', 'price': 10},
                 {'url': 'https://item.jd.com/222.html', 'price': 20}]
        async def nav(url):
            self.page.url = url
            return {}
        self.jd.navigate = AsyncMock(side_effect=nav)
        self.page.evaluate.return_value = {'has_product_identity': True, 'has_search_identity': True,
                                           'has_challenge_ui': False, 'outside_product_text': ''}
        async def detail(*args, **kwargs):
            if mode == 'login':
                self.page.url = 'https://passport.jd.com/new/login.aspx'
            elif mode == 'captcha':
                self.locator.inner_text.return_value = 'CAPTCHA 安全验证'
                self.page.evaluate.return_value = {'has_challenge_ui': True}
            else:
                self.locator.inner_text.return_value = '商品描述 安全验证 验证码错误'
            return {'title': 'Synthetic', 'price': 10}
        result = None
        with patch('jd_taobao_mcp.service.extract_jd_search', AsyncMock(return_value=items)), patch('jd_taobao_mcp.service.extract_product_detail', AsyncMock(side_effect=detail)):
            try:
                result = await self.service.search_products('jd', 'synthetic', include_details=True)
            except SafetyError:
                if mode == 'copy':
                    raise
        self.assertEqual(self.jd.navigate.await_count, 2 if mode == 'copy' else 1)
        if mode == 'copy':
            self.assertTrue(result['success'])
        elif result is not None:
            self.assertFalse(result['success'])
            self.assertTrue(result.get('requires_user_verification'))

    async def test_bulk_login_stops_next_item(self):
        await self.bulk('login')

    async def test_bulk_captcha_stops_next_item(self):
        await self.bulk('captcha')

    async def test_bulk_product_copy_control(self):
        await self.bulk('copy')

    async def identity(self, platform, change):
        initial = fixtures.TAOBAO if platform == 'taobao' else fixtures.JD
        self.page.url = initial
        self.page.evaluate.return_value = {'title': 'Original product', 'price_text': '99', 'url': initial}
        async def title():
            if change:
                self.page.url = 'https://item.taobao.com/item.htm?id=777' if platform == 'taobao' else 'https://item.jd.com/777.html'
            return 'Other product' if change else 'Original product'
        self.page.title.side_effect = title
        if change:
            with self.assertRaises(SafetyError):
                await extract_product_detail(self.page, platform)
        else:
            result = await extract_product_detail(self.page, platform)
            self.assertEqual(result['title'], 'Original product')

    async def test_changed_product_rejected(self):
        for platform in ('jd', 'taobao'):
            with self.subTest(platform=platform):
                await self.identity(platform, True)

    async def test_same_product_control(self):
        for platform in ('jd', 'taobao'):
            with self.subTest(platform=platform):
                await self.identity(platform, False)
