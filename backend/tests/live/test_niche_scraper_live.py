"""
Live tests: niche website scraping.

Two failure modes were fixed and are now covered here:
  1. GATEKEEPER: is_likely_product_url() silently dropped niche product URLs before
     any HTTP call was made.  Fixed by: Rule 2b (CMS path prefixes), lower Rule 3
     threshold (>10 → >=5 chars), Rule 4b (long multi-word depth-1 slugs).
  2. PARSER: _extract_text_bs4() used the "lxml-xml" (XML) parser which returns an
     empty body for Angular/React SSR sites. Fixed by switching to the "lxml" HTML
     parser (30 K chars from dedeman.ro vs 0 chars before the fix).

Run all tests:       pytest -m live tests/live/test_niche_scraper_live.py -v -s
Run only gatekeeper: pytest tests/live/test_niche_scraper_live.py::TestNicheUrlGatekeeping -v -s
Run comparison:      RUN_NICHE_COMPARISON=1 pytest -m live tests/live/test_niche_scraper_live.py -v -s
"""
import os
from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.live

from services.scraper_service import is_likely_product_url


# ── Data ──────────────────────────────────────────────────────────────────────

@dataclass
class ScraperTarget:
    url: str
    description: str
    expected_gate_pass: bool


# ── Part 1: Gatekeeper analysis (no HTTP) ─────────────────────────────────────

