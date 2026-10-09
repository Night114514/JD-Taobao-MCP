from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from playwright.async_api import Page

from .helpers import compact_text, normalize_url, parse_price


async def extract_product_detail(
    page: Page, platform: str, *, original_url: str | None = None
) -> dict[str, Any]:
    # Keep request metadata independent of canonical navigation and redirects.
    metadata_url = original_url if original_url is not None else page.url
    selectors = _selectors(platform)
    raw = await page.evaluate(
        r"""
        (selectors) => {
          const clean = (value, max = 500) => {
            const text = String(value || '').replace(/\s+/g, ' ').trim();
            return max && text.length > max ? text.slice(0, max - 1) + '…' : text;
          };
          const firstText = (items) => {
            for (const selector of items) {
              const el = document.querySelector(selector);
              const text = el?.innerText?.trim() || el?.getAttribute?.('content')?.trim();
              if (text) return text;
            }
            return '';
          };
          const jsonLd = [];
          for (const node of document.querySelectorAll('script[type="application/ld+json"]')) {
            try { jsonLd.push(JSON.parse(node.textContent || 'null')); } catch (_) {}
          }
          const specs = [];
          for (const selector of selectors.specs) {
            for (const el of document.querySelectorAll(selector)) {
              const text = (el.innerText || '').trim();
              if (text && text.length < 500) specs.push(text);
              if (specs.length >= 80) break;
            }
            if (specs.length >= 80) break;
          }
          const productParameters = [];
          const parameterSeen = new Set();
          const addParameter = (name, value, group = '') => {
            name = clean(name, 120).replace(/[：:]\s*$/, '');
            value = clean(value, 500);
            group = clean(group, 120);
            if (!name || !value || name === value) return;
            const key = `${group}\u0000${name}\u0000${value}`;
            if (parameterSeen.has(key)) return;
            parameterSeen.add(key);
            productParameters.push({name, value, group});
          };
          const splitParameterText = (text) => {
            text = clean(text, 600);
            const index = text.search(/[：:]/);
            if (index <= 0 || index >= text.length - 1) return null;
            return [text.slice(0, index), text.slice(index + 1)];
          };
          for (const selector of selectors.specs) {
            for (const el of document.querySelectorAll(selector)) {
              const pair = splitParameterText(el.innerText || '');
              if (pair) addParameter(pair[0], pair[1]);
              if (productParameters.length >= 100) break;
            }
            if (productParameters.length >= 100) break;
          }
          for (const section of document.querySelectorAll('.Ptable-item, [class*="Ptable"], [class*="parameter"], [class*="Parameter"]')) {
            const group = clean(section.querySelector('h3, h4, .Ptable-tit')?.innerText || '');
            for (const row of section.querySelectorAll('dl, tr, li')) {
              const name = clean(row.querySelector('dt, th, .name, [class*="name"]')?.innerText || '');
              const value = clean(row.querySelector('dd, td, .value, [class*="value"]')?.innerText || '');
              if (name && value) addParameter(name, value, group);
              const pair = splitParameterText(row.innerText || '');
              if (pair) addParameter(pair[0], pair[1], group);
              if (productParameters.length >= 100) break;
            }
            if (productParameters.length >= 100) break;
          }
          const detailParameters = [];
          const detailParameterSeen = new Set();
          const addDetailParameter = (name, value, group = '商品详情') => {
            name = clean(name, 120).replace(/[：:]\s*$/, '');
            value = clean(value, 500);
            group = clean(group, 120) || '商品详情';
            if (!name || !value || name === value) return;
            const key = `${group}\u0000${name}\u0000${value}`;
            if (detailParameterSeen.has(key)) return;
            detailParameterSeen.add(key);
            detailParameters.push({name, value, group});
          };
          const detailRoots = [
            ...document.querySelectorAll('#detail, #J-detail, .detail, .goods-detail, [class*="detail"], [class*="Detail"]')
          ];
          const rootSeen = new Set();
          for (const root of detailRoots) {
            if (!root || rootSeen.has(root)) continue;
            rootSeen.add(root);
            const rootText = clean(root.innerText || root.textContent || '', 3000);
            if (!rootText.includes('商品详情') && !root.querySelector('.Ptable, .Ptable-item, .p-parameter-list, .parameter2')) continue;
            for (const section of root.querySelectorAll('.Ptable-item, .Ptable, .p-parameter, .parameter2, .p-parameter-list')) {
              const group = clean(section.querySelector('h3, h4, .Ptable-tit')?.innerText || '商品详情');
              for (const row of section.querySelectorAll('dl, tr, li')) {
                const name = clean(row.querySelector('dt, th, .name, [class*="name"]')?.innerText || '');
                const value = clean(row.querySelector('dd, td, .value, [class*="value"]')?.innerText || '');
                if (name && value) addDetailParameter(name, value, group);
                const pair = splitParameterText(row.innerText || '');
                if (pair) addDetailParameter(pair[0], pair[1], group);
                if (detailParameters.length >= 100) break;
              }
              if (detailParameters.length >= 100) break;
            }
            if (detailParameters.length >= 100) break;
          }
          const textOf = (root, selectorList) => {
            for (const selector of selectorList) {
              const el = root.querySelector(selector);
              const text = clean(el?.innerText || el?.textContent || '', 1200);
              if (text) return text;
            }
            return '';
          };
          const helpfulCount = (text) => {
            text = clean(text, 2000);
            const patterns = [
              /(\d+)\s*(?:人)?(?:点赞|赞|有用|认为有用)/,
              /(?:点赞|赞|有用|认为有用)\D{0,8}(\d+)/
            ];
            for (const pattern of patterns) {
              const match = text.match(pattern);
              if (match) return Number(match[1]);
            }
            return null;
          };
          const positiveTerms = ['好用', '满意', '推荐', '不错', '很好', '超香', '方便', '简单', '值得', '性价比', '喜欢', '大品牌', '香甜', '粒粒分明', '完美', '省心', '治愈', '强烈推荐', '闭眼冲', '稳定', '灵敏', '流畅', '可爱', '实用'];
          const negativeTerms = ['不满意', '不好用', '差评', '很差', '垃圾', '失望', '退货', '坏了', '破损', '有异味', '夹生饭', '溢锅', '太慢了', '噪音大', '漏水', '不推荐', '难用', '踩雷', '虚假', '欺骗', '套路'];
          const negationPhrases = ['后悔没有早点', '没有异味', '无异味', '不粘锅', '不夹生', '噪音小', '噪音低', '不费力'];
          const isTrulyNegative = (text, term) => {
            const index = text.indexOf(term);
            if (index < 0) return false;
            if (negationPhrases.some((phrase) => text.includes(phrase))) return false;
            const before = text.slice(Math.max(0, index - 3), index);
            if (/[没无非少小零]$/.test(before)) return false;
            return true;
          };
          const reviewNodes = [];
          const reviewNodeSeen = new Set();
          for (const selector of selectors.review_items) {
            for (const node of document.querySelectorAll(selector)) {
              if (reviewNodeSeen.has(node)) continue;
              reviewNodeSeen.add(node);
              reviewNodes.push(node);
              if (reviewNodes.length >= 80) break;
            }
            if (reviewNodes.length >= 80) break;
          }
          const reviews = [];
          const reviewSeen = new Set();
          for (const node of reviewNodes) {
            const allText = clean(node.innerText || node.textContent || '', 2000);
            let content = textOf(node, selectors.review_content);
            if (!content) content = allText;
            const user = textOf(node, selectors.review_user);
            const time = textOf(node, selectors.review_time);
            const variant = textOf(node, selectors.review_variant);
            content = clean(content.replace(user, '').replace(time, '').replace(variant, ''), 800);
            if (content.length < 8) continue;
            const key = `${user}\u0000${content}`;
            if (reviewSeen.has(key)) continue;
            reviewSeen.add(key);
            const positive = positiveTerms.some((term) => content.includes(term));
            const negative = negativeTerms.some((term) => isTrulyNegative(content, term));
            reviews.push({
              user: clean(user, 80),
              content,
              helpful_count: helpfulCount(allText),
              time: clean(time, 80),
              variant: clean(variant, 160),
              sentiment: negative ? 'negative' : (positive ? 'positive' : '')
            });
          }
          const reviewSort = (a, b) => (b.helpful_count || 0) - (a.helpful_count || 0);
          const highPraiseReviews = reviews
            .filter((review) => review.sentiment === 'positive')
            .sort(reviewSort)
            .slice(0, 5);
          const highDissatisfiedReviews = reviews
            .filter((review) => review.sentiment === 'negative')
            .sort(reviewSort)
            .slice(0, 2);
          const images = [];
          const ogImage = document.querySelector('meta[property="og:image"]')?.content;
          if (ogImage) images.push(ogImage);
          for (const img of document.querySelectorAll('img')) {
            const src = img.getAttribute('data-origin') || img.getAttribute('data-src') || img.getAttribute('data-lazy-img') || img.src;
            const w = img.naturalWidth || img.width || 0;
            const h = img.naturalHeight || img.height || 0;
            if (src && (w >= 200 || h >= 200)) images.push(src);
            if (images.length >= 30) break;
          }
          const bodyText = document.body?.innerText || '';
          const bodyTextAll = document.body?.textContent || '';
          return {
            title: firstText(selectors.title),
            price_text: firstText(selectors.price),
            shop: firstText(selectors.shop),
            review_text: firstText(selectors.reviews),
            sales_text: firstText(selectors.sales),
            specs,
            product_parameters: productParameters,
            detail_product_parameters: detailParameters,
            high_praise_reviews: highPraiseReviews,
            high_dissatisfied_reviews: highDissatisfiedReviews,
            images,
            json_ld: jsonLd,
            meta: {
              og_title: document.querySelector('meta[property="og:title"]')?.content || '',
              description: document.querySelector('meta[name="description"]')?.content || document.querySelector('meta[property="og:description"]')?.content || '',
              canonical: document.querySelector('link[rel="canonical"]')?.href || ''
            },
            body_text: bodyText,
            body_text_all: bodyTextAll
          };
        }
        """,
        selectors,
    )

    json_product = _find_product_json_ld(raw.get("json_ld", []))
    page_title = compact_text(await page.title(), 500)
    title = compact_text(
        raw.get("title")
        or raw.get("meta", {}).get("og_title")
        or json_product.get("name"),
        500,
    )
    if platform == "taobao" and _is_generic_taobao_title(title):
        title = _clean_taobao_page_title(page_title) or title

    price_text = compact_text(raw.get("price_text"), 120)
    if not price_text:
        offers = json_product.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            price_text = compact_text(str(offers.get("price") or offers.get("lowPrice") or ""))

    images: list[str] = []
    json_images = json_product.get("image")
    if isinstance(json_images, str):
        images.append(json_images)
    elif isinstance(json_images, list):
        images.extend(str(item) for item in json_images if item)
    images.extend(str(item) for item in raw.get("images", []) if item)

    normalized_images: list[str] = []
    seen: set[str] = set()
    for image in images:
        normalized = normalize_url(page.url, image)
        if normalized and normalized not in seen:
            seen.add(normalized)
            normalized_images.append(normalized)
        if len(normalized_images) >= 15:
            break

    specs = []
    seen_specs: set[str] = set()
    for spec in raw.get("specs", []):
        cleaned = compact_text(spec, 500)
        if cleaned and cleaned not in seen_specs:
            seen_specs.add(cleaned)
            specs.append(cleaned)
        if len(specs) >= 50:
            break

    body_text = raw.get("body_text") or ""
    body_text_all = raw.get("body_text_all") or body_text

    if platform == "taobao":
        # Prefer visible/layout-aware innerText. Taobao summary parameter cards
        # rely on whitespace/order that can be lost in document.body.textContent.
        visible_taobao_parameters = _taobao_parameters_from_text(body_text)
        # textContent may contain hidden content. Preserve it separately until
        # evidence/conflicts are built; do not manufacture it from innerText.
        all_taobao_parameters = _taobao_parameters_from_text(raw.get("body_text_all") or "")

        parameter_sources = (
            ("visible_text", visible_taobao_parameters),
            (
                "dom_parameters",
                _normalize_parameters(raw.get("product_parameters", [])),
            ),
            (
                "dom_detail",
                _normalize_parameters(raw.get("detail_product_parameters", [])),
            ),
            ("json_ld", _json_ld_product_parameters(json_product)),
            ("text_content", all_taobao_parameters),
        )
        product_parameters = _merge_parameters(
            *(items for _, items in parameter_sources)
        )
    else:
        product_parameters = _merge_parameters(
            _parameters_from_detail_text(body_text),
            _normalize_parameters(
                raw.get("detail_product_parameters", [])
            ),
            _normalize_parameters(
                raw.get("product_parameters", [])
            ),
        )

    if not product_parameters:
        product_parameters = _fallback_parameters_from_text(
            body_text
        )
        if platform == "taobao":
            parameter_sources = (
                ("fallback_text", product_parameters),
            )

    if platform == "taobao":
        parameter_evidence, parameter_conflicts = (
            _build_taobao_parameter_evidence(
                product_parameters, parameter_sources
            )
        )

    high_praise_reviews = _normalize_reviews(
        raw.get("high_praise_reviews", []),
        limit=5,
    )

    high_dissatisfied_reviews = _normalize_reviews(
        raw.get("high_dissatisfied_reviews", []),
        limit=2,
    )

    raw_review_text = compact_text(
        raw.get("review_text"),
        5000,
    )

    review_source_text = (
        raw_review_text
        or (
            body_text_all
            if platform == "taobao"
            else body_text
        )
    )

    if not high_praise_reviews:
        high_praise_reviews = _fallback_reviews_from_text(
            review_source_text,
            positive=True,
            limit=5,
        )

    if not high_dissatisfied_reviews:
        high_dissatisfied_reviews = _fallback_reviews_from_text(
            review_source_text,
            positive=False,
            limit=2,
        )

    shop = compact_text(raw.get("shop"), 200)
    price = parse_price(price_text)
    price_source = "dom"
    selected_sku_id = None

    if platform == "taobao":
        if not shop:
            shop = _taobao_shop_from_text(body_text)

        url_price, selected_sku_id = _taobao_price_from_url(metadata_url)
        if url_price is not None:
            price = url_price
            price_text = f"\u00a5{url_price:.2f}"
            price_source = "url_upStreamPrice"
        else:
            body_price = _taobao_price_near_title(body_text, title)
            if body_price is not None and (price is None or price == 0):
                price = body_price
                price_text = f"\u00a5{body_price:.2f}"
                price_source = "visible_product_text"

    return {
        "platform": platform,
        "url": page.url,
        "product_url": page.url,
        "title": title,
        "price": price,
        "price_text": price_text,
        "price_source": price_source,
        "selected_sku_id": selected_sku_id,
        "shop": shop,
        "review_text": compact_text(raw.get("review_text"), 5000),
        "sales_text": compact_text(raw.get("sales_text"), 120),
        "description": compact_text(raw.get("meta", {}).get("description"), 1200),
        "canonical_url": normalize_url(page.url, raw.get("meta", {}).get("canonical")),
        "specifications": specs,
        "product_parameters": product_parameters,
        **(
            {
                "product_parameter_evidence": parameter_evidence,
                "product_parameter_conflicts": parameter_conflicts,
            }
            if platform == "taobao"
            else {}
        ),
        "high_praise_reviews": high_praise_reviews,
        "high_dissatisfied_reviews": high_dissatisfied_reviews,
        "images": normalized_images,
        "page_text_excerpt": compact_text(raw.get("body_text"), 10_000),
        "json_ld_product": _limit_json_value(json_product),
    }


