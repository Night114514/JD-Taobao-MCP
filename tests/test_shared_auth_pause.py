"""Offline auth observation regressions; no real browser or account state."""
import unittest
from unittest.mock import AsyncMock, patch
import test_cross_platform_guard as fixtures
from jd_taobao_mcp.taobao_guard import TaobaoNavigationGuard

LOGIN = "https://login.taobao.com/member/login.jhtml"


class SharedAuthPauseTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.CrossPlatformGuardTests.setUp

    def prepare(self, url=LOGIN, jd=False):
        browser = self.jd if jd else self.service.taobao_browser
        browser._context = self.jd._context
        browser._page = self.page
        browser._start_unlocked = AsyncMock()
        self.page.url = url
        self.page.screenshot.return_value = b"synthetic-image"
        browser.settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
        return browser

    async def observe(self, method, *, url=LOGIN, redirect_at=None, failure=False,
                      jd=False, paused=True, write_failure=False):
        browser = self.prepare(url, jd)
        guard = self.service.taobao_browser._taobao_guard
        artifacts_before = set(browser.settings.artifacts_dir.iterdir())
        original_error = RuntimeError("synthetic await failure")
        if redirect_at:
            async def redirect(*args, **kwargs):
                self.page.url = LOGIN
                if failure:
                    raise original_error
                return b"synthetic-image" if redirect_at == "screenshot" else "Product"
            target = self.locator if redirect_at == "inner_text" else self.page
            getattr(target, redirect_at).side_effect = redirect
        async def invoke():
            if method == "check_login":
                return await browser.check_login("taobao")
            return await getattr(browser, method)()
        with patch.object(guard, "reserve_navigation") as reserve:
            if write_failure:
                with patch.object(guard, "pause", side_effect=OSError("synthetic state write denied")):
                    with self.assertRaises(Exception) as caught:
                        await invoke()
                diagnostic = repr(caught.exception) + repr(caught.exception.__cause__)
                self.assertIn("synthetic state write denied", diagnostic)
                if failure:
                    self.assertIs(caught.exception, original_error)
                self.assertEqual(set(browser.settings.artifacts_dir.iterdir()), artifacts_before)
            elif failure:
                with self.assertRaises(Exception) as caught:
                    await invoke()
                self.assertTrue(caught.exception is original_error or
                                caught.exception.__cause__ is original_error)
                self.assertEqual(set(browser.settings.artifacts_dir.iterdir()), artifacts_before)
            else:
                await invoke()
            if not write_failure:
                self.assertEqual(TaobaoNavigationGuard(guard.state_path).is_paused(), paused)
            reserve.assert_not_called()
            self.page.goto.assert_not_awaited()
            self.page.go_back.assert_not_awaited()

    async def test_restored_profile_start(self):
        # Exercise real _active_page_unlocked selecting a restored context page.
        browser = self.prepare()
        browser._page = None
        await browser.start()
        self.assertTrue(TaobaoNavigationGuard(browser._taobao_guard.state_path).is_paused())
        self.page.goto.assert_not_awaited()

    async def test_manual_login_status(self):
        await self.observe("status")

    async def test_manual_login_screenshot(self):
        await self.observe("screenshot")

    async def test_status_title_redirect(self):
        await self.observe("status", url=fixtures.TAOBAO, redirect_at="title")

    async def test_status_title_redirect_then_error(self):
        await self.observe("status", url=fixtures.TAOBAO, redirect_at="title", failure=True)

    async def test_screenshot_redirect(self):
        await self.observe("screenshot", url=fixtures.TAOBAO, redirect_at="screenshot")

    async def test_screenshot_redirect_then_error(self):
        await self.observe("screenshot", url=fixtures.TAOBAO, redirect_at="screenshot", failure=True)

    async def test_check_login_dom_redirect(self):
        await self.observe("check_login", url=fixtures.TAOBAO, redirect_at="inner_text")

    async def test_pause_write_failure_is_not_success(self):
        await self.observe("start", write_failure=True)
        for method, operation in (("status", "title"), ("screenshot", "screenshot")):
            with self.subTest(method=method, phase="entry"):
                await self.observe(method, write_failure=True)
            for failure in (False, True):
                with self.subTest(method=method, phase="after_await", failure=failure):
                    await self.observe(method, url=fixtures.TAOBAO,
                                       redirect_at=operation, failure=failure,
                                       write_failure=True)

    async def test_normal_taobao(self):
        for method in ("start", "status", "screenshot"):
            with self.subTest(method=method):
                await self.observe(method, url=fixtures.TAOBAO, paused=False)

    async def test_normal_jd(self):
        for method in ("start", "status", "screenshot"):
            with self.subTest(method=method):
                await self.observe(method, url=fixtures.JD, jd=True, paused=False)

    async def test_blank_page(self):
        await self.observe("start", url="about:blank", paused=False)

    async def test_check_login_remains_diagnostic(self):
        browser = self.prepare()
        result = await browser.check_login("taobao")
        self.assertTrue(result["requires_user_verification"])
        self.assertFalse(result["likely_logged_in"])
        self.assertTrue(TaobaoNavigationGuard(browser._taobao_guard.state_path).is_paused())
        self.page.goto.assert_not_awaited()

    async def test_completed_manual_login_does_not_resume(self):
        browser = self.prepare(fixtures.TAOBAO)
        browser._taobao_guard.pause("synthetic prior auth")
        await browser.check_login("taobao")
        self.assertTrue(TaobaoNavigationGuard(browser._taobao_guard.state_path).is_paused())
        self.page.goto.assert_not_awaited()

    async def test_open_login_keeps_existing_guarded_navigation(self):
        browser = self.prepare("about:blank")
        browser.navigate = AsyncMock(return_value={"success": False, "requires_user_verification": True})
        result = await browser.open_login("taobao")
        browser.navigate.assert_awaited_once_with(LOGIN)
        self.assertTrue(result["requires_user_verification"])
        self.assertIn("check_login", result["message"])
        self.page.goto.assert_not_awaited()