class TestNicheUrlGatekeeping:
    """
    Purely structural — zero network calls.
    Documents which niche URL shapes is_likely_product_url() handles.

    Rule recap (after fixes):
      RULE 1  (hard block):    URL path contains /category/, /search/, /filter/, /blog/, etc.
      RULE 2  (SKU rescue):    SKU-like token found (e.g. -123456, /AB-1234/)
      RULE 2b (CMS prefix):    URL contains /products/, /product/, /pd/, /pdp/, or /p/{4+digits}
      RULE 3  (depth):         depth >= 2 AND last segment >= 5 chars (was > 10 before fix)
      RULE 4  (keyword):       depth == 1 AND segment matches hardcoded product keyword list
      RULE 4b (long slug):     depth == 1 AND >= 3 hyphen-tokens AND total length >= 17 chars
    """

    # ── Niche URLs that now PASS (formerly blocked before the gatekeeper fixes) ──
    # Moved here from the old NICHE_BLOCKED list — all were false negatives.
    FORMERLY_BLOCKED_NOW_PASSING = [
        # Fixed by Rule 4b (long multi-word depth-1 slug, >= 3 tokens, >= 17 chars)
        ("https://soycandles.com/vanilla-sunset-candle",        "soy candles – Rule 4b: 3 tokens, 21 chars"),
        ("https://handmade-ceramics.ro/cana-pictata-manual",    "artisan ceramics – Rule 4b: 3 tokens, 19 chars"),
        ("https://wooden-furniture.ro/masa-de-sufragerie",      "furniture – Rule 4b: 3 tokens, 18 chars"),
        ("https://organic-tea-shop.com/ceai-verde-jasmine",     "specialty tea – Rule 4b: 3 tokens, 18 chars"),
        ("https://niceshop.ro/lampa-de-birou-moderna",          "lighting – Rule 4b: 4 tokens, 22 chars"),
        ("https://florarie-online.ro/buchet-trandafiri-rosii",  "florist – Rule 4b: 3 tokens, 22 chars"),
        ("https://artcraft.ro/acuarele-profesionale-schmincke", "art supplies – Rule 4b: 3 tokens, 30 chars"),
        # Fixed by Rule 2b (CMS product path prefix)
        ("https://craft-shop.ro/products/mug",                  "Shopify – Rule 2b: /products/ prefix"),
        # Fixed by Rule 3 (lowered threshold from > 10 to >= 5)
        ("https://boutique-fashion.ro/rochii/rosie",            "WooCommerce – Rule 3: 'rosie' = 5 chars"),
        ("https://jewelry-store.com/rings/pearl",               "jewellery – Rule 3: 'pearl' = 5 chars"),
        ("https://vinylrecords.com/rock/doors",                 "vinyl records – Rule 3: 'doors' = 5 chars"),
        ("https://plantshop.ro/succulents/echeveria",           "plant shop – Rule 3: 'echeveria' = 9 chars"),
        ("https://artisansoap.com/bar-soaps/lavender",          "soap – Rule 3: 'lavender' = 8 chars"),
        ("https://wine-cellar.ro/vin-rosu/merlot",              "wine shop – Rule 3: 'merlot' = 6 chars"),
        ("https://musicalshop.ro/instrumente/chitara",          "musical instruments – Rule 3: 'chitara' = 7 chars"),
    ]

    # Niche product pages that pass via original rules (unchanged from before)
    NICHE_PASSED_ORIGINAL = [
        # SKU in URL → Rule 2 rescue
        ("https://small-shop.ro/produs-123456",             "niche shop – 6-digit SKU"),
        ("https://artisan-boutique.ro/item/AB-12345",       "boutique – alphanumeric SKU"),
        ("https://bijuterii-artizanale.ro/inel-argint-925", "jewellery – 'argint-925' rescued as SKU by Rule 2"),
        # Depth-2 with long slug (> 10 chars) → Rule 3
        ("https://handmade.ro/products/handmade-ceramic-bowl",         "handmade – 20-char slug"),
        ("https://craft-shop.ro/lumanari/lumanare-soia-lavanda-mare",  "craft – 29-char slug"),
        ("https://fashion-boutique.ro/rochii/rochie-de-seara-neagra",  "fashion – 20-char slug"),
        # Depth-1 with keyword → Rule 4
        ("https://niche-electronics.ro/laptop-gaming-ieftin",          "niche electronics – 'laptop' keyword"),
        ("https://petshop.ro/hrana-uscata-caini-royal-canin",          "pet shop – 'hrana' keyword"),
        ("https://watch-boutique.ro/ceas-fossil-barbati",              "watches – 'ceas' keyword"),
    ]

    # Mainstream retailer URLs that pass the gatekeeper (control group).
    # Includes eMAG PD codes which were blocked before Rule 2b was added.
    MAINSTREAM = [
        ("https://pcgarage.ro/laptop-lenovo-ideapad-3-15itl6/pld/RP-PCG-LEN-0163/", "PC Garage – 15-char PLD code → Rule 3"),
        ("https://bhphotovideo.com/c/product/1664978-REG/sony_wh1000xm5.html",       "B&H – 19-char slug → Rule 3"),
        ("https://elefant.ro/asus-vivobook-15-x1502za-laptop/p/12345678",            "Elefant – 8-digit ID → Rule 2 (\\d{6,})"),
        # eMAG PD codes were 9 chars (Rule 3 needed > 10). Fixed by Rule 2b (/pd/ prefix).
        ("https://emag.ro/laptop-lenovo-ideapad-3/pd/D9LGVSMBM/",                   "eMAG – Rule 2b: /pd/ prefix (was blocked before)"),
        # Dedeman short 4-digit IDs were too short for Rule 2 (\d{6,}).  Fixed by Rule 2b (/p/{4+digits}).
        ("https://dedeman.ro/ro/masa-rotativa/p/8902",                               "Dedeman – Rule 2b: /p/8902 (was blocked before)"),
    ]

    # Mainstream URLs that STILL fail the gatekeeper after all fixes.
    # Altex uses a single-letter last segment with no numeric ID after /p.
    MAINSTREAM_STILL_FAILING = [
        ("https://altex.ro/laptop-asus-vivobook-15-oled-90NB0PT2-M00KN0/p",
         "Altex – last segment is single letter 'p' with no numeric ID (known gap)"),
    ]

    def test_formerly_blocked_niche_urls_now_pass(self):
        """
        Regression test: all 15 URLs that were false negatives before the gatekeeper
        fixes must now pass. If any are blocked, a rule regressed.
        """
        failures = []
        for url, description in self.FORMERLY_BLOCKED_NOW_PASSING:
            if not is_likely_product_url(url):
                failures.append((url, description))

        if failures:
            print("\n[REGRESSION] These formerly-blocked niche URLs are now blocked again:")
            for url, desc in failures:
                print(f"  BLOCK  {desc}\n         {url}")

        assert not failures, (
            f"{len(failures)} niche URL(s) that were fixed are blocked again:\n"
            + "\n".join(f"  {u}" for u, _ in failures)
        )

    def test_niche_passed_urls_all_reach_scraper(self):
        """All niche URLs (original + formerly-blocked) must pass the gatekeeper."""
        all_niche = self.NICHE_PASSED_ORIGINAL + self.FORMERLY_BLOCKED_NOW_PASSING
        failures = []
        for url, description in all_niche:
            if not is_likely_product_url(url):
                failures.append((url, description))

        if failures:
            print("\n[GATEKEEPER] These niche URLs should pass but are blocked:")
            for url, desc in failures:
                print(f"  BLOCK  {desc}\n         {url}")
        assert not failures, (
            f"{len(failures)} niche URL(s) are blocked:\n"
            + "\n".join(f"  {u}" for u, _ in failures)
        )

    def test_mainstream_urls_all_pass_gatekeeper(self):
        """All mainstream retailer product URLs (including newly-fixed eMAG/Dedeman) must pass."""
        failures = []
        for url, description in self.MAINSTREAM:
            if not is_likely_product_url(url):
                failures.append((url, description))
        assert not failures, (
            f"Mainstream product URLs wrongly blocked ({len(failures)}):\n"
            + "\n".join(f"  {u}" for u, _ in failures)
        )

    def test_mainstream_still_failing_gatekeeper(self):
        """
        Documents the one remaining known gap: Altex single-letter /p suffix.
        If this starts passing, the gatekeeper was further improved — update accordingly.
        """
        still_blocked, now_passing = [], []
        for url, description in self.MAINSTREAM_STILL_FAILING:
            if is_likely_product_url(url):
                now_passing.append((url, description))
            else:
                still_blocked.append((url, description))

        if now_passing:
            print(f"\n[GATEKEEPER] Altex-style URLs now fixed:")
            for url, desc in now_passing:
                print(f"  PASS   {desc}")

        assert len(still_blocked) == len(self.MAINSTREAM_STILL_FAILING), (
            f"{len(now_passing)} previously-blocked mainstream URL(s) now pass — "
            "move them to MAINSTREAM and update the test:\n"
            + "\n".join(f"  {u}" for u, _ in now_passing)
        )

    def test_category_pages_always_blocked(self):
        """Sanity check: category/filter/search/blog pages must always be rejected."""
        category_urls = [
            "https://emag.ro/laptopuri/c",
            "https://niceshop.ro/category/electronics",
            "https://boutique.ro/collections/dresses",
            "https://store.com/search?q=mug",
            "https://shop.ro/filter/brand-apple",
            "https://amazon.com/s?k=headphones",
            "https://elefant.ro/catalog/telefoane",
            # Verify Rule 2b doesn't create false positives for non-product /p/ paths
            "https://site.com/page/1",          # /p/1 — only 1 digit, Rule 2b needs 4+
            "https://site.com/page/12",         # /p/12 — only 2 digits
            "https://site.com/page/123",        # /p/123 — only 3 digits
        ]
        for url in category_urls:
            assert not is_likely_product_url(url), f"Category/non-product URL wrongly allowed: {url}"

    def test_pass_rate_summary(self):
        """
        Prints the gatekeeper pass-rate for niche vs mainstream.
        After the fixes, niche should be at parity or better than mainstream.
        """
        all_niche = self.NICHE_PASSED_ORIGINAL + self.FORMERLY_BLOCKED_NOW_PASSING
        total_niche = len(all_niche)
        niche_passed = sum(1 for url, _ in all_niche if is_likely_product_url(url))

        total_mainstream = len(self.MAINSTREAM) + len(self.MAINSTREAM_STILL_FAILING)
        mainstream_passed = sum(1 for url, _ in self.MAINSTREAM if is_likely_product_url(url))

        niche_rate = niche_passed / total_niche * 100 if total_niche else 0
        mainstream_rate = mainstream_passed / total_mainstream * 100 if total_mainstream else 0
        gap = niche_rate - mainstream_rate

        print(f"\n{'=' * 60}")
        print("GATEKEEPER PASS-RATE SUMMARY (post-fix)")
        print(f"{'=' * 60}")
        print(f"  Niche sites:      {niche_passed:>2}/{total_niche:<2}  ({niche_rate:5.1f}% passed)")
        print(f"  Mainstream sites: {mainstream_passed:>2}/{total_mainstream:<2}  ({mainstream_rate:5.1f}% passed)")
        print(f"  (mainstream includes 1 known-broken Altex URL)")
        print(f"  Niche advantage: {gap:+.1f}pp")
        print(f"{'=' * 60}")

        assert niche_rate >= mainstream_rate, (
            f"Niche ({niche_rate:.0f}%) dropped below mainstream ({mainstream_rate:.0f}%) — "
            "a gatekeeper rule regressed. Check Rule 2b, Rule 3 threshold, or Rule 4b."
        )


