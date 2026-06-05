"""
JSON-LD structured-data extraction for product value scoring.

Called after scraping; injects machine-verified price / availability / rating
at the top of each product block in the Gemini scoring prompt so the model does not
have to guess from prose text.

Edge cases handled:
  - Root is a JSON array  : [ {"@type": "Product", ...}, ... ]
  - Root is a single dict : {"@type": "Product", ...}
  - offers is a list      : product.offers = [ {"price": ...}, ... ]
  - offers is nested dict : product.offers.price / product.offers.priceCurrency
  - price is a string     : "1 799,00" → 1799.0
"""
import functools
import json
import logging
import re

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# How many unique HTML pages to keep parsed results for.
# Popular products (gaming laptops, phones) are requested by many concurrent users;
# the cache turns O(n·parse) into O(1·parse + (n-1)·lookup) for identical pages.
# At 256 entries × ~50 KB avg HTML ≈ 13 MB upper bound on additional retained strings.
_JSONLD_CACHE_SIZE = 256


def _extract_microdata_rating(html: str) -> dict:
    """
    Fallback rating extraction from HTML microdata and common data-attributes.
    Covers sites that omit aggregateRating from their JSON-LD but emit it as
    itemprop attributes or data-* tags (e.g. eMAG, Altex, Amazon variants).
    """
    facts: dict = {}

    # Schema.org microdata — <meta itemprop="ratingValue" content="4.7">
    rv = None
    for pattern in (
        r'itemprop=["\']ratingValue["\'][^>]*content=["\']([0-9][0-9.,]*)["\']',
        r'content=["\']([0-9][0-9.,]*)["\'][^>]*itemprop=["\']ratingValue["\']',
        r'data-(?:rating|score|avg(?:erage)?-?rating)["\'\s>=]+([0-9][0-9.,]*)',
    ):
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            try:
                rv = float(m.group(1).replace(",", "."))
                break
            except ValueError:
                pass

    if rv is None or not (0.0 < rv <= 5.0):
        return facts

    rating_str = f"{rv}/5"

    # Review / rating count
    rc = None
    for pattern in (
        r'itemprop=["\'](?:reviewCount|ratingCount)["\'][^>]*content=["\'](\d+)["\']',
        r'content=["\'](\d+)["\'][^>]*itemprop=["\'](?:reviewCount|ratingCount)["\']',
        r'data-(?:review|rating)-?count["\'\s>=]+(\d+)',
    ):
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            rc = m.group(1)
            break

    if rc:
        rating_str += f" ({rc} reviews)"

    facts["rating"] = rating_str
    return facts


@functools.lru_cache(maxsize=_JSONLD_CACHE_SIZE)
def extract_jsonld_facts(text: str) -> dict:
    """
    Search for Schema.org Product JSON-LD in any text (raw HTML or Markdown).
    Returns a dict with confirmed facts, or {} if nothing found.

    Results are LRU-cached by the full text string.  When many users request
    the same popular product (e.g. a gaming laptop), the regex + JSON parsing
    runs once and every subsequent caller gets the cached dict in O(1).
    Callers must NOT mutate the returned dict (it is the live cache value).
    """
    raw_blocks: list[str] = []

    # 1. HTML <script type="application/ld+json"> tags (Jina sometimes preserves these)
    raw_blocks.extend(
        m.group(1)
        for m in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>',
            text,
            re.IGNORECASE,
        )
    )

    # 2. Markdown fenced code blocks  ```json ... ```
    raw_blocks.extend(
        m.group(1)
        for m in re.finditer(r"```(?:json|javascript)?\s*([\s\S]*?)\s*```", text)
    )

    # 3. Bare JSON arrays / objects that contain "@type" (last resort, greedy)
    raw_blocks.extend(
        m.group(0)
        for m in re.finditer(
            r'(?:^|[\n\r])(\[[\s\S]*?"@type"[\s\S]*?\]|\{[\s\S]*?"@type"[\s\S]*?\})',
            text,
        )
    )

    for raw in raw_blocks:
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue

        items: list = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type", "")
            if isinstance(item_type, list):
                item_type = " ".join(str(t) for t in item_type)
            if "product" not in str(item_type).lower():
                continue
            facts = _extract_from_product(item)
            if facts:
                # Fill any missing rating with microdata fallback
                if "rating" not in facts:
                    md_rating = _extract_microdata_rating(text)
                    if md_rating:
                        facts.update(md_rating)
                logger.debug("[JSON-LD] extracted: %s", facts)
                return facts

    # No JSON-LD Product block — try microdata rating alone
    microdata = _extract_microdata_rating(text)
    if microdata:
        logger.debug("[microdata] extracted: %s", microdata)
        return microdata

    return {}


