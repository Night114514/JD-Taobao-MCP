"""Real stdio MCP protocol, synthetic service results, no browser or site I/O."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from stdio_fixture_server import CURRENT, DETAIL, ERROR_URL, SEARCH, URL


ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 30


class MCPStdioTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def session(self, mode, expected_starts=0):
        with tempfile.TemporaryDirectory(prefix="mcp-stdio-") as folder:
            temp = Path(folder)
            report = temp / "report.json"
            # Only OS essentials are inherited. Never use the user's .env,
            # browser profiles, proxy settings or MCP server launch flags.
            env = {key: os.environ[key] for key in (
                "SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC",
            ) if key in os.environ}
            env.update({
                "PYTHONUTF8": "1",
                "PYTHON_DOTENV_DISABLED": "1",
                "BROWSER_PROFILE_DIR": str(temp / "profiles"),
                "ARTIFACTS_DIR": str(temp / "artifacts"),
                "TAOBAO_SEARCH_MODE": "mobile",
                "ALLOW_STATE_CHANGING_ACTIONS": "false",
            })
            params = StdioServerParameters(
                command=sys.executable,
                args=["-u", str(ROOT / "tests" / "stdio_fixture_server.py"),
                      mode, str(report)],
                cwd=str(temp), env=env,
            )
            with (temp / "stderr.log").open("w+", encoding="utf-8") as stderr:
                try:
                    async with asyncio.timeout(TIMEOUT):
                        async with stdio_client(params, errlog=stderr) as (reader, writer):
                            async with ClientSession(
                                reader, writer,
                                read_timeout_seconds=timedelta(seconds=10),
                            ) as session:
                                initialized = await session.initialize()
                                self.assertEqual(initialized.serverInfo.name, "JD-Taobao-Browser")
                                self.assertIsNotNone(initialized.capabilities.tools)
                                yield session
                except BaseException:
                    stderr.flush()
                    stderr.seek(0)
                    print(stderr.read(), file=sys.stderr)
                    raise
            self.assertTrue(report.exists(), "Child did not complete shutdown")
            self.report = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(self.report["shutdown_complete"])
            self.assertEqual(self.report["browser_starts"], expected_starts)
            self.assertEqual(self.report["browser_navigations"], 0)
            self.assertEqual(self.report["driver_starts"], 0)
            self.assertEqual(self.report["blocked_io"], [])
            self.assertFalse((temp / "profiles").exists())
            self.assertFalse((temp / "artifacts").exists())

    def assert_payload(self, result, expected):
        self.assertFalse(result.isError, result.content)
        text = [block.text for block in result.content if block.type == "text"]
        self.assertEqual(len(text), 1)
        self.assertEqual(json.loads(text[0]), expected)
        self.assertEqual(result.structuredContent, expected)

    async def test_initialize_and_list_tools_without_calling_tools(self):
        async with self.session("handshake") as session:
            listing = await session.list_tools()
            tools = {tool.name: tool for tool in listing.tools}
            self.assertTrue({"get_product_detail", "search_products",
                             "extract_current_page"}.issubset(tools))
            self.assertEqual(len(tools), len(listing.tools))
            description = tools["get_product_detail"].description or ""
            for field in ("product_parameter_evidence", "product_parameter_conflicts",
                          "parameter_evidence_status"):
                self.assertIn(field, description)
            self.assertIn("detail_output_contract", tools["search_products"].description)
            self.assertIn("product_like_data", tools["extract_current_page"].description)
            self.assertIn("url", tools["get_product_detail"].inputSchema["required"])
        self.assertEqual(self.report["calls"], {})

    async def test_mock_tools_call_round_trip_and_argument_forwarding(self):
        search_args = {
            "platform": "taobao", "keyword": "離線測試", "max_results": 5,
            "min_price": 10.0, "max_price": 100.0, "sort": "price_asc",
            "include_details": True,
        }
        async with self.session("mock") as session:
            self.assert_payload(await session.call_tool("get_product_detail", {"url": URL}), DETAIL)
            self.assert_payload(await session.call_tool("search_products", search_args), SEARCH)
            self.assert_payload(await session.call_tool("extract_current_page", {}), CURRENT)
        self.assertEqual(self.report["calls"], {
            "get_product_detail": [{"args": [URL], "kwargs": {}}],
            "search_products": [{"args": [], "kwargs": search_args}],
            "extract_current_page": [{"args": [], "kwargs": {}}],
        })

    async def test_errors_do_not_retry_and_session_remains_usable(self):
        async with self.session("mock") as session:
            invalid = await session.call_tool("get_product_detail", {})
            self.assertTrue(invalid.isError)
            unknown = await session.call_tool("nonexistent_tool", {})
            self.assertTrue(unknown.isError)
            blocked = await session.call_tool("get_product_detail", {"url": ERROR_URL})
            self.assertTrue(blocked.isError)
            self.assertIn("MOCK_VERIFICATION_PAUSED", str(blocked.content))
            self.assert_payload(await session.call_tool("extract_current_page", {}), CURRENT)
        self.assertEqual(self.report["calls"], {
            "get_product_detail": [{"args": [ERROR_URL], "kwargs": {}}],
            "search_products": [],
            "extract_current_page": [{"args": [], "kwargs": {}}],
        })

    async def test_fixture_blocks_browser_start_before_driver_launch(self):
        async with self.session("handshake", expected_starts=1) as session:
            result = await session.call_tool("browser_start", {})
            self.assertTrue(result.isError)
            self.assertIn("BROWSER_START_BLOCKED", str(result.content))


if __name__ == "__main__":
    unittest.main()
