"""Unit tests for the JSON-LD extraction service."""
import pytest
from services.jsonld_service import extract_jsonld_facts, build_facts_header


class TestExtractJsonldFacts:

    # ── Root shapes ────────────────────────────────────────────────────────────

    def test_single_dict_root(self):
        html = """<script type="application/ld+json">
        {
          "@context": "https://schema.org/",
          "@type": "Product",
          "name": "ASUS VivoBook 16",
          "offers": { "price": "1799.00", "priceCurrency": "RON",
                      "availability": "https://schema.org/InStock" }
        }
        </script>"""
        facts = extract_jsonld_facts(html)
        assert facts["price"] == 1799.0
        assert facts["currency"] == "RON"
        assert facts["availability"] == "In Stock"
        assert facts["name"] == "ASUS VivoBook 16"

    def test_list_root(self):
        html = """<script type="application/ld+json">
        [
          { "@type": "BreadcrumbList", "itemListElement": [] },
          { "@type": "Product", "name": "Lenovo IdeaPad 5",
            "offers": { "price": "1950", "priceCurrency": "RON",
                        "availability": "https://schema.org/InStock" } }
        ]
        </script>"""
        facts = extract_jsonld_facts(html)
        assert facts["price"] == 1950.0
        assert facts["name"] == "Lenovo IdeaPad 5"

    # ── Offers shapes ──────────────────────────────────────────────────────────

    def test_offers_as_list(self):
        html = """<script type="application/ld+json">
        { "@type": "Product", "name": "HP Pavilion",
          "offers": [
            { "price": "1600", "priceCurrency": "RON",
              "availability": "https://schema.org/InStock" },
            { "price": "1650", "priceCurrency": "RON" }
          ] }
        </script>"""
        facts = extract_jsonld_facts(html)
        # Should pick the first offer
        assert facts["price"] == 1600.0
        assert facts["availability"] == "In Stock"

    def test_nested_offers_with_extra_wrapper(self):
        html = """<script type="application/ld+json">
        { "@type": "Product", "name": "Samsung Galaxy S24",
          "offers": {
            "@type": "AggregateOffer",
            "priceCurrency": "RON",
            "price": "3299"
          } }
        </script>"""
        facts = extract_jsonld_facts(html)
        assert facts["price"] == 3299.0
        assert facts["currency"] == "RON"

    # ── Price string formats ───────────────────────────────────────────────────

    def test_price_with_space_and_comma(self):
        """Romanian format: "1 799,00" → 1799.0"""
        html = """<script type="application/ld+json">
        { "@type": "Product", "name": "TV",
          "offers": { "price": "1 799,00", "priceCurrency": "RON" } }
        </script>"""
        facts = extract_jsonld_facts(html)
        assert facts["price"] == 1799.0

    def test_price_as_integer_string(self):
        html = """<script type="application/ld+json">
        { "@type": "Product", "name": "Mouse",
          "offers": { "price": "149", "priceCurrency": "RON" } }
        </script>"""
        facts = extract_jsonld_facts(html)
        assert facts["price"] == 149.0

    # ── Availability variants ─────────────────────────────────────────────────

    def test_out_of_stock_schema_url(self):
        html = """<script type="application/ld+json">
        { "@type": "Product", "name": "X",
          "offers": { "price": "100", "priceCurrency": "RON",
                      "availability": "https://schema.org/OutOfStock" } }
        </script>"""
        facts = extract_jsonld_facts(html)
        assert facts["availability"] == "Out of Stock"

    def test_preorder_availability(self):
        html = """<script type="application/ld+json">
        { "@type": "Product", "name": "X",
          "offers": { "price": "500", "priceCurrency": "RON",
                      "availability": "https://schema.org/PreOrder" } }
        </script>"""
        facts = extract_jsonld_facts(html)
        assert facts["availability"] == "Pre-order"

    # ── Sources ────────────────────────────────────────────────────────────────

    def test_markdown_code_block(self):
        md = '''Some text above.

```json
{ "@type": "Product", "name": "Laptop",
  "offers": { "price": "2000", "priceCurrency": "EUR",
              "availability": "https://schema.org/InStock" } }
```

Some text below.'''
        facts = extract_jsonld_facts(md)
        assert facts["price"] == 2000.0
        assert facts["currency"] == "EUR"

    def test_aggregate_rating(self):
        html = """<script type="application/ld+json">
        { "@type": "Product", "name": "Headphones",
          "offers": { "price": "299", "priceCurrency": "RON",
                      "availability": "https://schema.org/InStock" },
          "aggregateRating": { "ratingValue": "4.6", "reviewCount": "312" } }
        </script>"""
        facts = extract_jsonld_facts(html)
        assert facts["rating"] == "4.6/5 (312 reviews)"

    def test_returns_empty_dict_when_no_jsonld(self):
        assert extract_jsonld_facts("No structured data here at all.") == {}

    def test_returns_empty_dict_for_non_product_type(self):
        html = """<script type="application/ld+json">
        { "@type": "WebSite", "url": "https://example.com" }
        </script>"""
        assert extract_jsonld_facts(html) == {}

    # ── Microdata fallback ────────────────────────────────────────────────────

    def test_microdata_itemprop_rating_with_review_count(self):
        """Pages with Schema.org microdata but no JSON-LD should return a rating."""
        html = """
        <div itemscope itemtype="https://schema.org/Product">
          <meta itemprop="ratingValue" content="4.7">
          <meta itemprop="reviewCount" content="832">
        </div>"""
        facts = extract_jsonld_facts(html)
        assert facts.get("rating") == "4.7/5 (832 reviews)"

    def test_microdata_rating_without_review_count(self):
        html = '<meta itemprop="ratingValue" content="4.2">'
        facts = extract_jsonld_facts(html)
        assert facts.get("rating") == "4.2/5"

    def test_data_rating_attribute(self):
        html = '<div class="stars" data-rating="3.9" data-review-count="55"></div>'
        facts = extract_jsonld_facts(html)
        assert facts.get("rating") == "3.9/5 (55 reviews)"

    def test_microdata_fills_missing_rating_on_jsonld_product(self):
        """JSON-LD Product without aggregateRating — microdata should fill the gap."""
        html = """<script type="application/ld+json">
        { "@type": "Product", "name": "Tablet",
          "offers": { "price": "999", "priceCurrency": "RON",
                      "availability": "https://schema.org/InStock" } }
        </script>
        <meta itemprop="ratingValue" content="4.4">
        <meta itemprop="reviewCount" content="210">"""
        facts = extract_jsonld_facts(html)
        assert facts["price"] == 999.0
        assert facts["rating"] == "4.4/5 (210 reviews)"

    def test_microdata_rating_out_of_range_ignored(self):
        """A ratingValue > 5 or <= 0 should not produce a rating entry."""
        html = '<meta itemprop="ratingValue" content="9.5">'
        facts = extract_jsonld_facts(html)
        assert "rating" not in facts

    # ── build_facts_header ────────────────────────────────────────────────────

    def test_build_facts_header_with_all_fields(self):
        jsonld = {
            "name": "ASUS VivoBook",
            "brand": "ASUS",
            "price": 1799.0,
            "currency": "RON",
            "availability": "In Stock",
            "rating": "4.5/5 (200 reviews)",
        }
        header = build_facts_header(jsonld)
        assert "CONFIRMED PRICE: 1799.0 RON" in header
        assert "CONFIRMED AVAILABILITY: In Stock" in header
        assert "CONFIRMED RATING: 4.5/5 (200 reviews)" in header
        assert "authoritative" in header.lower()

    def test_build_facts_header_empty_returns_empty_string(self):
        assert build_facts_header({}) == ""

    def test_build_facts_header_price_without_currency(self):
        header = build_facts_header({"price": 99.0})
        assert "CONFIRMED PRICE: 99.0" in header
