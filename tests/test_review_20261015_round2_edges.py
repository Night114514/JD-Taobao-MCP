"""Additional offline boundaries; the original Round 2 RED module is unchanged."""
import ast
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

import test_review_20261015_round2 as red
from jd_taobao_mcp.safety import SafetyError
from jd_taobao_mcp.service import _canonical_detail_url


class CanonicalBoundaryTests(unittest.TestCase):
    def test_conflicts_across_supported_desktop_and_mobile_entries(self):
        for base in ("https://item.taobao.com/item.htm",
                     "https://new.m.taobao.com/detail.htm"):
            for query in ("id=1&id=2", "id=1&skuId=2&skuid=3",
                          "id=1&skuid=2&sku_id=3", "id=1&sku_id=2&sku_id=3",
                          "id=1&id=", "id=1&skuId=2&sku_id=",
                          "id=1&sku%49d=2&sku_id=3"):
                with self.subTest(base=base, query=query), self.assertRaises(SafetyError):
                    _canonical_detail_url(base + "?" + query)

    def test_equal_aliases_keep_existing_canonical_output(self):
        for base in ("https://item.taobao.com/item.htm",
                     "https://new.m.taobao.com/detail.htm"):
            with self.subTest(base=base):
                self.assertEqual(
                    _canonical_detail_url(base + "?id=1&id=1&skuId=2&skuid=2&sku_id=2&spm=x#d"),
                    "https://item.taobao.com/item.htm?id=1&skuId=2",
                )
                # Alias-only SKU values were not promoted by canonicalization.
                self.assertEqual(
                    _canonical_detail_url(base + "?id=1&sku_id=2"),
                    "https://item.taobao.com/item.htm?id=1",
                )

    def test_unsupported_marketplace_and_path_are_unchanged(self):
        for url in ("https://detail.tmall.com/item.htm?id=1&skuId=2#d",
                    "https://item.m.taobao.com/item.htm?id=1&skuId=2",
                    "https://new.m.taobao.com/other?id=1&skuId=2"):
            with self.subTest(url=url):
                self.assertEqual(_canonical_detail_url(url), url)


class PageBoundaryTests(unittest.IsolatedAsyncioTestCase):
    setUp = red.PageInspectionTests.setUp
    taobao = red.PageInspectionTests.taobao
    assert_paused = red.PageInspectionTests.assert_paused

    async def test_mobile_conflicts_rejected_before_navigation(self):
        browser = self.taobao()
        browser.navigate = AsyncMock(side_effect=SafetyError("navigation sentinel"))
        for query in ("id=1&id=2", "id=1&skuId=2&skuid=3", "id=1&sku_id=2&sku_id=3"):
            with self.subTest(query=query):
                with self.assertRaises(SafetyError):
                    await self.service.get_product_detail("https://new.m.taobao.com/detail.htm?" + query)
                browser.navigate.assert_not_awaited()

    async def test_challenge_appearing_during_title_read_is_reported(self):
        browser = self.taobao()
        browser._settle = AsyncMock()

        async def title():
            self.locator.evaluate.return_value = True
            return "Synthetic"
        self.page.title.side_effect = title
        with patch.object(browser._taobao_guard, "reserve_navigation",
                          wraps=browser._taobao_guard.reserve_navigation) as reserve:
            result = await browser.navigate(self.page.url)
            self.assertEqual(reserve.call_count, 1)
        self.page.goto.assert_awaited_once()
        self.assertTrue(result["requires_user_verification"])
        self.assertTrue(result["automation_paused"])
        self.assert_paused(browser)

    async def test_login_challenge_appearing_during_cookie_read(self):
        browser = self.taobao()

        async def cookies():
            self.locator.evaluate.return_value = True
            return [{"name": "tracknick", "domain": ".taobao.com"}]
        browser._context.cookies.side_effect = cookies
        result = await browser.check_login("taobao")
        self.assertFalse(result["likely_logged_in"])
        self.assertTrue(result["requires_user_verification"])
        self.assert_paused(browser)
        self.page.goto.assert_not_awaited()

    async def test_login_post_cookie_dom_failure_persists_pause(self):
        browser = self.taobao()
        original = RuntimeError("synthetic second inspection failure")
        self.locator.inner_text.side_effect = ["Product", original]
        with self.assertRaises(SafetyError) as caught:
            await browser.check_login("taobao")
        self.assertIs(caught.exception.__cause__, original)
        self.assert_paused(browser)
        self.page.goto.assert_not_awaited()

    async def test_manual_completion_can_report_login_without_resuming_guard(self):
        browser = self.taobao()
        browser._taobao_guard.pause("synthetic earlier challenge")
        browser._context.cookies.return_value = [{"name": "tracknick", "domain": ".taobao.com"}]
        result = await browser.check_login("taobao")
        self.assertTrue(result["likely_logged_in"])
        self.assertFalse(result["requires_user_verification"])
        self.assert_paused(browser)
        self.page.goto.assert_not_awaited()

    async def test_login_challenge_pause_write_failure_propagates(self):
        browser = self.taobao()
        self.locator.evaluate.return_value = True
        with patch.object(browser._taobao_guard, "pause",
                          side_effect=OSError("synthetic write failure")):
            with self.assertRaisesRegex(OSError, "synthetic write failure"):
                await browser.check_login("taobao")
        self.page.goto.assert_not_awaited()


class ChildBoundaryTests(unittest.TestCase):
    def test_non_tuple_and_non_loopback_addresses_are_denied(self):
        probe = red.ChildAuditContractTests()
        probe.setUp()
        for event in ("socket.connect", "socket.bind"):
            for address in ("synthetic-unix-socket", ("192.0.2.1", 80), ("localhost", 80)):
                with self.subTest(event=event, address=address):
                    probe.assert_denied(event, (None, address))

    def test_dns_names_and_loopback_datagrams_are_denied(self):
        probe = red.ChildAuditContractTests()
        probe.setUp()
        for event, values in (
            ("socket.getaddrinfo", ("localhost", 80, 0, 0, 0)),
            ("socket.sendto", (None, ("127.0.0.1", 80))),
            ("socket.sendmsg", (None, ("::1", 80))),
        ):
            with self.subTest(event=event):
                probe.assert_denied(event, values)

    def test_hook_registration_precedes_server_startup(self):
        tree = ast.parse(Path(__file__).with_name("stdio_fixture_server.py").read_text(encoding="utf-8"))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        hook = next(node for node in main.body if isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Call)
                    and ast.unparse(node.value.func) == "sys.addaudithook")
        imports = [node for node in ast.walk(main) if isinstance(node, (ast.Import, ast.ImportFrom))]
        startups = [node for node in ast.walk(main) if isinstance(node, ast.Call)
                    and ast.unparse(node.func) in {"runpy.run_path", "server.main"}]
        self.assertTrue(imports)
        self.assertTrue(startups)
        self.assertTrue(all(node.lineno > hook.lineno for node in imports + startups))