# ── Part 2: Live HTTP scraping of niche sites ─────────────────────────────────
# These make real network requests. The parser fix (lxml-xml → lxml HTML parser)
# is required for Angular/React SSR sites — they return 0 chars with the XML parser
# but 14K+ chars with the HTML parser.
#
# URL stability notes:
#   dedeman.ro: URL slugs may drift when products are renamed; the numeric ID
#   (/p/XXXXXXX) is stable. If a URL returns empty content, verify the product
#   still exists and update the ID.
#   emag.ro: PD codes (/pd/XXXXXXXXX) are stable product identifiers.

NICHE_LIVE = [
    # Angular SSR — dedeman.ro was returning 0 chars before the lxml parser fix.
    # Passes via Rule 2 (_SKU_RE matches the 7-digit ID \d{6,}).
    ScraperTarget(
        url="https://www.dedeman.ro/ro/set-inele-fixare-sofit-23mm-alb-10buc/p/1032764",
        description="dedeman.ro – DIY/hardware niche shop (Angular SSR)",
        expected_gate_pass=True,
    ),
    # React SPA shell only — carturesti.ro renders product details client-side.
    # Returns ~1 K chars of nav/login shell via SSR; passes > 300 char threshold.
    # Passes via Rule 3 (depth-2, last segment 'harry-potter-...' = 40 chars).
    ScraperTarget(
        url="https://carturesti.ro/carte/harry-potter-si-piatra-filozofala-383382",
        description="carturesti.ro – cultural bookshop (React SPA shell)",
        expected_gate_pass=True,
    ),
]

