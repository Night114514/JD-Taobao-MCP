"""Synthetic redirects during awaits; no browser or site access."""
import unittest
from unittest.mock import AsyncMock

import test_cross_platform_guard as fixtures
from jd_taobao_mcp.safety import SafetyError


class ReadonlyRaceTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    async def redirect_case(self, operation, trigger, value):
        # JD direction demonstrates post-operation gaps independently of P2 #1.
        self.page.url = fixtures.JD
        async def redirect(*args, **kwargs):
            self.page.url = fixtures.TAOBAO
            return value
        trigger.side_effect = redirect
        with self.assertRaises(SafetyError):
            await operation()

    async def test_list_elements_rejects_redirect_during_evaluate(self):
        await self.redirect_case(self.jd.list_elements, self.page.evaluate, [{"text": "foreign"}])

    async def test_list_elements_rejects_redirect_during_title(self):
        self.page.evaluate.return_value = []
        await self.redirect_case(self.jd.list_elements, self.page.title, "foreign")

    async def test_screenshot_rejects_redirect_without_publishing_artifact(self):
        self.jd.settings.artifacts_dir.mkdir(parents=True)
        await self.redirect_case(self.jd.screenshot, self.page.screenshot, b"synthetic")
        self.assertEqual(list(self.jd.settings.artifacts_dir.iterdir()), [])

    async def test_status_rejects_redirect_during_title(self):
        await self.redirect_case(self.jd.status, self.page.title, "foreign")

    async def test_login_status_rejects_redirect_during_cookie_read(self):
        await self.redirect_case(lambda: self.jd.check_login("jd"),
                                 self.jd._context.cookies, [])

    async def test_navigation_rejects_redirect_during_result_title(self):
        await self.redirect_case(lambda: self.jd.navigate(fixtures.JD),
                                 self.page.title, "foreign")

    async def test_scroll_rejects_redirect_during_position_read(self):
        await self.redirect_case(self.jd.scroll, self.page.evaluate, {"x": 0, "y": 0})

    async def test_back_rejects_redirect_during_title(self):
        await self.redirect_case(self.jd.go_back, self.page.title, "foreign")

    async def test_normal_readonly_tools_keep_results(self):
        self.page.evaluate.return_value = [{"ref": "e1"}]
        self.page.screenshot.return_value = b"synthetic"
        self.jd.settings.artifacts_dir.mkdir(parents=True)
        self.assertEqual((await self.jd.list_elements())["count"], 1)
        self.assertTrue((await self.jd.screenshot())["success"])
        self.assertTrue((await self.jd.status())["running"])

    async def taobao_redirect_case(self, screenshot=False):
        browser = self.service.taobao_browser
        browser._context = self.jd._context
        browser._page = self.page
        browser._start_unlocked = AsyncMock()
        self.page.url = fixtures.TAOBAO
        browser.settings.artifacts_dir.mkdir(parents=True)
        async def redirect(*args, **kwargs):
            self.page.url = fixtures.JD
            return b"synthetic" if screenshot else [{"text": "foreign"}]
        if screenshot:
            self.page.screenshot.side_effect = redirect
        else:
            self.page.evaluate.side_effect = redirect
        with self.assertRaises(SafetyError):
            await (browser.screenshot() if screenshot else browser.list_elements())
        self.assertEqual(list(browser.settings.artifacts_dir.iterdir()), [])

    async def test_taobao_list_rejects_redirect_to_jd(self):
        await self.taobao_redirect_case()

    async def test_taobao_screenshot_rejects_redirect_to_jd(self):
        await self.taobao_redirect_case(screenshot=True)
