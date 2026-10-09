"""Offline-only child process for the real MCP stdio transport tests."""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
URL = "https://item.taobao.com/item.htm?id=123456"
ERROR_URL = "https://item.taobao.com/item.htm?id=999999"
DETAIL = {
    "success": True,
    "platform": "taobao",
    "product_url": URL,
    "product_parameters": [{"name": "型號", "value": "MT7925"}],
    "product_parameter_evidence": [{
        "name": "型號", "value": "MT7925",
        "source": "dom_parameters", "corroborated_by": ["dom_detail"],
    }],
    "product_parameter_conflicts": [{
        "name": "型號", "selected_value": "MT7925",
        "selected_source": "dom_parameters",
        "alternatives": [{"source": "json_ld", "value": "OTHER_MODEL"}],
    }],
    "parameter_evidence_status": "provided",
    "good_reviews": [],
    "bad_reviews": [],
}
SEARCH = {
    "success": True, "platform": "taobao", "count": 1,
    "items": [{"title": "離線測試", "price": 85.0, "url": URL}],
    "filters": {"include_details": False, "details_skipped_for_safety": True},
    "detail_output_contract": {
        "optional_fields": ["product_parameter_evidence", "product_parameter_conflicts"],
    },
}
CURRENT = {"success": True, "product_like_data": DETAIL}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("handshake", "mock"))
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    blocked = []

    def audit(event, values):
        # Windows asyncio can use loopback sockets for its internal socket pair.
        # The server has no reason to create a child process or contact a site.
        if event == "subprocess.Popen" or (
            event == "socket.connect"
            and values[1][0] not in {"127.0.0.1", "::1"}
        ):
            blocked.append(event)
            raise RuntimeError("OFFLINE_IO_BLOCKED")

    sys.addaudithook(audit)
    # Patch before importing server: even an accidental startup during import
    # cannot start the Playwright driver. No changes to production Safe Mode.
    driver = Mock(side_effect=RuntimeError("BROWSER_START_BLOCKED"))
    calls = {}
    with (
        patch("playwright.async_api.async_playwright", driver),
        patch("dotenv.load_dotenv", return_value=False),
    ):
        import jd_taobao_mcp.browser as browser_module

        start = AsyncMock(side_effect=RuntimeError("BROWSER_START_BLOCKED"))
        navigate = AsyncMock(side_effect=RuntimeError("BROWSER_NAVIGATION_BLOCKED"))
        with (
            patch.object(browser_module.BrowserController, "_start_unlocked", start),
            patch.object(browser_module.BrowserController, "navigate", navigate),
        ):
            try:
                if args.mode == "handshake":
                    # Exercise the production __main__ and stdio default path.
                    sys.argv = [str(ROOT / "server.py")]
                    runpy.run_path(str(ROOT / "server.py"), run_name="__main__")
                else:
                    import server
                    from jd_taobao_mcp.safety import SafetyError

                    async def detail(url):
                        if url == ERROR_URL:
                            raise SafetyError("MOCK_VERIFICATION_PAUSED")
                        return DETAIL

                    methods = {
                        "get_product_detail": AsyncMock(side_effect=detail),
                        "search_products": AsyncMock(return_value=SEARCH),
                        "extract_current_page": AsyncMock(return_value=CURRENT),
                    }
                    for name, method in methods.items():
                        setattr(server.service, name, method)
                    # Use the real registration, validation and result encoding.
                    sys.argv = [str(ROOT / "server.py")]
                    try:
                        server.main()
                    finally:
                        calls = {
                            name: [{"args": list(call.args), "kwargs": call.kwargs}
                                   for call in method.await_args_list]
                            for name, method in methods.items()
                        }
            finally:
                args.report.write_text(json.dumps({
                    "calls": calls,
                    "browser_starts": start.await_count,
                    "browser_navigations": navigate.await_count,
                    "driver_starts": driver.call_count,
                    "blocked_io": blocked,
                    "shutdown_complete": True,
                }), encoding="utf-8")


if __name__ == "__main__":
    main()