def _is_generic_taobao_title(title: str | None) -> bool:
    value = compact_text(title, 200)
    return not value or value in {
        "\u53c2\u6570",
        "\u53c2\u6570\u4fe1\u606f",
        "\u5546\u54c1\u53c2\u6570",
        "\u5b9d\u8d1d\u53c2\u6570",
        "\u89c4\u683c\u53c2\u6570",
        "\u7528\u6237\u8bc4\u4ef7",
        "\u8bc4\u4ef7",
        "\u5546\u54c1\u8be6\u60c5",
    }


def _clean_taobao_page_title(title: str | None) -> str:
    value = compact_text(title, 500)

    suffixes = (
        "- \u6dd8\u5b9d\u7f51",
        "_\u6dd8\u5b9d",
        " - \u6dd8\u5b9d",
        "| \u6dd8\u5b9d",
        "\u2013 \u6dd8\u5b9d",
    )

    for suffix in suffixes:
        if value.endswith(suffix):
            value = value[:-len(suffix)].strip()

    return value


def _taobao_price_from_url(
    url: str,
) -> tuple[float | None, str | None]:
    try:
        query = parse_qs(urlparse(url).query)
    except ValueError:
        return None, None

    sku_id = (query.get("skuId") or [None])[0]
    raw_price = (query.get("upStreamPrice") or [None])[0]

    if raw_price is None:
        return None, sku_id

    try:
        cents = float(raw_price)
    except (TypeError, ValueError):
        return None, sku_id

    if not math.isfinite(cents) or cents <= 0:
        return None, sku_id

    return round(cents / 100.0, 2), sku_id


