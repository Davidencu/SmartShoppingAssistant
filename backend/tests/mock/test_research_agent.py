"""
Unit and integration tests for the research-agent features added in the latest sprint:

  • _compress_markdown — signal-line extractor
  • _pick_contenders   — excluded_keywords + price_floor filters
  • score normalization — 0-1 → 0-100 conversion in score_and_rank_products
  • Tavily global e-commerce whitelist
  • research_community_picks — Gemini Google-Search-grounded research agent
  • SSE pipeline integration — research phase streamed, query boosted, picks forwarded

Run with:  pytest tests/mock/test_research_agent.py -v
All external API calls (Gemini, Tavily, Supabase, scraper) are mocked.
"""
import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# ── shared helpers (from conftest) ────────────────────────────────────────────
# sse_result / sse_statuses are module-level functions defined in conftest.py
from tests.conftest import sse_result, sse_statuses

CHAT_URL = "/search/chat"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _compress_markdown — pure function, zero mocking required
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompressMarkdown:
    def _compress(self, md, max_chars=600):
        from services.gemini_service import _compress_markdown
        return _compress_markdown(md, max_chars)

    def test_keeps_lines_with_numeric_content(self):
        md = "Price: 1799 RON\nSome navigation menu\n4.7/5 stars"
        out = self._compress(md)
        assert "1799" in out
        assert "4.7" in out

    def test_keeps_lines_with_signal_keywords(self):
        md = "Add to cart\nCookie policy blah blah blah\nFree shipping on orders"
        out = self._compress(md)
        assert "Add to cart" in out
        assert "Free shipping on orders" in out
        assert "Cookie policy" not in out

    def test_drops_empty_lines(self):
        md = "16GB RAM\n\n\nIn stock"
        out = self._compress(md)
        assert "\n\n" not in out

    def test_drops_lines_over_160_chars(self):
        long_line = "A" * 161 + " price 200"
        short_line = "Price: 200 RON"
        md = f"{long_line}\n{short_line}"
        out = self._compress(md)
        assert "A" * 161 not in out
        assert short_line in out

    def test_respects_max_chars(self):
        md = "\n".join(f"Price: {i} RON" for i in range(100))
        out = self._compress(md, max_chars=50)
        assert len(out) <= 50

    def test_empty_input_returns_empty_string(self):
        assert self._compress("") == ""

    def test_all_prose_returns_empty_string(self):
        md = "Welcome to our store\nExplore our collection\nCookies improve your experience"
        out = self._compress(md)
        assert out == ""


# ═══════════════════════════════════════════════════════════════════════════════
# 2. _pick_contenders — excluded_keywords + price_floor
# ═══════════════════════════════════════════════════════════════════════════════

def _make_scraped(url, markdown, price=None, availability=None):
    """Build a minimal scraped-result dict as returned by scraper_service."""
    jsonld = {}
    if price is not None:
        jsonld["price"] = price
    if availability is not None:
        jsonld["availability"] = availability
    return {"url": url, "markdown": markdown, "jsonld": jsonld, "title": url}


_GOOD_MD = (
    "16GB RAM laptop. Price: 1799 RON. In stock. "
    "Add to cart button. Rating: 4.5/5 stars from 320 reviews. "
    "Free shipping. Fast delivery in 2 days. "
) * 5  # ensure > 200 chars


