"""Offline RED probes: no real socket, process, browser, or account operations."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import test_cross_platform_guard as fixtures
from jd_taobao_mcp.safety import SafetyError
from jd_taobao_mcp.service import _canonical_detail_url
from jd_taobao_mcp.extractors.detail import _product_identity
from jd_taobao_mcp.taobao_guard import TaobaoNavigationGuard
from scripts.ci_offline_tests import OfflineGuard


class PageInspectionTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    def taobao(self):
        browser = self.service.taobao_browser
        browser._context = self.jd._context
        browser._page = self.page
        browser._start_unlocked = AsyncMock()
        browser._settle = AsyncMock()
        self.page.url = fixtures.TAOBAO
        return browser

    def assert_paused(self, browser):
        self.assertTrue(TaobaoNavigationGuard(browser._taobao_guard.state_path).is_paused())

    async def navigation_probe(self, challenge=False, scan_error=False, jd=False):
        browser = self.jd if jd else self.taobao()
        browser._settle = AsyncMock()
        target = fixtures.JD if jd else fixtures.TAOBAO

        async def goto(url, **kwargs):
            self.page.url = url
            self.locator.evaluate.return_value = challenge
            if scan_error:
                self.locator.evaluate.side_effect = RuntimeError('post-goto DOM lost')
            return SimpleNamespace(status=200)

        self.page.goto.side_effect = goto
        guard = self.service.taobao_browser._taobao_guard
        result = None
        with patch.object(guard, 'reserve_navigation', wraps=guard.reserve_navigation) as reserve:
            try:
                result = await browser.navigate(target)
            except SafetyError:
                if jd or not (challenge or scan_error):
                    raise
            self.assertEqual(reserve.call_count, 0 if jd else 1)
        self.page.goto.assert_awaited_once()
        if not jd and (challenge or scan_error):
            self.assert_paused(browser)
            if result is not None:
                self.assertTrue(result.get('requires_user_verification'))
                self.assertTrue(result.get('automation_paused'))
            self.locator.evaluate.side_effect = None
            self.locator.evaluate.return_value = False  # Manual completion never resumes.
            self.assert_paused(browser)
        else:
            self.assertTrue(result['success'])
            self.assertFalse(result['requires_user_verification'])
            self.assertFalse(TaobaoNavigationGuard(guard.state_path).is_paused())

    async def test_a_visible_control_after_goto(self):
        await self.navigation_probe(challenge=True)

    async def test_a_post_navigation_scan_error(self):
        await self.navigation_probe(scan_error=True)

    async def test_a_normal_or_hidden_control(self):
        # False is the production visibility predicate's output for hidden controls.
        await self.navigation_probe(challenge=False)

    async def test_a_jd_does_not_acquire_taobao_pause(self):
        await self.navigation_probe(challenge=True, jd=True)

    async def login_probe(self, mode):
        browser = self.taobao()
        self.jd._context.cookies.return_value = [{'name': 'tracknick', 'domain': '.taobao.com'}]
        if mode == 'missing':
            self.locator.count.return_value = 0
        elif mode == 'count_error':
            self.locator.count.side_effect = RuntimeError('body reload')
        elif mode == 'text_error':
            self.locator.inner_text.side_effect = RuntimeError('body text lost')
        elif mode == 'challenge':
            self.locator.evaluate.return_value = True
        result = None
        with patch.object(browser._taobao_guard, 'reserve_navigation') as reserve:
            try:
                result = await browser.check_login('taobao')
            except (SafetyError, RuntimeError):
                pass  # Error propagation is permitted; persistence is mandatory.
            reserve.assert_not_called()
        self.page.goto.assert_not_awaited()
        self.assert_paused(browser)
        if result is not None:
            self.assertFalse(result['likely_logged_in'])
            self.assertTrue(result['requires_user_verification'])

    async def test_b_missing_body_with_stale_cookie(self):
        await self.login_probe('missing')

    async def test_b_count_failure(self):
        await self.login_probe('count_error')

    async def test_b_text_failure(self):
        await self.login_probe('text_error')

    async def test_b_same_url_challenge_with_stale_cookie(self):
        await self.login_probe('challenge')

    async def test_b_inspection_and_pause_errors_remain_diagnosable(self):
        browser = self.taobao()
        original = RuntimeError('synthetic original DOM error')
        self.locator.inner_text.side_effect = original
        with patch.object(browser._taobao_guard, 'pause', side_effect=OSError('synthetic pause write error')) as pause:
            with self.assertRaises(Exception) as caught:
                await browser.check_login('taobao')
            pause.assert_called()
        seen = set()
        def diagnostics(error):
            if error is None or id(error) in seen:
                return ''
            seen.add(id(error))
            return repr(error) + repr(getattr(error, '__notes__', [])) + diagnostics(error.__cause__) + diagnostics(error.__context__)
        message = diagnostics(caught.exception)
        self.assertIn('synthetic original DOM error', message)
        self.assertIn('synthetic pause write error', message)
        self.page.goto.assert_not_awaited()

    async def test_b_normal_login_diagnostics(self):
        browser = self.taobao()
        for cookies, logged_in in [([], False), ([{'name': 'tracknick', 'domain': '.taobao.com'}], True)]:
            with self.subTest(logged_in=logged_in):
                self.jd._context.cookies.return_value = cookies
                result = await browser.check_login('taobao')
                self.assertEqual(result['likely_logged_in'], logged_in)
                self.assertFalse(result['requires_user_verification'])
                self.assertFalse(browser._taobao_guard.is_paused())
        self.page.goto.assert_not_awaited()

    async def test_b_about_blank_control(self):
        browser = self.taobao()
        self.page.url = 'about:blank'
        self.locator.count.return_value = 0
        result = await browser.check_login('taobao')
        self.assertFalse(result['likely_logged_in'])
        self.assertFalse(result['requires_user_verification'])
        self.assertFalse(browser._taobao_guard.is_paused())
        self.page.goto.assert_not_awaited()

    async def test_b_jd_control(self):
        self.jd._context.cookies.return_value = [{'name': 'pt_key', 'domain': '.jd.com'}]
        result = await self.jd.check_login('jd')
        self.assertTrue(result['likely_logged_in'])
        self.assertFalse(result['requires_user_verification'])
        self.assertFalse(self.service.taobao_browser._taobao_guard.is_paused())
        self.page.goto.assert_not_awaited()

    async def test_c_ambiguity_rejected_before_navigation(self):
        browser = self.taobao()
        browser.navigate = AsyncMock(side_effect=SafetyError('navigation sentinel'))
        for query in ('id=1&id=2', 'id=1&skuId=2&skuId=3', 'id=1&skuId=2&sku_id=3'):
            with self.subTest(query=query):
                browser.navigate.reset_mock()
                with self.assertRaises(SafetyError):
                    await self.service.get_product_detail('https://item.taobao.com/item.htm?' + query)
                browser.navigate.assert_not_awaited()


class CanonicalIdentityTests(unittest.TestCase):
    def test_c_conflicting_identifiers(self):
        for query in ('id=1&id=2', 'id=1&skuId=2&skuId=3', 'id=1&skuId=2&sku_id=3'):
            with self.subTest(query=query), self.assertRaises(SafetyError):
                _canonical_detail_url('https://item.taobao.com/item.htm?' + query)

    def test_c_repeated_equal_values_preserve_identity(self):
        url = 'https://item.taobao.com/item.htm?id=1&id=1&skuId=2&skuId=2&sku_id=2&spm=test#details'
        canonical = _canonical_detail_url(url)
        self.assertEqual(parse_qs(urlparse(canonical).query), {'id': ['1'], 'skuId': ['2']})
        self.assertEqual(_product_identity(url), _product_identity(canonical))

    def test_c_encoded_values_preserve_boundaries(self):
        canonical = _canonical_detail_url('https://new.m.taobao.com/detail.htm?id=1%26x%3D2&skuId=3%23part')
        self.assertEqual(parse_qs(urlparse(canonical).query), {'id': ['1&x=2'], 'skuId': ['3#part']})
        self.assertEqual(urlparse(canonical).fragment, '')

    def test_c_marketplaces_remain_distinct(self):
        taobao = _canonical_detail_url('https://item.taobao.com/item.htm?id=1&skuId=2')
        tmall = 'https://detail.tmall.com/item.htm?id=1&skuId=2'
        self.assertEqual(_canonical_detail_url(tmall), tmall)
        self.assertNotEqual(_product_identity(taobao), _product_identity(tmall))


class ChildAuditContractTests(unittest.TestCase):
    def setUp(self):
        # Extract the actual nested audit callback without executing main/importing server.
        source = Path(__file__).with_name('stdio_fixture_server.py')
        tree = ast.parse(source.read_text(encoding='utf-8'))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        audit = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == 'audit')
        self.blocked = []
        namespace = {'blocked': self.blocked}
        exec(compile(ast.Module(body=[audit], type_ignores=[]), str(source), 'exec'), namespace)
        self.child = namespace['audit']
        self.parent = OfflineGuard(Path('synthetic-unused-runtime'))

    def assert_denied(self, event, values):
        self.blocked.clear()
        with self.assertRaises(RuntimeError):
            self.parent.audit(event, values)
        with self.assertRaises(RuntimeError):
            self.child(event, values)
        self.assertIn(event, self.blocked)

    def test_d_process_events(self):
        for event, values in [('subprocess.Popen', ('fake', [], None, {})), ('os.system', ('fake',)),
                              ('os.exec', ('fake', [], {})), ('os.spawn', (0, 'fake', [], {})),
                              ('os.posix_spawn', ('fake', [], {}))]:
            with self.subTest(event=event):
                self.assert_denied(event, values)

    def test_d_network_events(self):
        for event, values in [('socket.connect', (None, ('192.0.2.1', 80))),
                              ('socket.bind', (None, ('0.0.0.0', 1234))),
                              ('socket.getaddrinfo', ('offline.invalid', 80, 0, 0, 0)),
                              ('socket.sendto', (None, ('127.0.0.1', 1234))),
                              ('socket.sendmsg', (None, ('127.0.0.1', 1234)))]:
            with self.subTest(event=event):
                self.assert_denied(event, values)

    def test_d_loopback_socketpair_controls(self):
        for host in ('127.0.0.1', '::1'):
            for event, values in [('socket.connect', (None, (host, 1234))), ('socket.bind', (None, (host, 0))),
                                  ('socket.getaddrinfo', (host, 0, 0, 0, 0))]:
                with self.subTest(host=host, event=event):
                    self.parent.audit(event, values)
                    self.child(event, values)
        self.assertEqual(self.blocked, [])

    def test_d_unrelated_event_control(self):
        self.parent.audit('synthetic.no_io', ())
        self.child('synthetic.no_io', ())
        self.assertEqual(self.blocked, [])