def _taobao_price_near_title(
    text: str | None,
    title: str | None,
) -> float | None:
    text = compact_text(text, 40_000)
    title = compact_text(title, 500)

    if not text:
        return None

    start = text.find(title) if title else -1

    segment = (
        text[start:start + 1000]
        if start >= 0
        else text[:3000]
    )

    for match in re.finditer(
        r"(?:\u00a5|\uffe5)\s*([0-9]+(?:\.[0-9]{1,2})?)",
        segment,
    ):
        try:
            value = float(match.group(1))
        except ValueError:
            continue

        if value > 0:
            return value

    return None


def _taobao_shop_from_text(text: str | None) -> str:
    text = compact_text(text, 10_000)

    if not text:
        return ""

    patterns = (
        r"\u641c\u672c\u5e97\s+(.{2,80}?)\s+\d(?:\.\d)?\s+88VIP\u597d\u8bc4\u7387",
        r"\u641c\u672c\u5e97\s+(.{2,80}?)\s+88VIP\u597d\u8bc4\u7387",
    )

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return compact_text(match.group(1), 200)

    return ""


def _selectors(platform: str) -> dict[str, list[str]]:
    if platform == "jd":
        return {
            "title": [".sku-name", "#name h1", "h1", "meta[property='og:title']"],
            "price": [
                ".p-price .price",
                ".summary-price .price",
                "[class*='price'] [class*='price']",
                "[class*='price']",
            ],
            "shop": [".name a", ".shop-name", "[class*='shopName']", "[class*='shop-name']"],
            "reviews": [".comment-count .count", "#comment-count", "[class*='comment']"],
            "sales": ["[class*='sales']", "[class*='deal']"],
            "specs": ["#detail .p-parameter-list li", ".parameter2 li", ".Ptable-item", "[class*='parameter'] li"],
            "review_items": [".comment-item", ".J-comment-item", "[class*='comment-item']", "[class*='CommentItem']"],
            "review_user": [".user-info", ".nickname", "[class*='user']", "[class*='User']"],
            "review_content": [".comment-con", ".comment-content", "[class*='content']", "[class*='Content']"],
            "review_time": [".order-info", ".comment-time", "[class*='time']", "[class*='Time']"],
            "review_variant": [".order-info", ".comment-column", "[class*='sku']", "[class*='Sku']"],
        }
    return {
        "title": ["h1", "[class*='Title']", "[class*='title'] h1", "meta[property='og:title']"],
        "price": [
            ".tb-rmb-num",
            "[class*='Price']",
            "[class*='price']",
            "[data-testid*='price']",
        ],
        "shop": [".shop-name", "[class*='Shop']", "[class*='shop'] [class*='name']"],
        "reviews": ["[class*='review']", "[class*='comment']"],
        "sales": ["[class*='sales']", "[class*='sold']", "[class*='deal']"],
        "specs": ["[class*='Parameter'] li", "[class*='parameter'] li", ".attributes-list li", ".tb-attributes li"],
        "review_items": ["[class*='review-item']", "[class*='comment-item']", "[class*='ReviewItem']", "[class*='CommentItem']"],
        "review_user": ["[class*='user']", "[class*='User']", "[class*='nick']", "[class*='Nick']"],
        "review_content": ["[class*='content']", "[class*='Content']", "[class*='review']", "[class*='comment']"],
        "review_time": ["[class*='time']", "[class*='Time']", "[class*='date']", "[class*='Date']"],
        "review_variant": ["[class*='sku']", "[class*='Sku']", "[class*='spec']", "[class*='Spec']"],
    }


