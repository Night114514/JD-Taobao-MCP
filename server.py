from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent

from mcp.server.fastmcp import FastMCP

from jd_taobao_mcp.config import load_settings
from jd_taobao_mcp.service import ShoppingBrowserService

settings = load_settings(PROJECT_ROOT)
service = ShoppingBrowserService(settings)

mcp = FastMCP(
    "JD-Taobao-Browser",
    instructions=(
        "Taobao Safe Mode: no automated scrolling, clicking, typing, or bulk detail enrichment. "
        "Never retry blocked Taobao requests automatically or clear verification pauses. "
        "用于在用户本机可见浏览器中浏览京东、淘宝和天猫，并提取页面与商品数据。"
        "必须让用户自己完成扫码、密码、验证码和安全验证。"
        "默认只读：不得购买、加入购物车、结算、支付、关注、收藏、删除或修改账户信息。"
        "优先使用 search_products 和 get_product_detail；只有页面结构变化时才使用通用点击工具。"
        "商品详情输出有硬约束：必须包含 product_url、product_parameters、good_reviews、bad_reviews "
        "及对应 status 字段；good_reviews 目标最多 5 条，bad_reviews 目标最多 2 条；"
        "缺失或不足时必须用空数组或不足目标条数和 status.reason 说明原因。"
        "不要高频、大规模采集。元素 ref 在页面变化后会失效，点击或导航后应重新调用 list_page_elements。"
    ),
)


@mcp.tool()
async def browser_start() -> dict[str, Any]:
    """启动一个带独立持久化资料目录的可见 Chromium 浏览器。"""
    return await service.taobao_browser.start()


@mcp.tool()
async def browser_status() -> dict[str, Any]:
    """查看浏览器是否运行、当前页面和资料目录。"""
    return {
        "jd": await service.jd_browser.status(),
        "taobao": await service.taobao_browser.status(),
    }


@mcp.tool()
async def open_login(platform: str) -> dict[str, Any]:
    """打开京东或淘宝登录页，由用户在浏览器窗口中手动登录。

    Args:
        platform: jd 或 taobao。
    """
    platform = platform.strip().lower()
    return await service._browser_for_platform(platform).open_login(platform)


@mcp.tool()
async def check_login(platform: str) -> dict[str, Any]:
    """根据页面与 Cookie 名称判断京东或淘宝是否可能已登录，不返回 Cookie 值。

    Args:
        platform: jd 或 taobao。
    """
    platform = platform.strip().lower()
    return await service._browser_for_platform(platform).check_login(platform)


@mcp.tool()
async def open_url(url: str) -> dict[str, Any]:
    """Open a permitted URL. Taobao navigation is subject to cooldown, hourly limits, and persistent verification pause."""
    from jd_taobao_mcp.service import platform_from_url

    platform = platform_from_url(url)
    return await service._browser_for_platform(platform).navigate(url)


@mcp.tool()
async def search_products(
    platform: str,
    keyword: str,
    max_results: int = 20,
    min_price: float | None = None,
    max_price: float | None = None,
    sort: str = "default",
    include_details: bool = True,
) -> dict[str, Any]:
    """Search JD or Taobao products.

Taobao Safe Mode: no scrolling or bulk detail navigation.
include_details=True is ignored for Taobao.
Only initially loaded search results are extracted.

detail_output_contract describes available detail fields, but Taobao search items do not automatically include product detail evidence.
JD retains its existing behavior."""
    return await service.search_products(
        platform=platform,
        keyword=keyword,
        max_results=max_results,
        min_price=min_price,
        max_price=max_price,
        sort=sort,
        include_details=include_details,
    )


@mcp.tool()
async def get_product_detail(url: str) -> dict[str, Any]:
    """Open one permitted product detail page and extract available information.

Taobao Safe Mode reads initially loaded DOM only.
No tab clicks, scrolling, or expansion. Navigation guard applies.

For Taobao, inspect product_parameter_evidence, product_parameter_conflicts, and parameter_evidence_status.
provided, not_provided, and not_extracted have different meanings.
Same-page source agreement is not independent verification.
An empty conflict list is meaningful only when evidence was provided.
Missing parameters and reviews are valid partial results."""
    return await service.get_product_detail(url)


@mcp.tool()
async def page_snapshot(max_chars: int | None = None) -> dict[str, Any]:
    """获取当前页面可见文本、链接、表单和基础元数据。"""
    return await service.browser.snapshot(max_chars=max_chars)


@mcp.tool()
async def extract_current_page() -> dict[str, Any]:
    """Extract a snapshot and structured data from the current page.

The product_like_data object contains the detail fields.
For Taobao, inspect parameter_evidence_status and source conflicts.
This tool does not require a new product-page navigation."""
    return await service.extract_current_page()


@mcp.tool()
async def list_page_elements(limit: int = 80) -> dict[str, Any]:
    """列出当前页面可见的链接、按钮、输入框等，并分配短期 ref。"""
    return await service.browser.list_elements(limit=limit)


@mcp.tool()
async def click_page_element(ref: str) -> dict[str, Any]:
    """Click an allowed page element. Disabled for Taobao Safe Mode."""
    return await service.browser.click(ref)


@mcp.tool()
async def type_into_element(
    ref: str, text: str, press_enter: bool = False
) -> dict[str, Any]:
    """Type into an allowed field. Disabled for Taobao Safe Mode."""
    return await service.browser.type_text(ref, text, press_enter=press_enter)


@mcp.tool()
async def scroll_page(direction: str = "down", amount: int = 900) -> dict[str, Any]:
    """Scroll the current page. Disabled for Taobao Safe Mode."""
    return await service.browser.scroll(direction=direction, amount=amount)


@mcp.tool()
async def go_back() -> dict[str, Any]:
    """Go to the previous page. Disabled for Taobao Safe Mode."""
    return await service.browser.go_back()


@mcp.tool()
async def take_screenshot(full_page: bool = False) -> dict[str, Any]:
    """将当前页面截图保存到本地 artifacts 目录。"""
    return await service.browser.screenshot(full_page=full_page)


@mcp.tool()
async def browser_close() -> dict[str, Any]:
    """关闭浏览器；持久化登录资料仍保留在本地独立目录。"""
    results = {
        "jd": await service.jd_browser.close(),
        "taobao": await service.taobao_browser.close(),
    }
    return {"success": True, "results": results}


def main() -> None:
    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
