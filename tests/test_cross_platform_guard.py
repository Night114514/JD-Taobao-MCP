"""Synthetic pages only: never start Playwright or navigate a real website."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import server
from jd_taobao_mcp.config import Settings
from jd_taobao_mcp.safety import ElementSafetyMetadata, SafetyError
from jd_taobao_mcp.service import ShoppingBrowserService


JD = "https://item.jd.com/123.html"
TAOBAO = "https://item.taobao.com/item.htm?id=123456"
TMALL = "https://detail.tmall.com/item.htm?id=123456"


class CrossPlatformGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        settings = replace(Settings.from_env(), profile_dir=Path(temp.name),
                           artifacts_dir=Path(temp.name) / "artifacts", action_delay_ms=0)
        self.service = ShoppingBrowserService(settings)
        self.jd = self.service._browser_for_platform("jd")
        self.page = Mock()
        self.page.url = JD
        self.page.is_closed.return_value = False
        self.page.title = AsyncMock(return_value="Synthetic JD product")
        self.page.wait_for_load_state = AsyncMock()
        self.page.wait_for_timeout = AsyncMock()
        self.page.evaluate = AsyncMock(return_value={"url": JD, "text": "Product"})
        self.page.mouse.wheel = AsyncMock()
        self.page.screenshot = AsyncMock()
        self.page.go_back = AsyncMock()
        self.locator = self.page.locator.return_value
        self.locator.first = self.locator
        self.locator.count = AsyncMock(return_value=1)
        self.locator.inner_text = AsyncMock(return_value="Product")
        self.locator.scroll_into_view_if_needed = AsyncMock()
        self.locator.click = AsyncMock()
        self.locator.fill = AsyncMock()
        self.locator.press = AsyncMock()
        self.locator.get_attribute = AsyncMock(return_value=None)
        self.jd._context = Mock(pages=[self.page])
        self.jd._context.cookies = AsyncMock(return_value=[])
        self.jd._page = self.page
        self.jd._start_unlocked = AsyncMock()
        self.jd._element_metadata = AsyncMock(return_value=ElementSafetyMetadata(text="Product"))

        async def goto(url, **kwargs):
            self.page.url = url
            return SimpleNamespace(status=200)
        self.page.goto = AsyncMock(side_effect=goto)

    async def test_foreign_current_page_blocks_all_jd_tool_paths(self):
        actions = {
            "scroll": lambda: self.jd.scroll(),
            "click": lambda: self.jd.click("e1"),
            "type": lambda: self.jd.type_text("e1", "text", press_enter=True),
            "back": self.jd.go_back,
            "snapshot": self.jd.snapshot,
            "elements": self.jd.list_elements,
            "screenshot": self.jd.screenshot,
            "get_page": self.jd.get_page,
            "check_login": lambda: self.jd.check_login("jd"),
            "navigate": lambda: self.jd.navigate(JD),
        }
        for url in (TAOBAO, TMALL, "https://TMALL.COM./item.htm?id=1"):
            self.page.url = url
            for name, action in actions.items():
                with self.subTest(url=url, action=name):
                    with self.assertRaises(SafetyError):
                        await action()
        self.page.goto.assert_not_awaited()
        self.page.mouse.wheel.assert_not_awaited()
        self.locator.click.assert_not_awaited()
        self.locator.fill.assert_not_awaited()
        self.page.go_back.assert_not_awaited()
        self.page.evaluate.assert_not_awaited()

    async def test_jd_rejects_taobao_target_before_page_access(self):
        for url in (TAOBAO, TMALL):
            with self.subTest(url=url), self.assertRaises(SafetyError):
                await self.jd.navigate(url)
        self.jd._start_unlocked.assert_not_awaited()
        self.page.goto.assert_not_awaited()

    async def test_redirect_is_rejected_before_result_inspection(self):
        async def redirect(*args, **kwargs):
            self.page.url = TMALL
            return SimpleNamespace(status=200)
        self.page.goto.side_effect = redirect
        with self.assertRaises(SafetyError):
            await self.jd.navigate(JD)
        self.locator.inner_text.assert_not_awaited()
        with self.assertRaises(SafetyError):
            await self.jd.scroll()
        self.page.mouse.wheel.assert_not_awaited()

    async def test_known_taobao_link_is_rejected_before_click_or_scroll(self):
        self.jd._element_metadata.return_value = ElementSafetyMetadata(text="Product", href=TAOBAO)
        with self.assertRaises(SafetyError):
            await self.jd.click("e1")
        self.locator.scroll_into_view_if_needed.assert_not_awaited()
        self.locator.click.assert_not_awaited()

    async def test_click_redirect_does_not_trigger_automatic_go_back(self):
        async def redirect():
            self.page.url = TAOBAO
        self.locator.click.side_effect = redirect
        with self.assertRaises(SafetyError):
            await self.jd.click("e1")
        self.page.go_back.assert_not_awaited()
        self.page.goto.assert_not_awaited()

    async def test_popup_is_checked_before_further_use(self):
        popup = Mock(url=TMALL)
        popup.is_closed.return_value = False
        popup.wait_for_load_state = AsyncMock()
        popup.wait_for_timeout = AsyncMock()
        popup.title = AsyncMock(return_value="Wrong platform")
        async def popup_click():
            self.jd._context.pages.append(popup)
        self.locator.click.side_effect = popup_click
        with self.assertRaises(SafetyError):
            await self.jd.click("e1")
        popup.title.assert_not_awaited()
        with self.assertRaises(SafetyError):
            await self.jd.scroll()

    async def test_fill_redirect_does_not_press_enter(self):
        async def redirect(*args):
            self.page.url = TAOBAO
        self.locator.fill.side_effect = redirect
        with self.assertRaises(SafetyError):
            await self.jd.type_text("e1", "query", press_enter=True)
        self.locator.press.assert_not_awaited()
        self.page.goto.assert_not_awaited()

    async def test_enter_redirect_does_not_trigger_recovery_navigation(self):
        async def redirect(*args):
            self.page.url = TMALL
        self.locator.press.side_effect = redirect
        with self.assertRaises(SafetyError):
            await self.jd.type_text("e1", "query", press_enter=True)
        self.page.goto.assert_not_awaited()

    async def test_history_redirect_is_rejected(self):
        async def redirect(**kwargs):
            self.page.url = TAOBAO
        self.page.go_back.side_effect = redirect
        with self.assertRaises(SafetyError):
            await self.jd.go_back()

    async def test_login_check_cannot_navigate_taobao_on_jd_controller(self):
        with self.assertRaises(SafetyError):
            await self.jd.check_login("taobao")
        self.page.goto.assert_not_awaited()

    async def test_snapshot_cannot_return_a_cross_platform_navigation(self):
        async def evaluate(*args):
            self.page.url = TAOBAO
            return {"url": TAOBAO, "text": "Product"}
        self.page.evaluate.side_effect = evaluate
        with self.assertRaises(SafetyError):
            await self.jd.snapshot()

    async def test_mcp_generic_tools_enforce_actual_platform(self):
        self.page.url = TMALL
        with patch.object(server, "service", self.service):
            for tool, args in ((server.scroll_page, ()), (server.click_page_element, ("e1",)),
                               (server.type_into_element, ("e1", "q")), (server.go_back, ()),
                               (server.extract_current_page, ())):
                with self.subTest(tool=tool.__name__), self.assertRaises(SafetyError):
                    await tool(*args)

    async def test_open_url_routes_taobao_and_tmall_to_guarded_controller(self):
        self.service.taobao_browser.navigate = AsyncMock(return_value={"success": True})
        with patch.object(server, "service", self.service):
            for url in (TAOBAO, TMALL):
                await server.open_url(url)
                self.service.taobao_browser.navigate.assert_awaited_with(url)
        self.page.goto.assert_not_awaited()

    async def test_normal_jd_navigation_and_interactions_remain_available(self):
        self.assertTrue((await self.jd.navigate(JD))["success"])
        self.assertTrue((await self.jd.click("e1"))["success"])
        self.assertTrue((await self.jd.type_text("e1", "query", press_enter=True))["success"])
        self.assertTrue((await self.jd.scroll())["success"])
        self.assertTrue((await self.jd.go_back())["success"])
        self.page.mouse.wheel.assert_awaited_once()
        self.locator.click.assert_awaited_once()

    async def test_jd_detail_preparation_rejects_foreign_page_before_wheel(self):
        self.page.url = TMALL
        with self.assertRaises(SafetyError):
            await self.service._prepare_product_detail_page(self.page, "jd")
        self.page.mouse.wheel.assert_not_awaited()

    async def test_jd_detail_tab_redirect_stops_before_scroll_or_next_selector(self):
        self.locator.first = self.locator
        async def redirect(**kwargs):
            self.page.url = TMALL
        self.locator.click.side_effect = redirect
        with self.assertRaises(SafetyError):
            await self.service._click_first_available(self.page, ("first", "second"), scroll_after=True)
        self.locator.click.assert_awaited_once()
        self.page.mouse.wheel.assert_not_awaited()

    async def test_jd_detail_tab_rejects_known_foreign_link_before_click(self):
        self.locator.get_attribute.return_value = TMALL
        with self.assertRaises(SafetyError):
            await self.service._click_first_available(self.page, ("first",), scroll_after=True)
        self.locator.click.assert_not_awaited()
        self.page.mouse.wheel.assert_not_awaited()

    async def test_form_submission_rejects_known_foreign_action_before_typing(self):
        metadata = Mock(spec=ElementSafetyMetadata)
        metadata.input_type = "text"
        metadata.combined_text.return_value = "query"
        metadata.form_action = TAOBAO
        self.jd._element_metadata.return_value = metadata
        with self.assertRaises(SafetyError):
            await self.jd.type_text("e1", "query", press_enter=True)
        self.locator.fill.assert_not_awaited()
        self.locator.press.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