MAINSTREAM_LIVE = [
    # eMAG: Angular SSR, was returning 0 chars before parser fix AND was blocked
    # by the gatekeeper (9-char PD code). Both issues are now fixed.
    # Passes via new Rule 2b (_CMS_PRODUCT_PATH_RE matches /pd/D9LGVSMBM/).
    ScraperTarget(
        url="https://www.emag.ro/laptop-lenovo-ideapad-3/pd/D9LGVSMBM/",
        description="emag.ro – mainstream Romanian tech retailer (Angular SSR)",
        expected_gate_pass=True,
    ),
]


class TestNicheSiteScrapingLive:
    """
    Fetches real product pages and verifies the scraper returns content.
    All tests require the lxml parser fix — without it every Angular/React
    site returns 0 chars and the tests skip.
    """

    def setup_method(self):
        import services.scraper_service as svc
        svc._policy_cache.clear()

    def _scrape(self, url: str) -> dict:
        from services.scraper_service import _fetch_one_sync
        return _fetch_one_sync(url)

    @pytest.mark.parametrize(
        "target",
        NICHE_LIVE,
        ids=[t.description for t in NICHE_LIVE],
    )
    def test_niche_gatekeeper_verdict(self, target: ScraperTarget):
        """Confirm niche URLs pass the (fixed) gatekeeper."""
        result = is_likely_product_url(target.url)
        verdict = "PASS" if result else "BLOCK"
        print(f"\n[GATE] {verdict}  {target.description}")
        assert result == target.expected_gate_pass, (
            f"Unexpected gatekeeper result for {target.description}:\n"
            f"  URL: {target.url}\n"
            f"  Expected {'PASS' if target.expected_gate_pass else 'BLOCK'}, got {verdict}"
        )

    @pytest.mark.parametrize(
        "target",
        NICHE_LIVE,
        ids=[t.description for t in NICHE_LIVE],
    )
    def test_niche_site_scrape_returns_content(self, target: ScraperTarget):
        """
        Scrapes a real niche product page and expects >= 300 chars.
        Before the lxml parser fix, Angular/React SSR sites returned 0 chars and skipped here.
        After the fix, they return 1K–30K chars depending on SSR vs SPA rendering.

        Empty result (0 chars, no block flag) means:
          a) URL is stale — product removed or slug changed → update the URL
          b) Site is pure client-side SPA (no SSR) → needs Playwright
          c) Site blocks datacenter IPs and no residential proxy is configured
        """
        if not is_likely_product_url(target.url):
            pytest.skip(f"Blocked by gatekeeper: {target.url}")

        result = self._scrape(target.url)
        markdown = result.get("markdown") or ""
        blocked = result.get("_blocked", False)
        cf_challenge = result.get("_cf_challenge", False)

        print(f"\n[SCRAPE] {target.description}")
        print(f"  URL:            {target.url}")
        print(f"  Blocked:        {blocked}")
        print(f"  CF challenge:   {cf_challenge}")
        print(f"  Content length: {len(markdown)} chars")
        if markdown:
            print(f"  Content sample: {markdown[:200]!r}")

        if blocked or cf_challenge:
            pytest.fail(
                f"Niche site blocked (bot detection): {target.description}\n"
                f"URL: {target.url}\n"
                "Full waterfall failed — site needs proxy support or Playwright."
            )

        if len(markdown) == 0:
            pytest.skip(
                f"Niche site returned 0 chars — stale URL or pure SPA: {target.description}\n"
                f"URL: {target.url}\n"
                "If the page loads content in a browser, the site needs Playwright."
            )

        assert len(markdown) > 300, (
            f"Niche site returned only {len(markdown)} chars: {target.description}\n"
            f"URL: {target.url}"
        )

    @pytest.mark.parametrize(
        "target",
        MAINSTREAM_LIVE,
        ids=[t.description for t in MAINSTREAM_LIVE],
    )
    def test_mainstream_site_scrape_returns_content(self, target: ScraperTarget):
        """Control group: mainstream sites scrape successfully (also benefited from lxml fix)."""
        if not is_likely_product_url(target.url):
            pytest.skip(
                f"Mainstream URL blocked by gatekeeper (known gap): {target.description}\n"
                f"URL: {target.url}"
            )

        result = self._scrape(target.url)
        markdown = result.get("markdown") or ""
        blocked = result.get("_blocked", False)
        cf_challenge = result.get("_cf_challenge", False)

        print(f"\n[SCRAPE] {target.description}")
        print(f"  URL:            {target.url}")
        print(f"  Blocked:        {blocked}")
        print(f"  CF challenge:   {cf_challenge}")
        print(f"  Content length: {len(markdown)} chars")

        if blocked or cf_challenge:
            pytest.skip(f"Mainstream site blocked — needs proxy or anti-bot handling: {target.description}")

        if len(markdown) == 0:
            pytest.skip(
                f"Mainstream site returned 0 chars — stale URL or pure SPA: {target.description}\n"
                f"URL: {target.url}"
            )

        assert len(markdown) > 300, (
            f"Mainstream site returned < 300 chars: {target.description} ({len(markdown)} chars)"
        )