class TestPickContenders:
    def _pick(self, scraped, budget=None, excluded_keywords=None, price_floor=None):
        from routers.search import _pick_contenders
        return _pick_contenders(scraped, budget, excluded_keywords=excluded_keywords, price_floor=price_floor)

    def test_drops_page_whose_title_contains_excluded_keyword(self):
        pages = [
            _make_scraped("https://shop.com/product/1", _GOOD_MD),
            _make_scraped("https://shop.com/bag-case", _GOOD_MD),
        ]
        pages[1]["title"] = "Laptop Bag Case for ASUS"
        result = self._pick(pages, excluded_keywords=["bag", "case"])
        urls = [p["url"] for p in result]
        assert "https://shop.com/product/1" in urls
        assert "https://shop.com/bag-case" not in urls

    def test_drops_page_whose_breadcrumb_contains_excluded_keyword(self):
        page = _make_scraped("https://shop.com/toy-bike", _GOOD_MD)
        page["jsonld"]["breadcrumb"] = "Sports > Toys > Bike accessories"
        result = self._pick([page], excluded_keywords=["toy", "accessories"])
        assert result == []

    def test_drops_page_below_price_floor(self):
        cheap = _make_scraped("https://shop.com/cheap", _GOOD_MD, price=50)
        good = _make_scraped("https://shop.com/good", _GOOD_MD, price=400)
        result = self._pick([cheap, good], price_floor=200)
        urls = [p["url"] for p in result]
        assert "https://shop.com/good" in urls
        assert "https://shop.com/cheap" not in urls

    def test_keeps_page_with_no_jsonld_price_when_floor_set(self):
        page = _make_scraped("https://shop.com/noprice", _GOOD_MD)  # no jsonld price key
        result = self._pick([page], price_floor=500)
        assert len(result) == 1

    def test_drops_out_of_stock_page(self):
        page = _make_scraped("https://shop.com/oos", _GOOD_MD, availability="OutOfStock")
        result = self._pick([page])
        assert result == []

    def test_no_filters_returns_all_valid_pages(self):
        pages = [
            _make_scraped(f"https://shop.com/p{i}", _GOOD_MD) for i in range(5)
        ]
        result = self._pick(pages)
        assert len(result) == 5

    def test_combined_keyword_and_floor_filters(self):
        pages = [
            _make_scraped("https://shop.com/a", _GOOD_MD, price=1500),  # passes both
            _make_scraped("https://shop.com/b", _GOOD_MD, price=50),    # fails floor
            _make_scraped("https://shop.com/c", _GOOD_MD, price=1200),  # passes both
        ]
        pages[1]["title"] = "Laptop Case"
        result = self._pick(pages, excluded_keywords=["case"], price_floor=500)
        urls = [p["url"] for p in result]
        assert "https://shop.com/a" in urls
        assert "https://shop.com/c" in urls
        assert "https://shop.com/b" not in urls


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Score normalization inside score_and_rank_products
# ═══════════════════════════════════════════════════════════════════════════════

def _mock_ranked_response(scores: dict, value_score: float = 0.0) -> str:
    return json.dumps({
        "ranked_products": [{
            "rank": 1,
            "title": "Test Product",
            "url": "https://amazon.com/test-product-p123",
            "price": 299.0,
            "currency": "USD",
            "image_url": None,
            "scores": scores,
            "value_score": value_score,
            "reasoning": "Good value.",
        }]
    })


