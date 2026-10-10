from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, quote_plus, urlencode, urljoin, urlparse

from .browser import BrowserController
from .config import Settings
from .extractors import extract_jd_search, extract_product_detail, extract_taobao_search
from .safety import SafetyError, ensure_allowed_url, page_requires_user_verification
from .taobao_guard import is_taobao_auth_url


class ShoppingBrowserService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.jd_browser = BrowserController(self._settings_for_platform("jd"))
        self.taobao_browser = BrowserController(
            self._settings_for_platform("taobao"),
            taobao_safe_mode=True,
        )
        self.browser = self.taobao_browser

    async def search_products(
        self,
        platform: str,
        keyword: str,
        max_results: int = 20,
        min_price: float | None = None,
        max_price: float | None = None,
        sort: str = "default",
        include_details: bool = True,
    ) -> dict[str, Any]:
        platform = _validate_platform(platform)
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("keyword cannot be empty")
        if len(keyword) > 200:
            raise ValueError("keyword is too long")
        max_results = max(1, min(max_results, self.settings.max_search_results))
        if min_price is not None and min_price < 0:
            raise ValueError("min_price cannot be negative")
        if max_price is not None and max_price < 0:
            raise ValueError("max_price cannot be negative")
        if min_price is not None and max_price is not None and min_price > max_price:
            raise ValueError("min_price cannot be greater than max_price")
        if sort not in {"default", "price_asc", "price_desc"}:
            raise ValueError("sort must be default, price_asc, or price_desc")

        browser = self._browser_for_platform(platform)
        nav = await self._open_search_page(browser, platform, keyword)
        async with browser.lock:
            page = await browser.get_page()
            # Safe mode: do not scroll Taobao search results.
            if platform == "jd":
                _ensure_page_platform(page, platform)
                await page.mouse.wheel(0, 900)
                await page.wait_for_timeout(self.settings.action_delay_ms)
            _ensure_page_platform(page, platform)
            body_text = ""
            if await page.locator("body").count():
                body_text = await page.locator("body").inner_text(timeout=5_000)
            requires_verification = page_requires_user_verification(
                body_text, page.url
            )
            if platform == "taobao" and (
                requires_verification
                or nav.get("requires_user_verification", False)
            ):
                browser.pause_taobao_automation("login_or_verification_required")
                return {
                    "success": False,
                    "platform": platform,
                    "keyword": keyword,
                    "requires_user_verification": True,
                    "url": page.url,
                    "message": "Manual verification required. Automation stopped.",
                    "items": [],
                    "detail_output_contract": _detail_output_contract(),
                }

            _ensure_page_platform(page, platform)
            items = (
                await extract_jd_search(page, max_results * 2)
                if platform == "jd"
                else await extract_taobao_search(page, max_results * 2)
            )
            await self._assert_extraction_page(browser, page, platform)
            if requires_verification and not items:
                return {
                    "success": False,
                    "platform": platform,
                    "keyword": keyword,
                    "requires_user_verification": True,
                    "url": page.url,
                    "message": "Page requires manual verification in the visible browser.",
                    "items": [],
                    "detail_output_contract": _detail_output_contract(),
                }

        filtered = [
            item
            for item in items
            if _price_matches(item.get("price"), min_price, max_price)
        ]
        if sort == "price_asc":
            filtered.sort(key=lambda item: (item.get("price") is None, item.get("price") or 0))
        elif sort == "price_desc":
            filtered.sort(
                key=lambda item: (item.get("price") is not None, item.get("price") or 0),
                reverse=True,
            )
        filtered = filtered[:max_results]
        effective_include_details = bool(include_details) and platform == "jd"
        if effective_include_details:
            await self._enrich_search_results_with_details(platform, filtered)

        return {
            "success": True,
            "platform": platform,
            "keyword": keyword,
            "search_url": nav.get("url", ""),
            "count": len(filtered),
            "filters": {
                "min_price": min_price,
                "max_price": max_price,
                "sort": sort,
                "include_details": effective_include_details,
                "details_skipped_for_safety": (
                    platform == "taobao" and bool(include_details)
                ),
            },
            "items": filtered,
            "detail_output_contract": _detail_output_contract(),
            "verification_warning": requires_verification,
            "note": (
                "JD and Taobao use separate browser profiles. Taobao defaults to Chrome "
                "and mobile search; detail extraction looks for Taobao parameter blocks."
            ),
        }

    async def get_product_detail(self, url: str) -> dict[str, Any]:
        original_url = ensure_allowed_url(url)
        platform = platform_from_url(url)
        browser = self._browser_for_platform(platform)
        detail_url = _canonical_detail_url(original_url)
        nav = await browser.navigate(detail_url)
        async with browser.lock:
            page = await browser.get_page()
            _ensure_page_platform(page, platform)
            body_text = ""
            if await page.locator("body").count():
                body_text = await page.locator("body").inner_text(timeout=5_000)
            requires_verification = page_requires_user_verification(
                body_text, page.url
            )
            if platform == "taobao" and (
                requires_verification
                or nav.get("requires_user_verification", False)
            ):
                browser.pause_taobao_automation("login_or_verification_required")
                return {
                    "success": False,
                    "platform": platform,
                    "original_url": original_url,
                    "url": page.url,
                    "product_url": page.url,
                    "requires_user_verification": True,
                    "message": "Manual verification required. Automation stopped.",
                    **_empty_detail_contract_fields(
                        "requires_user_verification", product_url=page.url
                    ),
                }
            if requires_verification and not _page_has_product_content(body_text):
                return {
                    "success": False,
                    "platform": platform,
                    "original_url": original_url,
                    "url": page.url,
                    "product_url": page.url,
                    "requires_user_verification": True,
                    "message": "Product page requires manual verification in the visible browser.",
                    **_empty_detail_contract_fields(
                        "requires_user_verification", product_url=page.url
                    ),
                }
            await self._prepare_product_detail_page(page, platform)
            await self._assert_extraction_page(browser, page, platform)
            detail = await extract_product_detail(
                page, platform, original_url=original_url
            )
            await self._assert_extraction_page(browser, page, platform)
            if platform == "taobao":
                unavailable_markers = (
                    "\u8a72\u5546\u54c1\u4e2d\u570b\u9999\u6e2f\u4e0d\u53ef\u552e\u8ce3",
                    "\u8be5\u5546\u54c1\u4e2d\u56fd\u9999\u6e2f\u4e0d\u53ef\u552e\u5356",
                )
                unavailable_message = next(
                    (marker for marker in unavailable_markers if marker in body_text),
                    "",
                )
                detail["availability_status"] = (
                    "unavailable_for_region" if unavailable_message else "unknown"
                )
                detail["availability_message"] = unavailable_message
        _apply_detail_output_contract(detail)
        detail.update(
            {
                "success": True,
                "original_url": original_url,
                "requires_user_verification": False,
                "verification_warning": requires_verification
                or nav.get("requires_user_verification", False),
                "note": (
                    "Fields are extracted from visible DOM, metadata, JSON-LD, and "
                    "platform-specific parameter areas. Missing fields include status reasons."
                ),
            }
        )
        return detail

    async def _assert_extraction_page(
        self, browser: BrowserController, page: Any, platform: str
    ) -> None:
        """Discard results if an awaited operation exposed login/verification."""
        try:
            _ensure_page_platform(page, platform)
            blocked = is_taobao_auth_url(page.url) or page_requires_user_verification("", page.url)
            if not blocked:
                body = page.locator("body")
                if not await body.count():
                    raise SafetyError("Page DOM unavailable after extraction operation.")
                text = await body.inner_text(timeout=5_000)
                _ensure_page_platform(page, platform)
                blocked = is_taobao_auth_url(page.url) or page_requires_user_verification(text, page.url)
        except Exception as exc:
            browser.pause_taobao_automation("extraction_inspection_failed")
            raise SafetyError("Cannot inspect extraction page; results discarded.") from exc
        if blocked:
            browser.pause_taobao_automation("login_or_verification_required")
            raise SafetyError("Login or verification detected during extraction; results discarded.")

    async def extract_current_page(self) -> dict[str, Any]:
        # Keep the original controller: a snapshot must not switch profiles.
        browser = self.browser
        snapshot = await browser.snapshot()
        platform = platform_from_url(snapshot["url"])
        async with browser.lock:
            page = await browser.get_page()
            _ensure_page_platform(page, platform)
            blocked = (
                snapshot.get("requires_user_verification", False)
                or page_requires_user_verification(snapshot.get("text", ""), snapshot["url"])
                or is_taobao_auth_url(snapshot["url"])
                or is_taobao_auth_url(page.url)
            )
            if not blocked:
                try:
                    body = page.locator("body")
                    if not await body.count():
                        raise SafetyError("Current page DOM unavailable.")
                    text = await body.inner_text(timeout=5_000)
                    blocked = page_requires_user_verification(text, page.url) or is_taobao_auth_url(page.url)
                except Exception as exc:
                    browser.pause_taobao_automation("current_page_inspection_failed")
                    raise SafetyError("Cannot inspect current page; extraction stopped.") from exc
            _ensure_page_platform(page, platform)
            if blocked:
                browser.pause_taobao_automation("login_or_verification_required")
                detail = {
                    "platform": platform,
                    **_empty_detail_contract_fields("requires_user_verification", product_url=page.url),
                }
                if platform == "taobao":
                    detail["parameter_evidence_status"] = "not_extracted"
                return {
                    "success": False,
                    "requires_user_verification": True,
                    "snapshot": snapshot,
                    "product_like_data": detail,
                    "detail_output_contract": _detail_output_contract(),
                }
            detail = await extract_product_detail(page, platform)
            await self._assert_extraction_page(browser, page, platform)
        _apply_detail_output_contract(detail)
        return {
            "success": True,
            "snapshot": snapshot,
            "product_like_data": detail,
            "detail_output_contract": _detail_output_contract(),
        }

    async def _enrich_search_results_with_details(
        self, platform: str, items: list[dict[str, Any]]
    ) -> bool:
        if platform == "taobao":
            return False

        for item in items:
            url = item.get("url")
            if not isinstance(url, str) or not url:
                continue
            try:
                detail = await self.get_product_detail(url)
            except Exception as exc:
                item["detail_success"] = False
                item["detail_error"] = str(exc)
                item.update(
                    _empty_detail_contract_fields(
                        "detail_error", product_url=str(url)
                    )
                )
                continue

            item["detail_success"] = bool(detail.get("success"))
            if detail.get("requires_user_verification"):
                item["detail_requires_user_verification"] = True
                item["detail_message"] = detail.get("message", "")
                item.update(
                    _empty_detail_contract_fields(
                        "requires_user_verification", product_url=str(url)
                    )
                )
                continue

            for key in (
                "product_url",
                "product_parameters",
                "high_praise_reviews",
                "high_dissatisfied_reviews",
                "good_reviews",
                "bad_reviews",
                "product_parameters_status",
                "good_reviews_status",
                "bad_reviews_status",
                "detail_output_contract",
            ):
                item[key] = detail.get(
                    key,
                    [] if key.endswith("_reviews") or key == "product_parameters" else {},
                )
            if not item.get("shop"):
                item["shop"] = detail.get("shop", "")
            if item.get("price") is None:
                item["price"] = detail.get("price")
                item["price_text"] = detail.get("price_text", "")

    async def _prepare_product_detail_page(
        self, page: Any, platform: str
    ) -> None:
        # JD still benefits from the legacy lazy-load scrolling.
        # Taobao must not blindly scroll: repeated wheel events on pages
        # without detail tabs are slow and can provoke site risk controls.
        if platform == "jd":
            _ensure_page_platform(page, platform)
            await page.wait_for_timeout(self.settings.action_delay_ms)
            for _ in range(2):
                _ensure_page_platform(page, platform)
                await page.mouse.wheel(0, 1000)
                await page.wait_for_timeout(self.settings.action_delay_ms)
            await self._prepare_jd_detail_page(page)
            return

        await self._prepare_taobao_detail_page(page)

    async def _prepare_jd_detail_page(self, page: Any) -> None:
        await self._click_first_available(
            page,
            (
                "#detail .tab-main li:has-text('商品详情')",
                ".tab-main li:has-text('商品详情')",
                "a:has-text('商品详情')",
                "li:has-text('商品详情')",
                "#detail .tab-main li:has-text('规格参数')",
                ".tab-main li:has-text('规格参数')",
            ),
            scroll_after=True,
        )
        await self._click_first_available(
            page,
            (
                "#detail .tab-main li:has-text('商品评价')",
                ".tab-main li:has-text('商品评价')",
                "a:has-text('商品评价')",
                "li:has-text('商品评价')",
            ),
        )

    async def _prepare_taobao_detail_page(self, page: Any) -> None:
        # Safe mode: do not scroll, click tabs, or expand content.
        # Extract only DOM content already loaded by navigation.
        return

    async def _click_first_available(
        self, page: Any, selectors: tuple[str, ...], *, scroll_after: bool = False
    ) -> None:
        for selector in selectors:
            _ensure_page_platform(page, "jd")
            locator = page.locator(selector).first
            if not await locator.count():
                continue
            try:
                href = await locator.get_attribute("href")
                target = urljoin(page.url, href) if href else page.url
                if target.lower().startswith(("http://", "https://")):
                    ensure_allowed_url(target)
                    if platform_from_url(target) != "jd":
                        raise SafetyError("JD detail control targets another platform.")
                _ensure_page_platform(page, "jd")
                await locator.click(timeout=2_000)
                _ensure_page_platform(page, "jd")
                await page.wait_for_timeout(self.settings.action_delay_ms)
                _ensure_page_platform(page, "jd")
                if scroll_after:
                    await page.mouse.wheel(0, 500)
                    await page.wait_for_timeout(self.settings.action_delay_ms)
                    _ensure_page_platform(page, "jd")
                return True
            except SafetyError:
                raise
            except Exception:
                _ensure_page_platform(page, "jd")
                continue
        return False

    def _settings_for_platform(self, platform: str) -> Settings:
        if platform == "taobao":
            executable_path = (
                self.settings.taobao_browser_executable_path
                or _default_chrome_path()
                or self.settings.browser_executable_path
            )
            return replace(
                self.settings,
                browser_channel=None if executable_path else self.settings.browser_channel,
                browser_executable_path=executable_path,
                profile_dir=self.settings.profile_dir / "taobao",
            )
        executable_path = (
            self.settings.jd_browser_executable_path
            or self.settings.browser_executable_path
        )
        return replace(
            self.settings,
            browser_executable_path=executable_path,
            profile_dir=self.settings.profile_dir / "jd",
        )

    def _browser_for_platform(self, platform: str) -> BrowserController:
        platform = _validate_platform(platform)
        self.browser = self.taobao_browser if platform == "taobao" else self.jd_browser
        return self.browser

    async def _open_search_page(
        self, browser: BrowserController, platform: str, keyword: str
    ) -> dict[str, Any]:
        if platform == "jd":
            return await browser.navigate(
                f"https://search.jd.com/Search?keyword={quote_plus(keyword)}"
            )
        if self.settings.taobao_search_mode != "mobile":
            raise ValueError(
                "Taobao Safe Mode requires TAOBAO_SEARCH_MODE=mobile."
            )
        if self.settings.taobao_search_mode == "mobile":
            return await browser.navigate(
                f"https://s.m.taobao.com/h5?q={quote(keyword)}"
            )

        nav = await browser.navigate("https://www.taobao.com/")
        async with browser.lock:
            page = await browser.get_page()
            search_box = None
            for selector in (
                'input[name="q"]',
                'input[aria-label*="搜索"]',
                'input[placeholder*="搜索"]',
                "#q",
            ):
                locator = page.locator(selector).first
                if await locator.count():
                    search_box = locator
                    break
            if search_box is None:
                return nav
            await search_box.fill(keyword)
            clicked = await self._click_first_available(
                page,
                (
                    'button:has-text("搜索")',
                    'input[type="submit"]',
                    '[role="button"]:has-text("搜索")',
                ),
            )
            if not clicked:
                await search_box.press("Enter")
            await page.wait_for_timeout(self.settings.action_delay_ms)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5_000)
            except Exception:
                pass
            if "s.taobao.com/search" not in page.url:
                fallback_url = f"https://s.taobao.com/search?q={quote(keyword)}"
                try:
                    response = await page.goto(fallback_url, wait_until="domcontentloaded")
                    await page.wait_for_timeout(self.settings.action_delay_ms)
                    nav = {**nav, "http_status": response.status if response else None}
                except Exception:
                    pass
            return {**nav, "url": page.url}


