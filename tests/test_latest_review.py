"""Offline latest review regressions; synthetic pages and temporary Guard only."""
import unittest
from unittest.mock import AsyncMock, patch

import test_cross_platform_guard as fixtures
from jd_taobao_mcp.extractors.detail import _fallback_reviews_from_text
from jd_taobao_mcp.safety import SafetyError
from jd_taobao_mcp.taobao_guard import TaobaoNavigationGuard

LOGIN = 'https://login.taobao.com/member/login.jhtml'
CAPTCHA = 'https://item.taobao.com/captcha'


class ElementPauseTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    async def check(self, *, url=fixtures.TAOBAO, text='Product', redirect=None,
                    operation='evaluate', failure=None, blocked=True, jd=False, pause_failure=False, elements=None):
        browser = self.jd if jd else self.service.taobao_browser
        browser._context = self.jd._context
        browser._page = self.page
        browser._start_unlocked = AsyncMock()
        self.page.url = url
        self.locator.inner_text.return_value = text
        self.page.evaluate.return_value = elements if elements is not None else [{'ref': 'e1', 'text': 'Synthetic'}]
        async def action(*args, **kwargs):
            if redirect:
                self.page.url = redirect
            if failure:
                raise failure
            return 'Synthetic' if operation == 'title' else [{'ref': 'e1', 'text': 'Synthetic'}]
        if redirect or failure:
            target = getattr(self.locator if operation in ('count', 'inner_text') else self.page, operation)
            target.side_effect = action
        guard = self.service.taobao_browser._taobao_guard
        with patch.object(guard, 'reserve_navigation') as reserve:
            if pause_failure:
                with patch.object(guard, 'pause', side_effect=OSError('synthetic disk unavailable')):
                    with self.assertRaises(Exception) as caught:
                        await browser.list_elements()
                diagnostic = repr(caught.exception) + repr(caught.exception.__cause__) + repr(getattr(caught.exception, '__notes__', []))
                self.assertIn('synthetic disk unavailable', diagnostic)
                self.assertFalse(TaobaoNavigationGuard(guard.state_path).is_paused())
            elif blocked:
                with self.assertRaises(Exception) as caught:
                    await browser.list_elements()
                if failure:
                    self.assertTrue(caught.exception is failure or caught.exception.__cause__ is failure)
                self.assertTrue(TaobaoNavigationGuard(guard.state_path).is_paused())
            else:
                result = await browser.list_elements()
                self.assertEqual(result['elements'], [{'ref': 'e1', 'text': 'Synthetic'}])
                self.assertFalse(TaobaoNavigationGuard(guard.state_path).is_paused())
            reserve.assert_not_called()
            self.page.goto.assert_not_awaited()
            self.page.go_back.assert_not_awaited()
            self.locator.click.assert_not_awaited()
            self.assertLessEqual(self.page.evaluate.await_count, 1)

    async def test_login_without_keywords(self):
        await self.check(url=LOGIN)

    async def test_same_platform_captcha(self):
        await self.check(url=CAPTCHA)

    async def test_normal_url_verification_body(self):
        await self.check(text='安全验证 请完成验证码')

    async def test_captcha_body_on_normal_url(self):
        await self.check(text='CAPTCHA 拖动下方滑块')

    async def test_captcha_element_without_body_words(self):
        await self.check(text='', elements=[{'ref': 'e1', 'name': 'captcha', 'aria_label': 'CAPTCHA'}])

    async def test_normal_read_does_not_clear_existing_pause(self):
        browser = self.service.taobao_browser
        browser._context = self.jd._context
        browser._page = self.page
        browser._start_unlocked = AsyncMock()
        self.page.url = fixtures.TAOBAO
        self.page.evaluate.return_value = []
        browser._taobao_guard.pause('synthetic existing pause')
        result = await browser.list_elements()
        self.assertEqual(result['elements'], [])
        self.assertTrue(TaobaoNavigationGuard(browser._taobao_guard.state_path).is_paused())

    async def test_cross_platform_redirect(self):
        await self.check(redirect=fixtures.JD)

    async def test_evaluate_redirect(self):
        await self.check(redirect=CAPTCHA)

    async def test_title_redirect(self):
        await self.check(redirect=LOGIN, operation='title')

    async def test_evaluate_failure(self):
        await self.check(failure=RuntimeError('synthetic evaluate reload'))

    async def test_body_count_failure(self):
        await self.check(operation='count', failure=RuntimeError('synthetic count reload'))

    async def test_body_text_failure(self):
        await self.check(operation='inner_text', failure=RuntimeError('synthetic text reload'))

    async def test_pause_write_failure_is_diagnostic(self):
        await self.check(url=LOGIN, pause_failure=True)

    async def test_pause_write_is_not_retried(self):
        browser = self.service.taobao_browser
        browser._context = self.jd._context
        browser._page = self.page
        browser._start_unlocked = AsyncMock()
        self.page.url = LOGIN
        with patch.object(browser._taobao_guard, 'pause', side_effect=OSError('synthetic write failed')) as pause:
            with self.assertRaises(Exception):
                await browser.list_elements()
            pause.assert_called_once()

    async def test_normal_taobao(self):
        await self.check(blocked=False)

    async def test_normal_jd(self):
        await self.check(url=fixtures.JD, blocked=False, jd=True)


class SearchContextTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    async def check(self, *, text='安全验证商品', challenge=False, outside='Search',
                    cards=True, url='https://search.jd.com/Search?keyword=fixture', platform='jd', blocked=False):
        self.page.url = url
        self.locator.inner_text.return_value = text
        self.page.evaluate.return_value = {'has_product_identity': False, 'has_search_identity': cards,
                                         'has_challenge_ui': challenge, 'outside_product_text': outside}
        browser = self.service._browser_for_platform(platform)
        browser.get_page = AsyncMock(return_value=self.page)
        self.service._open_search_page = AsyncMock(return_value={'success': True})
        with patch(f'jd_taobao_mcp.service.extract_{platform}_search', new_callable=AsyncMock,
                   return_value=[{'title': 'Fixture', 'product_url': fixtures.JD}]) as extract:
            if blocked and platform == 'jd':
                with self.assertRaises(SafetyError):
                    await self.service.search_products(platform, 'fixture', include_details=False)
            else:
                result = await self.service.search_products(platform, 'fixture', include_details=False)
                self.assertEqual(result['success'], not blocked)
                if not blocked:
                    self.assertEqual(len(result['items']), 1)
                else:
                    extract.assert_not_awaited()
        self.service._open_search_page.assert_awaited_once()
        self.page.goto.assert_not_awaited()

    async def test_search_title_mentions_verification(self):
        await self.check()

    async def test_search_snippet_mentions_error(self):
        await self.check(text='评论摘要 验证码错误')

    async def test_search_captcha_over_results(self):
        await self.check(challenge=True, blocked=True)

    async def test_search_login(self):
        await self.check(url='https://passport.jd.com/new/login.aspx', blocked=True)

    async def test_no_cards_with_verification_words(self):
        await self.check(cards=False, blocked=True)

    async def test_taobao_search_not_exempt(self):
        await self.check(platform='taobao', url=fixtures.TAOBAO, blocked=True)

    async def test_detail_does_not_accept_search_identity(self):
        self.page.url = fixtures.JD
        self.locator.inner_text.return_value = '安全验证'
        self.page.evaluate.return_value = {'has_product_identity': False, 'has_search_identity': True,
                                         'has_challenge_ui': False, 'outside_product_text': ''}
        with self.assertRaises(SafetyError):
            await self.service._assert_extraction_page(self.jd, self.page, 'jd')

    async def test_empty_search_without_risk_is_empty_success(self):
        self.page.url = 'https://search.jd.com/Search?keyword=fixture'
        self.locator.inner_text.return_value = ''
        self.jd.get_page = AsyncMock(return_value=self.page)
        self.service._open_search_page = AsyncMock(return_value={'success': True})
        with patch('jd_taobao_mcp.service.extract_jd_search', new_callable=AsyncMock, return_value=[]):
            result = await self.service.search_products('jd', 'fixture', include_details=False)
        self.assertTrue(result['success'])
        self.assertEqual(result['items'], [])

    async def test_detail_product_evidence_still_allowed(self):
        self.page.url = fixtures.JD
        self.locator.inner_text.return_value = '商品详情 安全验证'
        self.page.evaluate.return_value = {'has_product_identity': True, 'has_search_identity': False,
                                         'has_challenge_ui': False, 'outside_product_text': ''}
        await self.service._assert_extraction_page(self.jd, self.page, 'jd')

    async def test_taobao_detail_still_strict(self):
        self.page.url = fixtures.TAOBAO
        self.locator.inner_text.return_value = '商品详情 安全验证'
        with self.assertRaises(SafetyError):
            await self.service._assert_extraction_page(self.service.taobao_browser, self.page, 'taobao')
        guard = self.service.taobao_browser._taobao_guard
        self.assertTrue(TaobaoNavigationGuard(guard.state_path).is_paused())
