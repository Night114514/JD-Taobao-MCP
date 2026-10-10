"""Offline controller boundary regressions; reuse existing synthetic fixtures."""
import unittest
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace

import test_cross_platform_guard as fixtures
from jd_taobao_mcp.safety import SafetyError


class PlatformSymmetryTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    def taobao(self):
        browser = self.service.taobao_browser
        browser._context = self.jd._context
        browser._page = self.page
        browser._start_unlocked = AsyncMock()
        return browser

    async def test_taobao_rejects_jd_target_before_page_access(self):
        browser = self.taobao()
        self.page.url = fixtures.TAOBAO
        with self.assertRaises(SafetyError):
            await browser.navigate(fixtures.JD)
        browser._start_unlocked.assert_not_awaited()
        self.page.goto.assert_not_awaited()

    async def test_taobao_foreign_current_page_blocks_read_and_navigation(self):
        browser = self.taobao()
        self.page.url = fixtures.JD
        for action in (browser.get_page, browser.snapshot, browser.list_elements,
                       browser.screenshot, browser.status,
                       lambda: browser.check_login("taobao"),
                       lambda: browser.navigate(fixtures.TAOBAO)):
            with self.subTest(action=action), self.assertRaises(SafetyError):
                await action()
        self.page.goto.assert_not_awaited()
        self.page.evaluate.assert_not_awaited()

    async def test_taobao_redirect_to_jd_is_rejected_and_paused(self):
        browser = self.taobao()
        self.page.url = fixtures.TAOBAO
        async def redirect(*args, **kwargs):
            self.page.url = fixtures.JD
            return SimpleNamespace(status=200)
        self.page.goto.side_effect = redirect
        with self.assertRaises(SafetyError):
            await browser.navigate(fixtures.TAOBAO)
        self.assertTrue(browser._taobao_guard.is_paused())
        self.page.go_back.assert_not_awaited()

    async def test_foreign_popup_selected_after_closed_page_is_rejected_both_ways(self):
        for browser, source, target in (
            (self.jd, fixtures.JD, fixtures.TAOBAO),
            (self.taobao(), fixtures.TAOBAO, fixtures.JD),
        ):
            with self.subTest(source=source):
                self.page.url = source
                self.page.is_closed.return_value = True
                popup = Mock(url=target)
                popup.is_closed.return_value = False
                browser._page = self.page
                browser._context = Mock(pages=[self.page, popup])
                with self.assertRaises(SafetyError):
                    await browser.get_page()

    async def test_tmall_navigation_remains_within_taobao_controller(self):
        browser = self.taobao()
        self.page.url = fixtures.TAOBAO
        self.assertTrue((await browser.navigate(fixtures.TMALL))["success"])
        self.assertFalse(browser._taobao_guard.is_paused())

    async def test_taobao_interactions_remain_blocked_on_normal_page(self):
        browser = self.taobao()
        self.page.url = fixtures.TAOBAO
        for action in (browser.scroll, browser.go_back,
                       lambda: browser.click("e1"),
                       lambda: browser.type_text("e1", "synthetic")):
            with self.subTest(action=action), self.assertRaises(SafetyError):
                await action()
        self.page.mouse.wheel.assert_not_awaited()
        self.page.go_back.assert_not_awaited()