def _extract_from_product(product: dict) -> dict:
    facts: dict = {}

    if name := product.get("name"):
        facts["name"] = str(name)

    brand = product.get("brand")
    if isinstance(brand, dict):
        facts["brand"] = brand.get("name", "")
    elif isinstance(brand, str):
        facts["brand"] = brand

    # Offers — normalise to a single offer dict
    offers = product.get("offers") or product.get("Offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if isinstance(offers, dict):
        _extract_offer(offers, facts)

    # Aggregate rating
    agg = product.get("aggregateRating")
    if isinstance(agg, dict):
        rv = agg.get("ratingValue")
        rc = agg.get("reviewCount") or agg.get("ratingCount")
        if rv is not None:
            rating_str = f"{rv}/5"
            if rc:
                rating_str += f" ({rc} reviews)"
            facts["rating"] = rating_str

    return facts


def _extract_offer(offer: dict, facts: dict) -> None:
    raw_price = offer.get("price") or offer.get("Price")
    if raw_price is not None:
        try:
            # Handle "1 799,00" → 1799.0  and  "1799.00" → 1799.0
            cleaned = re.sub(r"[\s ]", "", str(raw_price)).replace(",", ".")
            facts["price"] = float(cleaned)
        except (ValueError, TypeError):
            pass

    currency = offer.get("priceCurrency") or offer.get("PriceCurrency")
    if currency:
        facts["currency"] = str(currency).strip().upper()

    availability = str(offer.get("availability") or offer.get("Availability") or "")
    av = availability.lower()
    if "instock" in av or "in_stock" in av:
        facts["availability"] = "In Stock"
    elif "outofstock" in av or "out_of_stock" in av:
        facts["availability"] = "Out of Stock"
    elif "preorder" in av or "pre-order" in av:
        facts["availability"] = "Pre-order"
    elif "discontinued" in av:
        facts["availability"] = "Discontinued"

    # Schema.org OfferShippingDetails — already on the page, zero extra requests
    shipping = offer.get("shippingDetails")
    if isinstance(shipping, list):
        shipping = shipping[0] if shipping else None
    if isinstance(shipping, dict):
        _extract_shipping_details(shipping, facts)


def _extract_shipping_details(shipping: dict, facts: dict) -> None:
    """Pull shipping cost + delivery window from OfferShippingDetails."""
    rate = shipping.get("shippingRate")
    if isinstance(rate, list):
        rate = rate[0] if rate else None
    if isinstance(rate, dict) and "shipping_cost" not in facts:
        raw = rate.get("value") if "value" in rate else rate.get("price")
        curr = rate.get("currency") or rate.get("priceCurrency")
        if raw is not None:
            try:
                facts["shipping_cost"] = float(str(raw).replace(",", "."))
                if curr:
                    facts["shipping_currency"] = str(curr).strip().upper()
            except (ValueError, TypeError):
                pass

    dt = shipping.get("deliveryTime")
    if isinstance(dt, dict) and "delivery_days" not in facts:
        transit = dt.get("transitTime") or dt
        if isinstance(transit, dict):
            mn = transit.get("minValue")
            mx = transit.get("maxValue")
            if mn is not None and mx is not None:
                facts["delivery_days"] = f"{int(mn)}–{int(mx)}"
            elif mx is not None:
                facts["delivery_days"] = str(int(mx))

    if shipping.get("doesNotShip") is True and "availability" not in facts:
        facts["availability"] = "Cannot Ship"


@functools.lru_cache(maxsize=_JSONLD_CACHE_SIZE)
def extract_bs4_facts(html: str) -> dict:
    """
    Secondary structured-data extractor that covers signals JSON-LD misses:

      1. Open Graph / Product-namespace <meta> tags  (og:price:amount, product:availability …)
      2. Schema.org itemprop attributes              (price, priceCurrency, availability …)
      3. aria-label star ratings                     ("4.7 out of 5", "4.7 din 5 stele" …)
      4. data-* price attributes                     (data-price, data-gtm-price …)
      5. og:site_name / application-name             → seller context for trust scoring

    Returns a dict in the same format as extract_jsonld_facts.
    JSON-LD is authoritative; callers should merge with JSON-LD winning on conflicts.
    Callers must NOT mutate the returned dict.
    """
    facts: dict = {}
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:
        logger.debug("[BS4] parse error: %s", exc)
        return facts

    # helpers

    def _meta_content(*props: str, by_name: bool = False) -> str:
        key = "name" if by_name else "property"
        for prop in props:
            tag = soup.find("meta", {key: prop})
            if tag:
                return (tag.get("content") or "").strip()
        return ""

    def _parse_price(raw: str) -> float | None:
        cleaned = re.sub(r"[^\d.,]", "", raw).replace(",", ".")
        # "1.799.00" → keep only the last decimal group
        if cleaned.count(".") > 1:
            cleaned = cleaned.replace(".", "", cleaned.count(".") - 1)
        try:
            v = float(cleaned)
            return v if v > 0 else None
        except ValueError:
            return None

    def _norm_availability(raw: str) -> str | None:
        lw = raw.lower()
        if any(k in lw for k in ("instock", "in_stock", "in stock", "available", "disponibil")):
            return "In Stock"
        if any(k in lw for k in ("outofstock", "out_of_stock", "out of stock",
                                  "epuizat", "indisponibil", "unavailable")):
            return "Out of Stock"
        if any(k in lw for k in ("preorder", "pre-order", "pre_order")):
            return "Pre-order"
        return None

    # 1. Open Graph / Product-namespace meta tags

    if "price" not in facts:
        raw = _meta_content("og:price:amount", "product:price:amount")
        if raw:
            v = _parse_price(raw)
            if v:
                facts["price"] = v

    if "currency" not in facts:
        raw = _meta_content("og:price:currency", "product:price:currency")
        if raw:
            facts["currency"] = raw.upper()

    if "availability" not in facts:
        raw = _meta_content("og:availability", "product:availability")
        if raw:
            av = _norm_availability(raw)
            if av:
                facts["availability"] = av

    _rv: float | None = None
    _rc: str | None = None

    raw = _meta_content("product:rating:value")
    if raw:
        try:
            v = float(raw)
            if 0.0 < v <= 5.0:
                _rv = v
        except ValueError:
            pass

    raw = _meta_content("product:rating:count", "product:review_count")
    if raw:
        rc = re.sub(r"\D", "", raw)
        if rc:
            _rc = rc

    # Site name → seller identity (helps trust scoring)
    if "seller" not in facts:
        raw = _meta_content("og:site_name") or _meta_content("application-name", by_name=True)
        if raw:
            facts["seller"] = raw

    # 2. Schema.org itemprop (content= attribute takes priority over text)

    if "price" not in facts:
        tag = soup.find(attrs={"itemprop": "price"})
        if tag:
            raw = tag.get("content") or tag.get_text(strip=True)
            if raw:
                v = _parse_price(raw)
                if v:
                    facts["price"] = v

    if "currency" not in facts:
        tag = soup.find(attrs={"itemprop": "priceCurrency"})
        if tag:
            raw = tag.get("content") or tag.get_text(strip=True)
            if raw:
                facts["currency"] = raw.strip().upper()

    if "availability" not in facts:
        tag = soup.find(attrs={"itemprop": "availability"})
        if tag:
            # <link itemprop="availability" href="schema.org/InStock"> or text
            raw = tag.get("href") or tag.get("content") or tag.get_text(strip=True)
            if raw:
                av = _norm_availability(raw)
                if av:
                    facts["availability"] = av

    if _rv is None:
        tag = soup.find(attrs={"itemprop": "ratingValue"})
        if tag:
            raw = tag.get("content") or tag.get_text(strip=True)
            try:
                v = float(raw.replace(",", "."))
                if 0.0 < v <= 5.0:
                    _rv = v
            except (ValueError, AttributeError):
                pass

    if _rc is None:
        for ip in ("reviewCount", "ratingCount"):
            tag = soup.find(attrs={"itemprop": ip})
            if tag:
                raw = re.sub(r"\D", "", tag.get("content") or tag.get_text(strip=True))
                if raw:
                    _rc = raw
                    break

    # 3. aria-label star ratings

    if _rv is None:
        for el in soup.find_all(attrs={"aria-label": True}):
            label = el["aria-label"]
            # "4.7 out of 5 stars", "4.7 din 5 stele", "4,7 de 5", "rated 4.7"
            m = re.search(
                r'(\d[.,]\d+|\d+)\s*(?:out\s+of|din|von|sur|de|\/)\s*5',
                label, re.IGNORECASE,
            )
            if not m:
                m = re.search(r'rated?\s+(\d[.,]\d+|\d+)', label, re.IGNORECASE)
            if m:
                try:
                    v = float(m.group(1).replace(",", "."))
                    if 0.0 < v <= 5.0:
                        _rv = v
                        # Try to find a nearby review count in the same element's text
                        nearby = el.get_text(" ", strip=True)
                        rc_m = re.search(r'(\d[\d\s,\.]+)\s*(?:review|rating|pareri|avis|Bewert)', nearby, re.IGNORECASE)
                        if rc_m and _rc is None:
                            _rc = re.sub(r"\D", "", rc_m.group(1))
                        break
                except ValueError:
                    pass

    # 4. data-* price attributes (GTM / GA tracking payloads)

    if "price" not in facts:
        for attr in ("data-price", "data-product-price", "data-price-amount",
                     "data-gtm-price", "data-sale-price", "data-final-price"):
            tag = soup.find(attrs={attr: True})
            if tag:
                v = _parse_price(str(tag[attr]))
                if v:
                    facts["price"] = v
                    break

    # Assemble rating string

    if _rv is not None and "rating" not in facts:
        rating_str = f"{_rv}/5"
        if _rc:
            rating_str += f" ({_rc} reviews)"
        facts["rating"] = rating_str

    if facts:
        logger.debug("[BS4] extracted: %s", facts)
    return facts


def build_facts_header(jsonld: dict) -> str:
    """
    Convert extracted JSON-LD facts into a prompt-ready authoritative header block.
    Returns an empty string when no facts are available.
    """
    if not jsonld:
        return ""

    lines: list[str] = []
    if "name" in jsonld:
        lines.append(f"CONFIRMED NAME: {jsonld['name']}")
    if "brand" in jsonld:
        lines.append(f"CONFIRMED BRAND: {jsonld['brand']}")
    if "price" in jsonld:
        price_str = str(jsonld["price"])
        if "currency" in jsonld:
            price_str += f" {jsonld['currency']}"
        lines.append(f"CONFIRMED PRICE: {price_str}")
    if "availability" in jsonld:
        lines.append(f"CONFIRMED AVAILABILITY: {jsonld['availability']}")
    if "rating" in jsonld:
        lines.append(f"CONFIRMED RATING: {jsonld['rating']}")
    if "seller" in jsonld:
        lines.append(f"CONFIRMED SELLER: {jsonld['seller']}")
    if "shipping_cost" in jsonld:
        raw_cost = jsonld["shipping_cost"]
        if raw_cost == 0:
            cost_str = "FREE"
        else:
            cost_str = str(raw_cost)
            if "shipping_currency" in jsonld:
                cost_str += f" {jsonld['shipping_currency']}"
        lines.append(f"CONFIRMED SHIPPING COST: {cost_str}")
    if "delivery_days" in jsonld:
        lines.append(f"CONFIRMED DELIVERY: {jsonld['delivery_days']} business days")

    if not lines:
        return ""

    return (
        "### MACHINE-VERIFIED DATA (Schema.org JSON-LD — authoritative)\n"
        + "\n".join(f"• {l}" for l in lines)
        + "\n"
        "These values are extracted from structured data embedded in the page. "
        "Use them directly for budget checks and scoring. "
        "Do NOT override them with text-parsed guesses.\n\n"
    )
