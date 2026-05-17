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
