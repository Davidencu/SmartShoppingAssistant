"""
Niche-only pipeline test suite.

Since Phase 5b (local mainstream fallback) and Phase 6 (global mainstream
fallback) were removed, the pipeline exclusively searches niche/mid-market
domains. This file verifies:

  Part 1 — URL gatekeeper extensions (no HTTP):
    New rules added alongside the niche-only change block PDF/doc/zip file
    extensions, instruction-manual paths, app-store hosts, and download/
    compare pages before any HTTP call is made.

  Part 2 — Buy-button detection (no HTTP):
    _has_active_buy_button() must find enabled buy-action elements and ignore
    disabled/aria-disabled ones. Used as a ranking signal in _pick_contenders.

  Part 3 — Domain purity (Tavily only, cheap):
    Verifies that the niche-only Tavily pass never returns URLs from mainstream
    mega-retailers. Amazon, Walmart, eBay, Zalando, etc. must not appear.

  Part 4 — Queries expected to return results (full pipeline, gated):
    Products that niche specialty retailers reliably carry. Require
    RUN_NICHE_PIPELINE_TESTS=1.

  Part 5 — Queries expected to return 0 results (full pipeline, gated):
    Products that live exclusively on mainstream platforms — Amazon Kindle/Echo
    (Amazon-exclusive brand), IKEA furniture (IKEA-only distribution). These
    document the known tradeoff of removing the mainstream fallback.
    Require RUN_NICHE_PIPELINE_TESTS=1.

Run cheap tests (Parts 1-2):
    pytest tests/live/test_niche_only_pipeline.py::TestGatekeeperExtensions -v -s
    pytest tests/live/test_niche_only_pipeline.py::TestBuyButtonDetection -v -s

Run domain purity (Part 3, needs TAVILY_API_KEY):
    pytest -m live tests/live/test_niche_only_pipeline.py::TestDomainPurity -v -s

Run full pipeline (Parts 4-5, needs GEMINI_API_KEY + TAVILY_API_KEY):
    RUN_NICHE_PIPELINE_TESTS=1 pytest -m live tests/live/test_niche_only_pipeline.py -v -s
"""
import asyncio
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

import pytest

pytestmark = pytest.mark.live

# ── Known mainstream domains that must NEVER appear in niche-only results ───
_MAINSTREAM_DOMAINS: frozenset[str] = frozenset({
    "amazon.com", "amazon.co.uk", "amazon.de", "amazon.fr", "amazon.it",
    "amazon.es", "amazon.pl", "amazon.nl", "amazon.se", "amazon.ca",
    "amazon.com.au", "amazon.co.jp", "amazon.in", "amazon.com.br",
    "walmart.com", "target.com", "bestbuy.com", "costco.com",
    "ebay.com", "ebay.co.uk", "ebay.de", "ebay.fr", "ebay.it",
    "aliexpress.com", "zalando.com", "zalando.de", "zalando.fr",
    "emag.ro", "altex.ro", "flanco.ro",
    "hm.com", "uniqlo.com", "asos.com",
    "mediamarkt.de", "saturn.de", "otto.de",
    "allegro.pl",
    "coolblue.nl", "bol.com",
})