def _canonical_detail_url(url: str) -> str:
    """Normalize supported Taobao detail URLs to the full desktop detail page."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    supported = (
        (host == "item.taobao.com" and parsed.path == "/item.htm")
        or
        (host == "new.m.taobao.com" and parsed.path == "/detail.htm")
    )

    if not supported:
        return url

    query = parse_qs(parsed.query)

    item_id = (query.get("id") or [None])[0]
    sku_id = (query.get("skuId") or [None])[0]

    if not item_id:
        return url

    canonical = f"https://item.taobao.com/item.htm?id={item_id}"

    if sku_id:
        canonical += f"&skuId={sku_id}"

    return canonical

def _validate_platform(platform: str) -> str:
    normalized = platform.strip().lower()
    if normalized not in {"jd", "taobao"}:
        raise ValueError("platform must be jd or taobao")
    return normalized


def platform_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host == "jd.com" or host.endswith(".jd.com") or host.endswith(".360buy.com"):
        return "jd"
    if (
        host == "taobao.com"
        or host.endswith(".taobao.com")
        or host == "tmall.com"
        or host.endswith(".tmall.com")
    ):
        return "taobao"
    raise ValueError("URL must belong to JD, Taobao, or Tmall")


def _ensure_page_platform(page: Any, platform: str) -> None:
    ensure_allowed_url(page.url)
    if platform_from_url(page.url) != platform:
        raise SafetyError("Page platform changed; operation stopped without retry.")


def _default_chrome_path() -> Path | None:
    candidates = (
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    )
    return next((path for path in candidates if path.exists()), None)


def _price_matches(
    price: float | None, min_price: float | None, max_price: float | None
) -> bool:
    if price is None:
        return min_price is None and max_price is None
    if min_price is not None and price < min_price:
        return False
    if max_price is not None and price > max_price:
        return False
    return True


def _apply_detail_output_contract(detail: dict[str, Any]) -> None:
    product_url = detail.get("product_url") or detail.get("url") or ""
    product_parameters = _list_value(detail.get("product_parameters"))
    good_reviews = _list_value(
        detail.get("good_reviews") or detail.get("high_praise_reviews")
    )[:5]
    bad_reviews = _list_value(
        detail.get("bad_reviews") or detail.get("high_dissatisfied_reviews")
    )[:2]

    detail["product_url"] = product_url
    detail["product_parameters"] = product_parameters
    detail["good_reviews"] = good_reviews
    detail["bad_reviews"] = bad_reviews
    detail["high_praise_reviews"] = good_reviews
    detail["high_dissatisfied_reviews"] = bad_reviews
    detail["product_parameters_status"] = _field_status(
        "product_parameters", len(product_parameters)
    )
    detail["good_reviews_status"] = _field_status(
        "good_reviews", len(good_reviews), target_count=5
    )
    detail["bad_reviews_status"] = _field_status(
        "bad_reviews", len(bad_reviews), target_count=2
    )
    detail["detail_output_contract"] = _detail_output_contract()


def _empty_detail_contract_fields(reason: str, *, product_url: str = "") -> dict[str, Any]:
    return {
        "product_url": product_url,
        "product_parameters": [],
        "good_reviews": [],
        "bad_reviews": [],
        "high_praise_reviews": [],
        "high_dissatisfied_reviews": [],
        "product_parameters_status": _field_status("product_parameters", 0, reason),
        "good_reviews_status": _field_status(
            "good_reviews", 0, reason, target_count=5
        ),
        "bad_reviews_status": _field_status(
            "bad_reviews", 0, reason, target_count=2
        ),
        "detail_output_contract": _detail_output_contract(),
    }


def _detail_output_contract() -> dict[str, Any]:
    return {
        "required_fields": [
            "product_url",
            "product_parameters",
            "good_reviews",
            "bad_reviews",
            "product_parameters_status",
            "good_reviews_status",
            "bad_reviews_status",
        ],
        "review_limits": {"good_reviews": 5, "bad_reviews": 2},
        "empty_field_policy": (
            "Required fields are always present. Missing or partial fields include "
            "a status.reason explaining verification, visibility, or extraction limits."
        ),
    }


def _field_status(
    field: str, count: int, reason: str | None = None, *, target_count: int = 1
) -> dict[str, Any]:
    if count:
        complete = field == "product_parameters" or count >= target_count
        return {
            "field": field,
            "required": True,
            "count": count,
            "target_count": target_count,
            "complete": complete,
            "reason": "ok" if complete else f"visible_reviews_less_than_{target_count}",
        }
    return {
        "field": field,
        "required": True,
        "count": 0,
        "target_count": target_count,
        "complete": False,
        "reason": reason or "not_visible_or_not_extracted",
    }


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _page_has_product_content(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "商品详情",
            "买家评价",
            "累计评价",
            "商品编号",
            "参数",
        )
    )