def _build_taobao_parameter_evidence(
    selected: list[dict[str, str]],
    sources: tuple[tuple[str, list[dict[str, str]]], ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence = []
    conflicts = []

    for item in selected:
        name = item["name"]
        chosen_value = item["value"]
        chosen_source = "unknown"
        corroborated_by = []
        alternatives = []
        seen_alternatives = set()

        for source, parameters in sources:
            for candidate in parameters:
                if candidate.get("name") != name:
                    continue

                value = candidate.get("value")
                if not value:
                    continue

                if value == chosen_value:
                    if chosen_source == "unknown":
                        chosen_source = source
                    elif (
                        source != chosen_source
                        and source not in corroborated_by
                    ):
                        corroborated_by.append(source)
                else:
                    key = (source, value)
                    if key not in seen_alternatives:
                        seen_alternatives.add(key)
                        alternatives.append({
                            "source": source,
                            "value": value,
                        })

        evidence.append({
            "name": name,
            "value": chosen_value,
            "source": chosen_source,
            "corroborated_by": corroborated_by,
        })

        if alternatives:
            conflicts.append({
                "name": name,
                "selected_value": chosen_value,
                "selected_source": chosen_source,
                "alternatives": alternatives,
            })

    return evidence, conflicts


def _json_ld_product_parameters(
    product: dict[str, Any],
) -> list[dict[str, str]]:
    properties = product.get("additionalProperty", [])

    if isinstance(properties, dict):
        properties = [properties]
    if not isinstance(properties, list):
        return []

    output = []

    for item in properties[:80]:
        if not isinstance(item, dict):
            continue

        name = item.get("name")
        value = item.get("value")

        if not isinstance(name, str):
            continue
        if isinstance(value, bool) or not isinstance(
            value, (str, int, float)
        ):
            continue

        name = compact_text(name, 120)
        value = compact_text(str(value), 500)

        if not name or not value:
            continue

        output.append({
            "name": name,
            "value": value,
            "group": "JSON-LD",
        })

    return output


def _normalize_parameters(items: list[Any]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        name = compact_text(str(item.get("name") or ""), 120)
        value = compact_text(str(item.get("value") or ""), 500)
        group = compact_text(str(item.get("group") or ""), 120)
        if not name or not value:
            continue
        key = (group, name, value)
        if key in seen:
            continue
        seen.add(key)
        output.append({"name": name, "value": value, "group": group})
        if len(output) >= 80:
            break
    return output


def _normalize_reviews(items: list[Any], *, limit: int = 5) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        user = compact_text(str(item.get("user") or ""), 80)
        content = compact_text(str(item.get("content") or ""), 800)
        if not content:
            continue
        key = (user, content)
        if key in seen:
            continue
        seen.add(key)
        helpful_count = item.get("helpful_count")
        if not isinstance(helpful_count, int):
            helpful_count = None
        output.append(
            {
                "user": user,
                "content": content,
                "helpful_count": helpful_count,
                "time": compact_text(str(item.get("time") or ""), 80),
                "variant": compact_text(str(item.get("variant") or ""), 160),
            }
        )
        if len(output) >= limit:
            break
    return output


def _merge_parameters(*sources: list[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen_names: set[str] = set()
    seen_pairs: set[tuple[str, str, str]] = set()
    for source in sources:
        for item in source:
            name = compact_text(item.get("name"), 120)
            value = compact_text(item.get("value"), 500)
            group = compact_text(item.get("group"), 120) or "商品详情"
            if not name or not value:
                continue
            key = (group, name, value)
            if key in seen_pairs or name in seen_names:
                continue
            seen_pairs.add(key)
            seen_names.add(name)
            output.append({"name": name, "value": value, "group": group})
            if len(output) >= 80:
                return output
    return output


def _taobao_parameters_from_text(
    text: str | None,
) -> list[dict[str, str]]:
    text = compact_text(text, 80_000)
    if not text:
        return []

    parameter_heading = "\u53c2\u6570\u4fe1\u606f"
    detail_heading = "\u56fe\u6587\u8be6\u60c5"

    expected_labels = (
        "\u9002\u7528\u7f51\u7edc\u7c7b\u578b",
        "\u7f51\u5361\u63d2\u53e3",
        "\u662f\u5426\u65e0\u7ebf",
        "\u4f20\u8f93\u901f\u5ea6",
        "\u54c1\u724c",
        "\u578b\u53f7",
        "\u552e\u540e\u670d\u52a1",
        "\u9002\u7528\u573a\u666f",
        "\u65e0\u7ebf\u534f\u8bae",
        "\u9891\u6bb5\u7c7b\u578b",
        "\u6210\u8272",
    )

    # There can be more than one "parameter info" label:
    # one in the navigation bar and another above the actual data.
    # Score every parameter-info -> graphic-detail region and keep
    # the region containing the most real parameter labels.
    candidates: list[tuple[int, str]] = []
    search_from = 0

    while True:
        section_start = text.find(parameter_heading, search_from)
        if section_start < 0:
            break

        section_end = text.find(
            detail_heading,
            section_start + len(parameter_heading),
        )

        if section_end > section_start:
            segment = text[
                section_start + len(parameter_heading):section_end
            ]
            score = sum(
                1 for label in expected_labels
                if label in segment
            )
            candidates.append((score, segment))

        search_from = section_start + len(parameter_heading)

    if not candidates:
        return []

    score, segment = max(candidates, key=lambda item: item[0])

    if score < 3:
        return []

    output: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(name: str, value: str) -> None:
        name = compact_text(name, 120)
        value = compact_text(value, 300)

        if not name or not value or name in seen:
            return

        seen.add(name)
        output.append(
            {
                "name": name,
                "value": value,
                "group": "\u6dd8\u5b9d\u53c2\u6570\u4fe1\u606f",
            }
        )

    # These Taobao summary cards use VALUE -> LABEL.
    reverse_labels = (
        "\u9002\u7528\u7f51\u7edc\u7c7b\u578b",
        "\u7f51\u5361\u63d2\u53e3",
        "\u662f\u5426\u65e0\u7ebf",
        "\u4f20\u8f93\u901f\u5ea6",
    )

    for label in reverse_labels:
        match = re.search(
            rf"([^\s]{{1,60}})\s+{re.escape(label)}",
            segment,
        )
        if match:
            add(label, match.group(1))

    # The lower list uses LABEL -> VALUE.
    forward_labels = (
        "\u54c1\u724c",
        "\u578b\u53f7",
        "\u552e\u540e\u670d\u52a1",
        "\u9002\u7528\u573a\u666f",
        "\u65e0\u7ebf\u534f\u8bae",
        "\u9891\u6bb5\u7c7b\u578b",
        "\u6210\u8272",
    )

    positions: list[tuple[int, str]] = []

    for label in forward_labels:
        pos = segment.find(label)
        if pos >= 0:
            positions.append((pos, label))

    positions.sort(key=lambda item: item[0])

    for index, (pos, label) in enumerate(positions):
        value_start = pos + len(label)

        value_end = (
            positions[index + 1][0]
            if index + 1 < len(positions)
            else len(segment)
        )

        value = compact_text(
            segment[value_start:value_end],
            300,
        )

        add(label, value)

    return output


_DETAIL_PARAM_LABELS = (
    "品牌",
    "商品编号",
    "店铺",
    "货号",
    "型号",
    "认证型号",
    "CCC强制性认证",
    "3C证书编号",
    "国补备案型号",
    "能效等级",
    "能效网规格型号",
    "重量",
    "产品净重",
    "含底座重量",
    "产品尺寸",
    "外包装尺寸",
    "含底座尺寸",
    "裸机尺寸（不含底座）",
    "长",
    "宽",
    "高",
    "身高",
    "类型",
    "功能",
    "特色功能",
    "面板样式",
    "面板形状",
    "火力档位",
    "适用锅具",
    "是否配锅",
    "控温方式",
    "外形外观",
    "智能生态",
    "IoT智能生态产品",
    "是否内置大模型",
    "是否支持车机联动",
    "联网方式",
    "电源方式",
    "续航时间",
    "硬件形态",
    "屏幕尺寸",
    "适用场景",
    "包装形式",
    "内胆材质",
    "操控方式",
    "加热方式",
    "真空度",
    "最大吸力",
    "最低噪音",
    "额定功率",
    "额定电压",
    "上市时间",
    "包装清单",
)


def _parameters_from_detail_text(text: str | None) -> list[dict[str, str]]:
    text = compact_text(text, 50_000)
    if not text:
        return []
    start = text.find("商品详情 品牌")
    if start < 0:
        start = text.find("商品详情 商品编号")
    if start < 0:
        start = text.find("商品详情")
    if start < 0:
        return []
    end = _first_existing_index(
        text,
        ("又好又便宜", "官方购买", "以旧换新", "售后保障", "温馨提示", "收藏", "加入购物车", "立即购买"),
        start + len("商品详情"),
    )
    segment = text[start:end] if end > start else text[start : start + 5000]
    positions: list[tuple[int, str, int]] = []
    for label in _DETAIL_PARAM_LABELS:
        pattern = rf"(?<!\S){re.escape(label)}(?!\S)"
        for match in re.finditer(pattern, segment):
            positions.append((match.start(), label, match.end()))
            break
    positions.sort(key=lambda item: item[0])

    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, (_, label, value_start) in enumerate(positions):
        value_end = positions[index + 1][0] if index + 1 < len(positions) else len(segment)
        value = compact_text(segment[value_start:value_end], 500)
        if not value or value in {"暂无", "无"} or label in seen:
            continue
        seen.add(label)
        output.append({"name": label, "value": value, "group": "商品详情"})
        if len(output) >= 40:
            break
    return output


def _fallback_parameters_from_text(text: str | None) -> list[dict[str, str]]:
    text = compact_text(text, 20_000)
    if not text:
        return []

    output: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(name: str, value: str, group: str = "") -> None:
        name = compact_text(name, 120)
        value = compact_text(value, 500)
        group = compact_text(group, 120)
        if not name or not value:
            return
        key = (name, value)
        if key in seen:
            return
        seen.add(key)
        output.append({"name": name, "value": value, "group": group})

    breadcrumb = _between(text, "\u6700\u8fd1\u611f\u5174\u8da3 ", " \u8fdb\u5e97\u901b\u901b")
    if breadcrumb:
        add("\u7c7b\u76ee", breadcrumb, "\u57fa\u672c\u4fe1\u606f")

    shop_match = re.search(r">\s*([^ >]{2,40}(?:\u65d7\u8230\u5e97|\u81ea\u8425\u5e97|\u5b98\u65b9\u5e97))", text)
    if shop_match:
        add("\u5e97\u94fa", shop_match.group(1), "\u57fa\u672c\u4fe1\u606f")

    for label in (
        "\u7cfb\u5217\u54c1",
        "\u5bb9\u91cf",
        "\u670d\u52a1",
        "\u4eac\u9009\u670d\u52a1",
        "\u9001\u81f3",
    ):
        value = _section_after_label(
            text,
            label,
            stop_labels=(
                "\u7cfb\u5217\u54c1",
                "\u5bb9\u91cf",
                "\u670d\u52a1",
                "\u4eac\u9009\u670d\u52a1",
                "\u767d\u6761\u5206\u671f",
                "\u6e29\u99a8\u63d0\u793a",
                "\u6536\u85cf",
                "\u00a5",
            ),
        )
        if value:
            add(label, value, "\u9875\u9762\u53ef\u89c1\u53c2\u6570")
        if len(output) >= 20:
            break

    return output[:20]


def _fallback_reviews_from_text(
    text: str | None, *, positive: bool, limit: int = 5
) -> list[dict[str, Any]]:
    text = compact_text(text, 40_000)
    if not text:
        return []

    # Prefer the actual Taobao review heading "user reviews + count".
    actual_heading = "\u7528\u6237\u8bc4\u4ef7\u00b7"
    end_heading = "\u67e5\u770b\u5168\u90e8\u8bc4\u4ef7"

    start = text.find(actual_heading)

    if start >= 0:
        end = text.find(end_heading, start)

        if end < 0:
            end = min(len(text), start + 8000)

        segment = text[start:end]
    else:
        # raw review_text has no heading; parse the whole value.
        segment = text

    review_re = re.compile(
        r"(?P<user>[A-Za-z0-9_\u4e00-\u9fff]{2,30})\s+"
        r"(?P<date>20\d{2}-\d{2}-\d{2})\s+"
        r"(?P<content>.*?)"
        r"(?=(?:[A-Za-z0-9_\u4e00-\u9fff]{2,30}\s+"
        r"20\d{2}-\d{2}-\d{2}\s+)|$)"
    )

    negative_terms = _negative_terms()

    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for match in review_re.finditer(segment):
        user = compact_text(match.group("user"), 80)
        date = compact_text(match.group("date"), 80)
        content = compact_text(match.group("content"), 800)

        if len(content) < 4:
            continue

        has_negative = any(
            term in content
            for term in negative_terms
        )

        if positive:
            if has_negative:
                continue
        else:
            if not has_negative:
                continue

        key = (user, content)

        if key in seen:
            continue

        seen.add(key)

        output.append(
            {
                "user": user,
                "content": content,
                "helpful_count": None,
                "time": date,
                "variant": "",
            }
        )

        if len(output) >= limit:
            break

    return output

def _positive_terms() -> tuple[str, ...]:
    return (
        "\u597d\u7528",
        "\u6ee1\u610f",
        "\u63a8\u8350",
        "\u4e0d\u9519",
        "\u5f88\u597d",
        "\u65b9\u4fbf",
        "\u7b80\u5355",
        "\u503c\u5f97",
        "\u6027\u4ef7\u6bd4",
        "\u559c\u6b22",
        "\u9999",
        "\u6e05\u6d17",
        "\u987a\u624b",
    )


def _negative_terms() -> tuple[str, ...]:
    return (
        "\u4e0d\u6ee1\u610f",
        "\u4e0d\u597d\u7528",
        "\u5dee\u8bc4",
        "\u5f88\u5dee",
        "\u5931\u671b",
        "\u540e\u6094",
        "\u9000\u8d27",
        "\u574f\u4e86",
        "\u7834\u635f",
        "\u5f02\u5473",
        "\u5939\u751f",
        "\u7c98\u9505",
        "\u6ea2\u9505",
        "\u592a\u6162",
        "\u566a\u97f3",
        "\u6f0f\u6c34",
        "\u4e0d\u63a8\u8350",
    )


def _between(text: str, start_token: str, end_token: str) -> str:
    start = text.find(start_token)
    if start < 0:
        return ""
    start += len(start_token)
    end = text.find(end_token, start)
    if end < 0:
        return ""
    return compact_text(text[start:end], 500)


def _section_after_label(
    text: str, label: str, *, stop_labels: tuple[str, ...]
) -> str:
    start = text.find(f" {label} ")
    if start < 0:
        start = text.find(label)
    if start < 0:
        return ""
    start += len(label)
    end = _first_existing_index(text, tuple(item for item in stop_labels if item != label), start)
    if end <= start:
        end = min(len(text), start + 500)
    return compact_text(text[start:end], 500)


def _first_existing_index(text: str, tokens: tuple[str, ...], start: int) -> int:
    indexes = [text.find(token, start) for token in tokens]
    indexes = [index for index in indexes if index >= 0]
    return min(indexes) if indexes else len(text)


def _find_product_json_ld(nodes: list[Any]) -> dict[str, Any]:
    queue: list[Any] = list(nodes)
    while queue:
        node = queue.pop(0)
        if isinstance(node, list):
            queue.extend(node)
            continue
        if not isinstance(node, dict):
            continue
        node_type = node.get("@type")
        if node_type == "Product" or (
            isinstance(node_type, list) and "Product" in node_type
        ):
            return node
        graph = node.get("@graph")
        if isinstance(graph, list):
            queue.extend(graph)
    return {}


def _limit_json_value(value: Any, depth: int = 0) -> Any:
    """Bound JSON-LD size before returning it through MCP."""
    if depth >= 4:
        if isinstance(value, (dict, list)):
            return "[truncated]"
        return compact_text(str(value), 500)
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 30:
                output["_truncated"] = True
                break
            output[str(key)] = _limit_json_value(item, depth + 1)
        return output
    if isinstance(value, list):
        output = [_limit_json_value(item, depth + 1) for item in value[:20]]
        if len(value) > 20:
            output.append("[truncated]")
        return output
    if isinstance(value, str):
        return compact_text(value, 1200)
    return value