class TestScoreNormalization:
    def _call_scorer(self, raw_scores, value_score=0.0):
        scraped = [{
            "url": "https://amazon.com/test-product-p123",
            "markdown": _GOOD_MD,
            "jsonld": {"price": 299.0},
            "title": "Test Product",
            "shipping_policy_url": "",
            "return_policy_text": "",
        }]
        from services.gemini_service import score_and_rank_products
        with patch("services.gemini_service._client") as mock_client:
            resp = MagicMock()
            resp.text = _mock_ranked_response(raw_scores, value_score)
            mock_client.models.generate_content.return_value = resp
            return score_and_rank_products(
                scraped, "test product", 500.0, "USD", is_global=True
            )

    def test_0_to_1_scale_multiplied_by_100(self):
        ranked = self._call_scorer(
            {"cost_efficiency": 0.85, "quality_confidence": 0.90, "logistics": 0.70, "trust": 0.80}
        )
        assert len(ranked) == 1
        s = ranked[0]["scores"]
        assert s["cost_efficiency"] == pytest.approx(85.0, abs=1)
        assert s["quality_confidence"] == pytest.approx(90.0, abs=1)

    def test_already_0_to_100_scale_unchanged(self):
        ranked = self._call_scorer(
            {"cost_efficiency": 85, "quality_confidence": 90, "logistics": 70, "trust": 80}
        )
        assert len(ranked) == 1
        s = ranked[0]["scores"]
        assert s["cost_efficiency"] == pytest.approx(85.0, abs=1)

    def test_mixed_scale_fractional_values_rescaled(self):
        # logistics is 0-1 but others are 0-100 → only the fractional one rescales
        ranked = self._call_scorer(
            {"cost_efficiency": 85, "quality_confidence": 90, "logistics": 0.7, "trust": 80}
        )
        assert len(ranked) == 1
        s = ranked[0]["scores"]
        assert s["logistics"] == pytest.approx(70.0, abs=1)
        assert s["cost_efficiency"] == pytest.approx(85.0, abs=1)

    def test_value_score_always_recomputed_from_weights(self):
        # LLM returns wrong value_score (0.855) — must be ignored and recomputed
        ranked = self._call_scorer(
            {"cost_efficiency": 80, "quality_confidence": 70, "logistics": 60, "trust": 50},
            value_score=0.855,  # wrong — will be overwritten
        )
        expected = 80 * 0.40 + 70 * 0.35 + 60 * 0.15 + 50 * 0.10
        assert len(ranked) == 1
        assert ranked[0]["value_score"] == pytest.approx(expected, abs=0.5)

    def test_scores_clamped_to_0_100(self):
        ranked = self._call_scorer(
            {"cost_efficiency": 120, "quality_confidence": -5, "logistics": 70, "trust": 80}
        )
        assert len(ranked) == 1
        s = ranked[0]["scores"]
        assert s["cost_efficiency"] == 100.0
        assert s["quality_confidence"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Tavily global e-commerce whitelist
# ═══════════════════════════════════════════════════════════════════════════════

class TestTavilyGlobalFilter:
    def test_uses_global_whitelist_when_no_domains_given(self):
        from services.tavily_service import _GLOBAL_ECOMMERCE_DOMAINS
        with patch("services.tavily_service._client") as mock_client:
            mock_client.search.return_value = {"results": []}
            from services.tavily_service import search_products
            search_products("laptop buy", max_results=5, include_domains=None)
            call_kwargs = mock_client.search.call_args.kwargs
            passed_domains = call_kwargs.get("include_domains") or []
            assert len(passed_domains) > 0, "Should use global whitelist, not empty list"
            assert all(d in _GLOBAL_ECOMMERCE_DOMAINS for d in passed_domains)

    def test_uses_provided_domains_when_explicitly_given(self):
        local = ["emag.ro", "altex.ro"]
        with patch("services.tavily_service._client") as mock_client:
            mock_client.search.return_value = {"results": []}
            from services.tavily_service import search_products
            search_products("laptop buy", max_results=5, include_domains=local)
            call_kwargs = mock_client.search.call_args.kwargs
            assert call_kwargs["include_domains"] == local

    def test_global_whitelist_excludes_reddit_and_wikipedia(self):
        from services.tavily_service import _GLOBAL_ECOMMERCE_DOMAINS
        assert "reddit.com" not in _GLOBAL_ECOMMERCE_DOMAINS
        assert "wikipedia.org" not in _GLOBAL_ECOMMERCE_DOMAINS
        assert "youtube.com" not in _GLOBAL_ECOMMERCE_DOMAINS

    def test_global_whitelist_covers_major_markets(self):
        from services.tavily_service import _GLOBAL_ECOMMERCE_DOMAINS
        domains = set(_GLOBAL_ECOMMERCE_DOMAINS)
        assert "amazon.com" in domains
        assert "amazon.de" in domains
        assert "emag.ro" in domains
        assert "allegro.pl" in domains
        assert "fnac.fr" in domains


# ═══════════════════════════════════════════════════════════════════════════════
# 5. research_community_picks — unit tests (Gemini client mocked)
# ═══════════════════════════════════════════════════════════════════════════════

class TestResearchCommunityPicksUnit:
    def _call(self, gemini_text: str):
        from services.gemini_service import research_community_picks
        with patch("services.gemini_service._client") as mock_client:
            resp = MagicMock()
            resp.text = gemini_text
            mock_client.models.generate_content.return_value = resp
            return research_community_picks(
                category="headphones",
                preference="noise cancelling",
                budget="1500 RON",
                user_language="English",
            )

    def test_parses_clean_json_response(self):
        result = self._call(json.dumps({
            "recommendations": ["Sony WH-1000XM5", "Bose QC45"],
            "insight": "Reddit recommends Sony WH-1000XM5 for best ANC.",
        }))
        assert result["recommendations"] == ["Sony WH-1000XM5", "Bose QC45"]
        assert "Sony" in result["insight"]

    def test_parses_json_embedded_in_explanation_text(self):
        # Google Search grounding embeds JSON inside prose
        mixed_text = (
            'Based on Reddit and forums, here are the top picks:\n'
            '{"recommendations": ["Sony WH-1000XM5"], '
            '"insight": "Most recommended ANC headphones."}\n'
            'These are widely praised in audiophile communities.'
        )
        result = self._call(mixed_text)
        assert result["recommendations"] == ["Sony WH-1000XM5"]
        assert result["insight"] is not None

    def test_returns_empty_when_recommendations_list_is_empty(self):
        result = self._call(json.dumps({
            "recommendations": [],
            "insight": None,
        }))
        assert result["recommendations"] == []
        assert result["insight"] is None

    def test_returns_empty_dict_on_gemini_api_error(self):
        from services.gemini_service import research_community_picks
        with patch("services.gemini_service._client") as mock_client:
            mock_client.models.generate_content.side_effect = Exception("API unavailable")
            result = research_community_picks("laptop", "gaming", "2000 RON")
        assert result["recommendations"] == []
        assert result["insight"] is None

    def test_returns_empty_when_response_is_plain_text_no_json(self):
        result = self._call("Sorry, I could not find community consensus for this product.")
        assert result["recommendations"] == []

    def test_google_search_tool_used_in_gemini_call(self):
        from google.genai import types
        from services.gemini_service import research_community_picks
        with patch("services.gemini_service._client") as mock_client:
            resp = MagicMock()
            resp.text = json.dumps({
                "recommendations": ["Test Model"],
                "insight": "Popular.",
            })
            mock_client.models.generate_content.return_value = resp
            research_community_picks("headphones", None, None)
            call_kwargs = mock_client.models.generate_content.call_args.kwargs
            config = call_kwargs.get("config")
            assert config is not None
            # Verify the Google Search tool was included
            tools = getattr(config, "tools", None) or []
            assert any(
                hasattr(t, "google_search") for t in tools
            ), "Gemini call must include google_search tool for web grounding"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Adaptive requirement gate — system prompt content
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdaptiveRequirementGate:
    def test_system_prompt_contains_gate_section(self):
        from services.gemini_service import _SYSTEM_PROMPT
        assert "Adaptive Requirement Gate" in _SYSTEM_PROMPT
        assert "HIGH-COMPLEXITY CATEGORIES" in _SYSTEM_PROMPT
        assert "LOW-COMPLEXITY CATEGORIES" in _SYSTEM_PROMPT

    def test_high_complexity_list_covers_key_categories(self):
        from services.gemini_service import _SYSTEM_PROMPT
        for kw in ("laptop", "smartphone", "camera", "washing machine", "tv"):
            assert kw in _SYSTEM_PROMPT.lower(), f"Gate should mention '{kw}'"

    def test_gate_allows_use_case_in_category_name(self):
        from services.gemini_service import _SYSTEM_PROMPT
        assert "gaming" in _SYSTEM_PROMPT.lower()
        assert "photography" in _SYSTEM_PROMPT.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 7. SSE pipeline integration — research phase wired end-to-end
# ═══════════════════════════════════════════════════════════════════════════════

_SEARCH_INTENT = {
    "intent": "SEARCH",
    "reply": None,
    "language_code": "en",
    "collected_params": {
        "category": "Headphones",
        "budget": "1500 RON",
        "budget_max": 1500.0,
        "budget_currency": "RON",
        "preference": "noise cancelling",
    },
    "localized_search_query": "casti noise cancelling",
    "local_domains": ["emag.ro", "altex.ro"],
    "search_globally": False,
    "is_refinement": False,
    "excluded_keywords": [],
    "price_floor": None,
}

_RESEARCH_RESULT = {
    "recommendations": ["Sony WH-1000XM5", "Bose QC45"],
    "insight": "Reddit consistently recommends the Sony WH-1000XM5 for best noise cancellation.",
}

_TAVILY_URLS = [
    {"url": "https://emag.ro/sony-wh1000xm5/pd/DX1234MB/", "title": "Sony WH-1000XM5"},
    {"url": "https://altex.ro/bose-qc45/pd/BQ45001/", "title": "Bose QC45"},
]

_SCRAPED = [
    {
        "url": "https://emag.ro/sony-wh1000xm5/pd/DX1234MB/",
        "markdown": (
            "Sony WH-1000XM5 noise cancelling headphones. Price: 1299 RON. "
            "In stock. Add to cart. Rating: 4.8/5 from 1200 reviews. "
            "Bluetooth 5.2, 30h battery, USB-C charging. Free shipping. "
        ) * 6,
        "jsonld": {"price": 1299.0, "name": "Sony WH-1000XM5"},
        "title": "Sony WH-1000XM5",
        "shipping_policy_url": "",
        "return_policy_text": "",
    },
    {
        "url": "https://altex.ro/bose-qc45/pd/BQ45001/",
        "markdown": (
            "Bose QuietComfort 45 headphones. Price: 1399 RON. "
            "In stock. Cumpara acum. Rating: 4.6/5 from 860 reviews. "
            "Bluetooth 5.1, 24h battery, active noise cancellation. Free delivery. "
        ) * 6,
        "jsonld": {"price": 1399.0, "name": "Bose QC45"},
        "title": "Bose QC45",
        "shipping_policy_url": "",
        "return_policy_text": "",
    },
]

_RANKED_PRODUCTS = [
    {
        "rank": 1, "title": "Sony WH-1000XM5",
        "url": "https://emag.ro/sony-wh1000xm5/pd/DX1234MB/",
        "price": 1299.0, "currency": "RON", "image_url": None,
        "scores": {"cost_efficiency": 88, "quality_confidence": 92, "logistics": 85, "trust": 90},
        "value_score": 90.0,
        "reasoning": "Community favourite with top ANC at a great price.",
    },
]


def _mock_full_pipeline(mocker, mock_supabase, research_result=None, raises_research=False):
    """Patch all external calls for a SEARCH that hits the research phase."""
    mocker.patch("services.gemini_service.classify_intent", return_value=_SEARCH_INTENT)
    mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
    mocker.patch("services.cache_service.lookup_cache", return_value=None)  # cache miss

    if raises_research:
        mocker.patch(
            "services.gemini_service.research_community_picks",
            side_effect=RuntimeError("research failed"),
        )
    else:
        mocker.patch(
            "services.gemini_service.research_community_picks",
            return_value=research_result or _RESEARCH_RESULT,
        )

    mocker.patch("services.tavily_service.search_products", return_value=_TAVILY_URLS)
    mocker.patch(
        "services.scraper_service.scrape_urls",
        new=AsyncMock(return_value=_SCRAPED),
    )
    mocker.patch(
        "services.gemini_service.score_and_rank_products",
        return_value=_RANKED_PRODUCTS,
    )
    mocker.patch("services.cache_service.save_cache")


class TestResearchPipelineIntegration:
    def test_researching_status_appears_before_search(
        self, client, mock_supabase, auth_token, mocker
    ):
        """'Researching community recommendations…' must appear before 'Searching for products…'."""
        _mock_full_pipeline(mocker, mock_supabase)
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "noise cancelling headphones under 1500 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        statuses = sse_statuses(resp)

        # The research status contains "community" — distinct from "searching for products".
        # We must NOT match "researching" when looking for the search status because
        # "searching" is a substring of "researching".
        researching_idx = next(
            (i for i, s in enumerate(statuses) if "community" in s.lower()), None
        )
        # "Searching for products" starts with "Search" but NOT "Research"
        search_idx = next(
            (i for i, s in enumerate(statuses)
             if s.lower().startswith("search") and "community" not in s.lower()), None
        )
        assert researching_idx is not None, f"No researching status found. Statuses: {statuses}"
        if search_idx is not None:
            assert researching_idx < search_idx, (
                f"Research (idx {researching_idx}) must precede search status (idx {search_idx}). "
                f"Full statuses: {statuses}"
            )

    def test_research_insight_streamed_to_frontend(
        self, client, mock_supabase, auth_token, mocker
    ):
        """The insight sentence returned by research_community_picks must appear in SSE."""
        _mock_full_pipeline(mocker, mock_supabase)
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "noise cancelling headphones under 1500 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        statuses = sse_statuses(resp)
        insight = _RESEARCH_RESULT["insight"]
        assert any(insight in s for s in statuses), (
            f"Insight not found in SSE statuses.\nExpected: {insight}\nGot: {statuses}"
        )

    def test_community_picks_do_not_contaminate_tavily_query(
        self, client, mock_supabase, auth_token, mocker
    ):
        """Community model names must NOT be injected into the Tavily search query.
        Picks are scoring hints only — injecting them would constrain Tavily to those
        exact (often out-of-budget) products and return zero results."""
        _mock_full_pipeline(mocker, mock_supabase)
        mock_tavily = mocker.patch(
            "services.tavily_service.search_products", return_value=_TAVILY_URLS
        )
        client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "noise cancelling headphones under 1500 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        calls = mock_tavily.call_args_list
        assert calls, "Tavily was not called"
        first_query = calls[0].args[0]
        # Model names from community picks must NOT appear in the search query
        assert "Sony WH-1000XM5" not in first_query and "Bose QC45" not in first_query, (
            f"Community model names were injected into Tavily query (must not be). Got: {first_query!r}"
        )

    def test_community_picks_forwarded_to_scorer(
        self, client, mock_supabase, auth_token, mocker
    ):
        """score_and_rank_products must receive community_picks from the research result."""
        _mock_full_pipeline(mocker, mock_supabase)
        mock_scorer = mocker.patch(
            "services.gemini_service.score_and_rank_products",
            return_value=_RANKED_PRODUCTS,
        )
        client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "noise cancelling headphones under 1500 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert mock_scorer.called, "Scorer was not called"
        # community_picks is the 9th positional arg (index 8)
        picks_arg = mock_scorer.call_args.args[8]
        assert "Sony WH-1000XM5" in picks_arg, (
            f"community_picks not forwarded to scorer. Got 9th arg: {picks_arg!r}"
        )

    def test_research_failure_does_not_break_pipeline(
        self, client, mock_supabase, auth_token, mocker
    ):
        """If research_community_picks raises, the pipeline must complete normally."""
        _mock_full_pipeline(mocker, mock_supabase, raises_research=True)
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "noise cancelling headphones under 1500 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "SEARCH"
        assert len(data["products"]) == 1

    def test_research_empty_picks_does_not_boost_query(
        self, client, mock_supabase, auth_token, mocker
    ):
        """When research returns no picks, the base query must be used unchanged."""
        empty_research = {"recommendations": [], "insight": None}
        _mock_full_pipeline(mocker, mock_supabase, research_result=empty_research)
        mock_tavily = mocker.patch(
            "services.tavily_service.search_products", return_value=_TAVILY_URLS
        )
        client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "noise cancelling headphones under 1500 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        first_query = mock_tavily.call_args_list[0].args[0]
        # Base query ends with "buy", must NOT contain model names
        assert "Sony" not in first_query
        assert "Bose" not in first_query

    def test_cache_hit_skips_research_phase(
        self, client, mock_supabase, auth_token, mocker
    ):
        """Cache hits must return immediately — research_community_picks must not be called."""
        mocker.patch("services.gemini_service.classify_intent", return_value=_SEARCH_INTENT)
        mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
        mocker.patch("services.cache_service.lookup_cache", return_value=_RANKED_PRODUCTS)
        mock_research = mocker.patch("services.gemini_service.research_community_picks")
        mock_tavily = mocker.patch("services.tavily_service.search_products")

        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "noise cancelling headphones under 1500 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["from_cache"] is True
        mock_research.assert_not_called()
        mock_tavily.assert_not_called()

    def test_final_result_contains_products_with_scores(
        self, client, mock_supabase, auth_token, mocker
    ):
        """End-to-end: SSE result event must carry products with normalised scores."""
        _mock_full_pipeline(mocker, mock_supabase)
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "noise cancelling headphones under 1500 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "SEARCH"
        assert len(data["products"]) == 1
        p = data["products"][0]
        assert p["title"] == "Sony WH-1000XM5"
        assert p["value_score"] == 90.0
        assert all(k in p["scores"] for k in ("cost_efficiency", "quality_confidence", "logistics", "trust"))