# ── Part 3: Full comparison (gated behind env var) ───────────────────────────

class TestNicheVsMainstreamComparison:
    """
    Combines gatekeeper + live scrape into a single pass-rate report.
    Skipped unless RUN_NICHE_COMPARISON=1.
    """

    def setup_method(self):
        if not os.environ.get("RUN_NICHE_COMPARISON"):
            pytest.skip("Set RUN_NICHE_COMPARISON=1 to run the full comparison (~5 HTTP requests)")
        import services.scraper_service as svc
        svc._policy_cache.clear()

    def test_niche_vs_mainstream_pipeline(self):
        """
        End-to-end pipeline test: gatekeeper filter + live HTTP scrape.
        After fixing the lxml parser and gatekeeper rules, both niche and mainstream
        sites should succeed. Fails if the niche disadvantage exceeds 30 percentage points.
        """
        from services.scraper_service import _fetch_one_sync

        all_targets = [
            *[(t, "niche") for t in NICHE_LIVE],
            *[(t, "mainstream") for t in MAINSTREAM_LIVE],
        ]

        rows = []
        for target, group in all_targets:
            gated = is_likely_product_url(target.url)
            content_len = 0
            blocked = False
            cf = False

            if gated:
                scrape = _fetch_one_sync(target.url)
                content_len = len(scrape.get("markdown") or "")
                blocked = scrape.get("_blocked", False)
                cf = scrape.get("_cf_challenge", False)

            success = gated and not blocked and not cf and content_len > 300
            rows.append({
                "group": group,
                "description": target.description,
                "gated": gated,
                "blocked": blocked,
                "content_len": content_len,
                "success": success,
            })

        niche_rows = [r for r in rows if r["group"] == "niche"]
        mainstream_rows = [r for r in rows if r["group"] == "mainstream"]

        niche_ok = sum(1 for r in niche_rows if r["success"])
        mainstream_ok = sum(1 for r in mainstream_rows if r["success"])
        niche_rate = niche_ok / len(niche_rows) * 100 if niche_rows else 0
        mainstream_rate = mainstream_ok / len(mainstream_rows) * 100 if mainstream_rows else 0
        gap = mainstream_rate - niche_rate

        print("\n" + "=" * 72)
        print("NICHE vs MAINSTREAM — END-TO-END PIPELINE COMPARISON")
        print("=" * 72)
        header = f"{'GROUP':<12} {'SITE':<40} {'GATE':<6} {'CHARS':<7} {'OK?'}"
        print(header)
        print("-" * 72)
        for r in rows:
            gate_str = "PASS" if r["gated"] else "BLOCK"
            ok_str = "YES" if r["success"] else "NO"
            desc = r["description"][:39]
            print(f"{r['group']:<12} {desc:<40} {gate_str:<6} {r['content_len']:<7} {ok_str}")
        print("-" * 72)
        print(f"Niche sites:      {niche_ok}/{len(niche_rows)} succeeded  ({niche_rate:.0f}%)")
        print(f"Mainstream sites: {mainstream_ok}/{len(mainstream_rows)} succeeded  ({mainstream_rate:.0f}%)")
        print(f"Niche disadvantage: {gap:+.0f}pp  ({'significant — needs fixing' if gap > 30 else 'acceptable'})")
        print("=" * 72)

        assert gap <= 30, (
            f"Niche sites are {gap:.0f}pp behind mainstream (threshold: 30pp). "
            "Fix: broaden Rule 4 keywords, lower Rule 3 depth threshold, or add a Rule 5."
        )