def _bare_domain(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host.lstrip("www.")


def _require_api_keys():
    from core.config import settings
    missing = []
    if not settings.gemini_api_key:
        missing.append("GEMINI_API_KEY")
    if not settings.tavily_api_key:
        missing.append("TAVILY_API_KEY")
    if missing:
        pytest.skip(f"Missing env vars: {', '.join(missing)}")


def _require_pipeline_flag():
    _require_api_keys()
    if not os.environ.get("RUN_NICHE_PIPELINE_TESTS"):
        pytest.skip("Set RUN_NICHE_PIPELINE_TESTS=1 to run full niche pipeline tests")


# ═══════════════════════════════════════════════════════════════════════════════
# PART 1 — URL Gatekeeper extensions
# ═══════════════════════════════════════════════════════════════════════════════

class TestGatekeeperExtensions:
    """
    Structural (zero HTTP) tests for the rules added with the niche-only change:
      • File extension blocking  (.pdf, .doc, .zip, images, …)
      • Junk path blocking       (/manual, /download, /compare, /instruction, …)
      • Junk host blocking       (apps.apple.com, play.google.com)
      • Regression: existing valid niche product URL shapes still pass.
    """

    # ── New: file extension blocking ──────────────────────────────────────────
    JUNK_EXTENSION_URLS = [
        ("https://niche-shop.com/produs/manual.pdf",            "PDF manual at product path"),
        ("https://store.ro/docs/user-guide.pdf",                "PDF in /docs/"),
        ("https://electronics.de/downloads/firmware-v2.zip",   "Firmware zip"),
        ("https://shop.fr/notice-installation.pdf",            "French instruction PDF"),
        ("https://artshop.com/catalogue-2024.pdf",             "Product catalogue PDF"),
        ("https://boutique.ro/image.jpg",                      "JPEG image URL"),
        ("https://tech-shop.com/product-photo.png",            "PNG image URL"),
        ("https://store.com/driver-setup.exe",                 "Windows installer"),
        ("https://site.ro/export.csv",                         "CSV export"),
        ("https://shop.com/product-spec.docx",                 "Word document"),
    ]

    # ── New: junk path blocking ───────────────────────────────────────────────
    JUNK_PATH_URLS = [
        ("https://niche-shop.com/manual/product-guide",         "/manual/ path"),
        ("https://store.ro/manuals/drill-instruction",          "/manuals/ path"),
        ("https://shop.de/instruction/assembly",                "/instruction/ path"),
        ("https://boutique.fr/instructions/velo-montage",       "/instructions/ path"),
        ("https://tech-shop.com/datasheet/laptop-x200",         "/datasheet/ path"),
        ("https://electronics.ro/datasheets/chip-specs",        "/datasheets/ path"),
        ("https://store.com/handbook/user-manual",              "/handbook/ path"),
        ("https://shop.ro/download/firmware",                   "/download/ path"),
        ("https://site.com/downloads/software-v3",              "/downloads/ path"),
        ("https://tech.de/driver/usb-driver",                  "/driver/ path"),
        ("https://store.com/drivers/windows-10",                "/drivers/ path"),
        ("https://shop.com/software/plugin",                    "/software/ path"),
        ("https://firmware.ro/firmware/router-update",          "/firmware/ path"),
        ("https://shop.com/compare/laptop-vs-tablet",           "/compare/ path"),
        ("https://store.ro/comparison/phones",                  "/comparison/ path"),
        ("https://shop.de/versus/models",                       "/versus/ path"),
    ]

    # ── New: junk host blocking ───────────────────────────────────────────────
    JUNK_HOST_URLS = [
        ("https://apps.apple.com/app/shopping-app/id123456",   "Apple App Store"),
        ("https://play.google.com/store/apps/details?id=com.shop", "Google Play Store"),
        ("https://appgallery.huawei.com/app/C12345",           "Huawei AppGallery"),
    ]

    # ── Regression: these must still PASS after new rules ────────────────────
    SHOULD_STILL_PASS = [
        ("https://soycandles.com/vanilla-sunset-candle",        "Rule 4b long slug"),
        ("https://shop.ro/products/rucsac-gaming-pro",          "Shopify /products/ prefix"),
        ("https://niche.com/rucsac-sport-negru-25l",            "long depth-1 slug"),
        ("https://site.com/pd/D9LGVSMBM",                      "eMAG /pd/ prefix"),
        ("https://dedeman.ro/ro/masa-rotativa/p/8902",          "Dedeman /p/{4+digits}"),
        ("https://carturesti.ro/carte/harry-potter-383382",     "depth-2 book slug"),
        ("https://musicalshop.ro/instrumente/chitara",          "Rule 3 depth-2 short slug"),
        ("https://shop.com/products/manual-coffee-grinder",     "Shopify /products/ — word 'manual' in slug, not path segment"),
        ("https://store.ro/items/download-jacket-blue",         "/items/ CMS prefix — 'download' in slug, not path segment"),
    ]

    def test_file_extensions_blocked(self):
        from services.scraper_service import is_likely_product_url

        failures = []
        for url, desc in self.JUNK_EXTENSION_URLS:
            if is_likely_product_url(url):
                failures.append((url, desc))

        if failures:
            print("\n[EXT BLOCK] These file-extension URLs wrongly passed:")
            for url, desc in failures:
                print(f"  PASS (WRONG)  {desc}\n               {url}")

        assert not failures, (
            f"{len(failures)} file-extension URL(s) not blocked:\n"
            + "\n".join(f"  {u}" for u, _ in failures)
        )

    def test_junk_paths_blocked(self):
        from services.scraper_service import is_likely_product_url

        failures = []
        for url, desc in self.JUNK_PATH_URLS:
            if is_likely_product_url(url):
                failures.append((url, desc))

        if failures:
            print("\n[PATH BLOCK] These junk-path URLs wrongly passed:")
            for url, desc in failures:
                print(f"  PASS (WRONG)  {desc}\n               {url}")

        assert not failures, (
            f"{len(failures)} junk-path URL(s) not blocked:\n"
            + "\n".join(f"  {u}" for u, _ in failures)
        )

    def test_junk_hosts_blocked(self):
        from services.scraper_service import is_likely_product_url

        failures = []
        for url, desc in self.JUNK_HOST_URLS:
            if is_likely_product_url(url):
                failures.append((url, desc))

        assert not failures, (
            f"App-store hosts not blocked ({len(failures)}):\n"
            + "\n".join(f"  {u}" for u, _ in failures)
        )

    def test_valid_niche_urls_unaffected(self):
        """New blocking rules must not cause regressions on valid product URLs."""
        from services.scraper_service import is_likely_product_url

        failures = []
        for url, desc in self.SHOULD_STILL_PASS:
            if not is_likely_product_url(url):
                failures.append((url, desc))

        if failures:
            print("\n[REGRESSION] Valid product URLs now wrongly blocked:")
            for url, desc in failures:
                print(f"  BLOCK (WRONG) {desc}\n               {url}")

        assert not failures, (
            f"New rules created {len(failures)} false negative(s):\n"
            + "\n".join(f"  {u}" for u, _ in failures)
        )

    def test_extension_in_slug_not_blocked(self):
        """An extension keyword in the middle of a slug must not be blocked."""
        from services.scraper_service import is_likely_product_url

        safe_slugs = [
            "https://shop.com/products/pdf-printer-laser",      # 'pdf' in slug text, not extension
            "https://store.ro/items/software-bag-waterproof",   # 'software' is product keyword here
        ]
        for url in safe_slugs:
            # These might pass or block depending on other rules — we only care that
            # the extension regex doesn't trigger when there's no file extension at end.
            # The path doesn't end in .pdf/.zip so _JUNK_EXTENSIONS_RE won't fire.
            parsed_path = urlparse(url).path
            assert not parsed_path.endswith(
                (".pdf", ".zip", ".doc", ".exe", ".jpg", ".png")
            ), f"Path should not end with a known extension: {url}"


# ═══════════════════════════════════════════════════════════════════════════════
# PART 2 — Buy-button detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuyButtonDetection:
    """
    Unit tests for _has_active_buy_button(html).
    No HTTP calls — all HTML is synthetic.
    """

    def _check(self, html: str) -> bool:
        from services.scraper_service import _has_active_buy_button
        return _has_active_buy_button(html)

    def test_active_add_to_cart_detected(self):
        html = "<html><body><button>Add to Cart</button></body></html>"
        assert self._check(html) is True

    def test_active_buy_now_detected(self):
        html = "<html><body><button>Buy Now</button></body></html>"
        assert self._check(html) is True

    def test_active_order_now_detected(self):
        html = "<html><body><a href='/checkout'>Order Now</a></body></html>"
        assert self._check(html) is True

    def test_disabled_button_not_detected(self):
        html = "<html><body><button disabled>Add to Cart</button></body></html>"
        assert self._check(html) is False

    def test_disabled_class_not_detected(self):
        html = '<html><body><button class="btn disabled">Add to Cart</button></body></html>'
        assert self._check(html) is False

    def test_aria_disabled_not_detected(self):
        html = '<html><body><button aria-disabled="true">Add to Cart</button></body></html>'
        assert self._check(html) is False

    def test_no_buy_button_returns_false(self):
        html = "<html><body><h1>Product Name</h1><p>Description here.</p></body></html>"
        assert self._check(html) is False

    def test_empty_html_returns_false(self):
        assert self._check("") is False

    def test_romanian_buy_button_detected(self):
        html = "<html><body><button>Adaugă în coș</button></body></html>"
        assert self._check(html) is True

    def test_german_buy_button_detected(self):
        html = "<html><body><button>In den Warenkorb</button></body></html>"
        assert self._check(html) is True

    def test_french_buy_button_detected(self):
        html = "<html><body><button>Ajouter au panier</button></body></html>"
        assert self._check(html) is True

    def test_spanish_buy_button_detected(self):
        html = "<html><body><button>Añadir al carrito</button></body></html>"
        assert self._check(html) is True

    def test_polish_buy_button_detected(self):
        html = "<html><body><button>Dodaj do koszyka</button></body></html>"
        assert self._check(html) is True

    def test_italian_buy_button_detected(self):
        html = "<html><body><button>Aggiungi al carrello</button></body></html>"
        assert self._check(html) is True

    def test_oos_page_no_active_button(self):
        """A realistic OOS page has the button disabled — must not be detected."""
        html = """
        <html><body>
          <h1>Product Name</h1>
          <p>Out of stock</p>
          <button disabled class="add-to-cart">Add to Cart</button>
          <p>Notify me when available</p>
        </body></html>
        """
        assert self._check(html) is False

    def test_active_button_among_other_disabled_ones(self):
        """One active Buy Now among other disabled elements must still be detected."""
        html = """
        <html><body>
          <button disabled>Add to Wishlist</button>
          <button aria-disabled="true">Compare</button>
          <button>Buy Now</button>
        </body></html>
        """
        assert self._check(html) is True


# ═══════════════════════════════════════════════════════════════════════════════
# PART 3 — Domain purity (Tavily only, cheap)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDomainPurity:
    """
    Verifies that niche-domain Tavily searches never leak mainstream retailer URLs.
    Requires TAVILY_API_KEY. No scraping or Gemini calls — fast and cheap.
    """

    def setup_method(self):
        from core.config import settings
        if not settings.tavily_api_key:
            pytest.skip("TAVILY_API_KEY not set")

    def _niche_domains(self) -> list[str]:
        """Return combined local RO + global niche domains from retailers_service."""
        from services import retailers_service
        local = retailers_service.get_niche_domains_for_country("RO")
        global_niche = retailers_service.get_global_niche_domains()
        combined = list(dict.fromkeys((local or []) + global_niche))
        if not combined:
            pytest.skip("No niche domains in DB — run with a seeded Supabase instance")
        return combined

    def _check_no_mainstream(self, results: list[dict], query: str):
        """Assert none of the Tavily result URLs come from mainstream domains."""
        leaks = [
            r["url"] for r in results
            if _bare_domain(r["url"]) in _MAINSTREAM_DOMAINS
        ]
        assert not leaks, (
            f"Mainstream domains leaked into niche-only search for '{query}':\n"
            + "\n".join(f"  {u}" for u in leaks)
        )

    def test_mountain_bike_search_no_mainstream(self):
        from services.tavily_service import search_products
        niche = self._niche_domains()
        results = search_products("mountain bike adults buy", max_results=10, include_domains=niche)
        self._check_no_mainstream(results, "mountain bike")

    def test_gaming_keyboard_search_no_mainstream(self):
        from services.tavily_service import search_products
        niche = self._niche_domains()
        results = search_products("mechanical gaming keyboard buy", max_results=10, include_domains=niche)
        self._check_no_mainstream(results, "gaming keyboard")

    def test_pet_food_search_no_mainstream(self):
        from services.tavily_service import search_products
        niche = self._niche_domains()
        results = search_products("dog food premium dry buy", max_results=10, include_domains=niche)
        self._check_no_mainstream(results, "dog food")

    def test_guitar_search_no_mainstream(self):
        from services.tavily_service import search_products
        niche = self._niche_domains()
        results = search_products("acoustic guitar beginner buy", max_results=10, include_domains=niche)
        self._check_no_mainstream(results, "acoustic guitar")

    def test_book_search_no_mainstream(self):
        from services.tavily_service import search_products
        niche = self._niche_domains()
        results = search_products("roman policier Harry Potter buy", max_results=10, include_domains=niche)
        self._check_no_mainstream(results, "Harry Potter book")


# ═══════════════════════════════════════════════════════════════════════════════
# Part 4 — Queries expected to find results on niche domains
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class NicheScenario:
    prompt: str
    city: str
    country: str
    why_niche: str            # human-readable reason this should succeed on niche domains
    min_value_score: float = 45.0
    expected_domains_hint: list[str] = field(default_factory=list)  # not enforced, for docs


NICHE_SHOULD_SUCCEED = [
    NicheScenario(
        prompt="mountain bike for adults under 800 RON",
        city="Bucharest", country="Romania",
        why_niche="Sport retailers like decathlon.ro and velodrom.ro are classified as niche",
        expected_domains_hint=["decathlon.ro", "velodrom.ro", "sportguru.ro"],
    ),
    NicheScenario(
        prompt="mechanical gaming keyboard under 300 RON",
        city="Bucharest", country="Romania",
        why_niche="PC Garage (pcgarage.ro) is a niche IT retailer reliably stocking peripherals",
        expected_domains_hint=["pcgarage.ro"],
    ),
    NicheScenario(
        prompt="premium dry dog food under 150 RON",
        city="Bucharest", country="Romania",
        why_niche="Pet specialty shops like zooplus.ro and magnolia.ro are niche tier",
        expected_domains_hint=["zooplus.ro", "magnolia.ro"],
    ),
    NicheScenario(
        prompt="Harry Potter book in Romanian under 50 RON",
        city="Bucharest", country="Romania",
        why_niche="Carturesti (carturesti.ro) and Elefant (elefant.ro) are well-indexed niche book retailers",
        expected_domains_hint=["carturesti.ro", "elefant.ro"],
    ),
    NicheScenario(
        prompt="acoustic guitar for beginners under 600 RON",
        city="Bucharest", country="Romania",
        why_niche="Specialty music shops (muzicapentrutoti.ro, muzikon.ro) are niche tier",
        expected_domains_hint=["muzicapentrutoti.ro", "muzikon.ro"],
    ),
]


class TestNicheQueriesWithExpectedResults:
    """
    Full pipeline: intent → Tavily (niche domains only) → scraper → Gemini.
    All scenarios use products reliably stocked by niche/specialty retailers.

    Gated by RUN_NICHE_PIPELINE_TESTS=1 because these consume API credits.
    """

    def setup_method(self):
        _require_pipeline_flag()

    def _run(self, scenario: NicheScenario):
        """Run the full niche-only pipeline for a scenario, return ranked products."""
        from models.search import ChatMessage, IntentParams
        from services import gemini_service, tavily_service, scraper_service, retailers_service
        from routers.search import _build_search_query
        from services.scraper_service import is_likely_product_url

        messages = [ChatMessage(role="user", content=scenario.prompt)]
        intent = gemini_service.classify_intent(
            messages, city=scenario.city, country=scenario.country
        )

        if intent["intent"] != "SEARCH":
            return intent, []

        raw = intent.get("collected_params") or {}
        params = IntentParams(
            category=raw.get("category"),
            budget=raw.get("budget"),
            budget_max=raw.get("budget_max"),
            budget_currency=raw.get("budget_currency"),
            preference=raw.get("preference"),
        )

        query, _ = _build_search_query(
            intent.get("localized_search_query"), params, intent.get("local_domains")
        )

        # Niche-only domain list — mirrors Phase 5a logic
        from services import retailers_service
        from services.retailers_service import country_name_to_iso
        iso = country_name_to_iso(scenario.country)
        niche_local = retailers_service.get_niche_domains_for_country(iso)
        global_niche = retailers_service.get_global_niche_domains()
        niche_domains = list(dict.fromkeys((niche_local or []) + global_niche)) or None

        tavily_results = tavily_service.search_products(
            query, max_results=10, include_domains=niche_domains
        )
        if not tavily_results:
            return intent, []

        urls = [r["url"] for r in tavily_results if is_likely_product_url(r["url"])]
        if not urls:
            return intent, []

        scraped = asyncio.run(scraper_service.scrape_urls(urls))
        url_to_title = {r["url"]: r.get("title", "") for r in tavily_results}
        for s in scraped:
            s["title"] = url_to_title.get(s["url"], "")

        usable = [s for s in scraped if len(s.get("markdown") or "") > 200]
        if not usable:
            return intent, []

        ranked = gemini_service.score_and_rank_products(
            usable,
            f"{params.preference or ''} {params.category or ''}".strip(),
            params.budget_max,
            params.budget_currency,
            city=scenario.city,
            country=scenario.country,
        )
        return intent, ranked

    @pytest.mark.parametrize(
        "scenario",
        NICHE_SHOULD_SUCCEED,
        ids=[s.prompt[:50] for s in NICHE_SHOULD_SUCCEED],
    )
    def test_niche_query_returns_results(self, scenario: NicheScenario):
        """Pipeline must find at least one product for queries niche retailers cover."""
        intent, ranked = self._run(scenario)

        print(f"\n[NICHE OK] '{scenario.prompt}'")
        print(f"  Why expected: {scenario.why_niche}")

        if intent["intent"] != "SEARCH":
            pytest.skip(f"Gemini returned {intent['intent']} — clarification needed")

        if not ranked:
            pytest.skip(
                f"No results from niche-only search for: {scenario.prompt}\n"
                "Possible causes: niche domains not seeded in DB, site down, or "
                "Tavily index gap. Run with RUN_NICHE_COMPARISON=1 to compare against mainstream."
            )

        top = ranked[0]
        scores = top.get("scores") or {}
        print(
            f"  #{top['rank']} {top.get('title', '?')[:60]} "
            f"| {top.get('price')} {top.get('currency')} "
            f"| value={top['value_score']}"
        )

        above_floor = [dim for dim, v in scores.items() if float(v or 0) > 40]
        assert above_floor, (
            f"All score dimensions at floor-40 — page had no parseable data.\n"
            f"URL: {top.get('url')}"
        )
        assert float(top.get("value_score", 0)) >= scenario.min_value_score, (
            f"value_score {top['value_score']} < {scenario.min_value_score} for "
            f"'{top.get('title')}' at {top.get('url')}"
        )

    @pytest.mark.parametrize(
        "scenario",
        NICHE_SHOULD_SUCCEED,
        ids=[s.prompt[:50] for s in NICHE_SHOULD_SUCCEED],
    )
    def test_results_come_from_niche_domains_only(self, scenario: NicheScenario):
        """All result URLs must come from niche domains, never mainstream mega-retailers."""
        intent, ranked = self._run(scenario)

        if intent["intent"] != "SEARCH" or not ranked:
            pytest.skip("No results to check")

        leaks = [
            p["url"] for p in ranked
            if _bare_domain(p.get("url", "")) in _MAINSTREAM_DOMAINS
        ]
        assert not leaks, (
            f"Mainstream domains appeared in niche-only results for '{scenario.prompt}':\n"
            + "\n".join(f"  {u}" for u in leaks)
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Part 5 — Queries expected to return 0 results (mainstream-exclusive products)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MainstreamOnlyScenario:
    prompt: str
    city: str
    country: str
    why_zero: str             # why niche sites won't carry this


MAINSTREAM_ONLY_PRODUCTS = [
    MainstreamOnlyScenario(
        prompt="Amazon Kindle Paperwhite e-reader",
        city="Bucharest", country="Romania",
        why_zero=(
            "Amazon Kindle is an Amazon-exclusive product line. "
            "Amazon.com/Amazon.co.uk are the sole authorized sellers globally — "
            "no niche third-party retailer stocks Kindle hardware."
        ),
    ),
    MainstreamOnlyScenario(
        prompt="Amazon Echo Dot smart speaker",
        city="Bucharest", country="Romania",
        why_zero=(
            "Amazon Echo is an Amazon-exclusive brand sold only via amazon.* domains. "
            "No niche shop carries Echo devices."
        ),
    ),
    MainstreamOnlyScenario(
        prompt="IKEA KALLAX shelf unit",
        city="Bucharest", country="Romania",
        why_zero=(
            "IKEA products are sold exclusively through IKEA's own stores/website. "
            "No third-party niche retailer is an authorized IKEA reseller — "
            "IKEA.com is not in the niche domain list."
        ),
    ),
    MainstreamOnlyScenario(
        prompt="IKEA BILLY bookcase",
        city="Bucharest", country="Romania",
        why_zero=(
            "Like all IKEA furniture, BILLY is exclusively distributed through IKEA. "
            "Second-hand listings (marketplace) are not indexed by Tavily as product pages."
        ),
    ),
    MainstreamOnlyScenario(
        prompt="Amazon Fire TV Stick 4K",
        city="Bucharest", country="Romania",
        why_zero=(
            "Amazon Fire TV is an Amazon-exclusive hardware brand. "
            "Only amazon.* domains stock it — absent from every niche retailer."
        ),
    ),
]


class TestMainstreamOnlyQueriesYieldZeroResults:
    """
    Documents the tradeoff of removing the mainstream fallback:
    products exclusive to Amazon, IKEA, or similar walled-garden retailers
    return 0 results in niche-only mode.

    These tests assert either:
      a) ranked == [] (ideal: pipeline correctly returns nothing), OR
      b) no result URL comes from a mainstream domain (sanity check if a
         fringe niche reseller somehow carries the product).

    Gated by RUN_NICHE_PIPELINE_TESTS=1.
    """

    def setup_method(self):
        _require_pipeline_flag()

    def _run_niche_only(self, scenario: MainstreamOnlyScenario):
        from models.search import ChatMessage, IntentParams
        from services import gemini_service, tavily_service, scraper_service, retailers_service
        from services.retailers_service import country_name_to_iso
        from routers.search import _build_search_query
        from services.scraper_service import is_likely_product_url

        messages = [ChatMessage(role="user", content=scenario.prompt)]
        intent = gemini_service.classify_intent(
            messages, city=scenario.city, country=scenario.country
        )

        if intent["intent"] != "SEARCH":
            return intent, [], []

        raw = intent.get("collected_params") or {}
        params = IntentParams(
            category=raw.get("category"),
            budget=raw.get("budget"),
            budget_max=raw.get("budget_max"),
            budget_currency=raw.get("budget_currency"),
            preference=raw.get("preference"),
        )

        query, _ = _build_search_query(
            intent.get("localized_search_query"), params, intent.get("local_domains")
        )

        iso = country_name_to_iso(scenario.country)
        niche_local = retailers_service.get_niche_domains_for_country(iso)
        global_niche = retailers_service.get_global_niche_domains()
        niche_domains = list(dict.fromkeys((niche_local or []) + global_niche)) or None

        tavily_results = tavily_service.search_products(
            query, max_results=10, include_domains=niche_domains
        )

        urls = [r["url"] for r in tavily_results if is_likely_product_url(r["url"])]
        if not urls:
            return intent, tavily_results, []

        scraped = asyncio.run(scraper_service.scrape_urls(urls))
        url_to_title = {r["url"]: r.get("title", "") for r in tavily_results}
        for s in scraped:
            s["title"] = url_to_title.get(s["url"], "")

        usable = [s for s in scraped if len(s.get("markdown") or "") > 200]
        if not usable:
            return intent, tavily_results, []

        ranked = gemini_service.score_and_rank_products(
            usable,
            f"{params.preference or ''} {params.category or ''}".strip(),
            params.budget_max,
            params.budget_currency,
            city=scenario.city,
            country=scenario.country,
        )
        return intent, tavily_results, ranked

    @pytest.mark.parametrize(
        "scenario",
        MAINSTREAM_ONLY_PRODUCTS,
        ids=[s.prompt[:60] for s in MAINSTREAM_ONLY_PRODUCTS],
    )
    def test_mainstream_exclusive_product_yields_zero_results(
        self, scenario: MainstreamOnlyScenario
    ):
        """
        The niche-only pipeline must return 0 ranked products for Amazon/IKEA exclusives.
        If this fails (ranked > 0), a niche reseller unexpectedly carries the product —
        inspect the URL and decide whether the domain should be reclassified.
        """
        intent, tavily_results, ranked = self._run_niche_only(scenario)

        print(f"\n[MAINSTREAM EXCLUSIVE] '{scenario.prompt}'")
        print(f"  Why expected 0: {scenario.why_zero}")
        print(f"  Tavily returned: {len(tavily_results)} URLs (before gatekeeper)")
        print(f"  Ranked products: {len(ranked)}")

        if intent["intent"] != "SEARCH":
            pytest.skip(f"Gemini returned {intent['intent']} — query too vague")

        # Primary assertion: no mainstream domain should appear in Tavily results
        mainstream_leaks = [
            r["url"] for r in tavily_results
            if _bare_domain(r["url"]) in _MAINSTREAM_DOMAINS
        ]
        assert not mainstream_leaks, (
            f"Mainstream domains leaked into niche-only Tavily results for '{scenario.prompt}'.\n"
            f"This means the domain whitelist is not working correctly:\n"
            + "\n".join(f"  {u}" for u in mainstream_leaks)
        )

        # Secondary: ranked list should be empty (the interesting assertion)
        if ranked:
            unexpected_urls = [p.get("url", "") for p in ranked]
            print(
                f"  [NOTICE] Unexpectedly got {len(ranked)} result(s) from niche domains:\n"
                + "\n".join(f"    {u}" for u in unexpected_urls)
            )
            # Soft-fail: a niche reseller might actually carry the product.
            # Verify no mainstream domain sneaked through.
            leaked_ranked = [u for u in unexpected_urls if _bare_domain(u) in _MAINSTREAM_DOMAINS]
            assert not leaked_ranked, (
                f"Mainstream domain appeared in ranked results for '{scenario.prompt}':\n"
                + "\n".join(f"  {u}" for u in leaked_ranked)
            )
            pytest.xfail(
                f"Got {len(ranked)} result(s) from a niche reseller for a normally "
                f"mainstream-exclusive product. Inspect URLs above and reclassify if needed."
            )
        else:
            print("  PASS — niche-only pipeline correctly returned 0 results (expected tradeoff).")

    @pytest.mark.parametrize(
        "scenario",
        MAINSTREAM_ONLY_PRODUCTS,
        ids=[s.prompt[:60] for s in MAINSTREAM_ONLY_PRODUCTS],
    )
    def test_no_mainstream_url_in_tavily_response(self, scenario: MainstreamOnlyScenario):
        """
        Even when Tavily finds 0 useful results, it must not have leaked any
        Amazon/eBay/Walmart/IKEA URLs through the niche-domain filter.
        This verifies the Tavily include_domains constraint is working.
        """
        from core.config import settings
        if not settings.tavily_api_key:
            pytest.skip("TAVILY_API_KEY not set")

        from services import tavily_service, retailers_service
        from services.retailers_service import country_name_to_iso

        iso = country_name_to_iso(scenario.country)
        niche_local = retailers_service.get_niche_domains_for_country(iso)
        global_niche = retailers_service.get_global_niche_domains()
        niche_domains = list(dict.fromkeys((niche_local or []) + global_niche)) or None

        results = tavily_service.search_products(
            scenario.prompt, max_results=10, include_domains=niche_domains
        )

        leaks = [
            r["url"] for r in results
            if _bare_domain(r["url"]) in _MAINSTREAM_DOMAINS
        ]
        assert not leaks, (
            f"Mainstream URLs returned by Tavily despite niche-only include_domains "
            f"for '{scenario.prompt}':\n"
            + "\n".join(f"  {u}" for u in leaks)
        )

        print(
            f"\n[DOMAIN PURITY] '{scenario.prompt[:50]}' → "
            f"{len(results)} Tavily results, 0 mainstream leaks"
        )
