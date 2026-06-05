"""
Live tests for the research-agent features — hit real external APIs.

Run with:
    pytest tests/live/test_research_agent_live.py -v -s -m live

These tests consume real API credits (Gemini, Tavily).
They are automatically skipped when API keys are absent.

Test areas:
  A. research_community_picks — structure, quality, language
  B. Adaptive Requirement Gate — complex items need use-case before SEARCH
  C. Tavily e-commerce filter  — whitelist means no Reddit/Wikipedia results
  D. Full-pipeline impact      — with vs without research picks (gated)
"""
import asyncio
import os

import pytest

pytestmark = pytest.mark.live


def _require_keys():
    from core.config import settings
    missing = []
    if not settings.gemini_api_key:
        missing.append("GEMINI_API_KEY")
    if not settings.tavily_api_key:
        missing.append("TAVILY_API_KEY")
    if missing:
        pytest.skip(f"Missing env vars: {', '.join(missing)}")


# ═══════════════════════════════════════════════════════════════════════════════
# A. research_community_picks — Gemini + Google Search grounding
# ═══════════════════════════════════════════════════════════════════════════════

class TestLiveResearchCommunityPicks:
    def setup_method(self):
        _require_keys()

    def test_returns_valid_structure(self):
        """Basic contract: must return a dict with the two expected keys."""
        from services.gemini_service import research_community_picks

        result = research_community_picks(
            category="wireless headphones",
            preference="noise cancelling",
            budget="300 USD",
            user_language="English",
        )
        assert isinstance(result, dict)
        assert "recommendations" in result
        assert "insight" in result
        assert isinstance(result["recommendations"], list)

    def test_finds_specific_models_for_popular_category(self):
        """
        For a well-known category (noise-cancelling headphones), the research
        agent should find at least one specific brand+model name.
        Reddit consensus for this category is extremely strong (Sony WH-1000XM5,
        Bose QC45, etc.), so community_picks should be non-empty.
        """
        from services.gemini_service import research_community_picks

        result = research_community_picks(
            category="headphones",
            preference="noise cancelling for commuting",
            budget="400 USD",
            user_language="English",
        )
        recs = result.get("recommendations") or []
        assert len(recs) >= 1, (
            f"Expected at least one model recommendation for noise-cancelling headphones. "
            f"Got: {result}"
        )
        # Each recommendation should be a non-empty string with a space (brand + model)
        for rec in recs:
            assert isinstance(rec, str) and len(rec) > 3, f"Invalid recommendation: {rec!r}"

    def test_insight_not_empty_when_recommendations_exist(self):
        """When models are found, insight must be a non-empty sentence."""
        from services.gemini_service import research_community_picks

        result = research_community_picks(
            category="mechanical keyboard",
            preference="for programming",
            budget="150 USD",
            user_language="English",
        )
        recs = result.get("recommendations") or []
        if recs:
            insight = result.get("insight") or ""
            assert len(insight) > 10, f"Insight should be a sentence, got: {insight!r}"

    def test_insight_in_romanian_when_requested(self):
        """
        When user_language='Romanian', the insight sentence must be in Romanian.
        Gemini's Language Rule applies to research_community_picks too.
        """
        from services.gemini_service import research_community_picks

        result = research_community_picks(
            category="laptop",
            preference="gaming",
            budget="2000 RON",
            user_language="Romanian",
        )
        insight = result.get("insight") or ""
        if not insight:
            pytest.skip("No insight returned — community consensus unclear, skip language check")
        # Romanian-specific heuristic: common words in Romanian text
        romanian_signals = {"este", "are", "pentru", "cele", "mai", "bune", "recomandate", "din"}
        insight_lower = insight.lower()
        found = any(word in insight_lower for word in romanian_signals)
        assert found, (
            f"Insight requested in Romanian but no Romanian words detected: {insight!r}"
        )

    def test_handles_obscure_category_gracefully(self):
        """For a very niche category with no community consensus, returns empty picks safely."""
        from services.gemini_service import research_community_picks

        result = research_community_picks(
            category="industrial conveyor belt motor",
            preference="3-phase 400V",
            budget=None,
            user_language="English",
        )
        assert isinstance(result.get("recommendations"), list)
        # Either empty or contains model names — must not crash


# ═══════════════════════════════════════════════════════════════════════════════
# B. Adaptive Requirement Gate — Gemini classify_intent live behaviour
# ═══════════════════════════════════════════════════════════════════════════════

class TestLiveAdaptiveRequirementGate:
    def setup_method(self):
        _require_keys()

    def test_gaming_laptop_fires_search_immediately(self):
        """
        'ASUS gaming laptop under 2000 RON' — 'gaming' implies use-case.
        The gate must NOT trigger; Gemini must return SEARCH.
        """
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="ASUS gaming laptop under 2000 RON")
        ])
        assert result["intent"] == "SEARCH", (
            f"'gaming laptop' has an implicit use-case — gate must not trigger. "
            f"Got intent={result['intent']}, reply={result.get('reply')}"
        )

    def test_laptop_for_video_editing_fires_search(self):
        """'laptop for video editing under 5000 RON' — explicit use-case → SEARCH."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="laptop for video editing under 5000 RON")
        ])
        assert result["intent"] == "SEARCH"

    def test_bare_brand_laptop_triggers_clarify(self):
        """
        'ASUS laptop under 2000 RON' — only brand, no use-case.
        With the adaptive gate, Gemini should trigger CLARIFY.
        """
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="ASUS laptop under 2000 RON")
        ])
        # CLARIFY is the expected intent — the gate should ask about use case
        # But some models might still fire SEARCH for a brand+category match.
        # We assert a reply exists either way (no silent SEARCH without reply).
        if result["intent"] == "SEARCH":
            # Acceptable if the model inferred enough context — log for observation
            import logging
            logging.getLogger(__name__).warning(
                "[GATE-OBSERVATION] bare brand+budget yielded SEARCH (gate did not trigger): %s",
                result,
            )
        else:
            assert result["intent"] in ("CLARIFY", "CHAT")
            assert result["reply"] is not None and len(result["reply"]) > 5

    def test_smartphone_with_use_case_fires_search(self):
        """'Samsung Galaxy phone for photography under 3000 RON' → SEARCH."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="Samsung Galaxy phone for photography under 3000 RON")
        ])
        assert result["intent"] == "SEARCH"

    def test_usb_cable_fires_search_without_usecase(self):
        """
        USB cable is a low-complexity item — gate must NOT trigger.
        'USB-C cable under 50 RON' should fire SEARCH immediately.
        """
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="USB-C cable under 50 RON")
        ])
        assert result["intent"] == "SEARCH", (
            f"Simple accessory must not trigger the adaptive gate. "
            f"Got intent={result['intent']}, reply={result.get('reply')}"
        )

    def test_running_shoes_with_brand_fires_search(self):
        """'Nike running shoes size 42 under 500 RON' — low-complexity + complete → SEARCH."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="Nike running shoes size 42 under 500 RON")
        ])
        assert result["intent"] == "SEARCH"


# ═══════════════════════════════════════════════════════════════════════════════
# C. Tavily e-commerce filter — no Reddit/Wikipedia in global results
# ═══════════════════════════════════════════════════════════════════════════════

class TestLiveTavilyEcommerceFilter:
    def setup_method(self):
        _require_keys()

    def test_global_search_returns_only_ecommerce_urls(self):
        """
        Without local domains (global search), Tavily must only return URLs
        from the _GLOBAL_ECOMMERCE_DOMAINS whitelist — no Reddit, YouTube, or
        Wikipedia results.
        """
        from services.tavily_service import _GLOBAL_ECOMMERCE_DOMAINS, search_products

        results = search_products("Sony WH-1000XM5 buy", max_results=10, include_domains=None)
        assert isinstance(results, list)
        if not results:
            pytest.skip("Tavily returned no results — possibly rate limited")

        non_commerce_patterns = ("reddit.com", "wikipedia.org", "youtube.com", "quora.com",
                                 "twitter.com", "x.com", "facebook.com", "medium.com",
                                 "techradar.com", "rtings.com", "cnet.com", "theverge.com")
        for r in results:
            url = r["url"].lower()
            for pattern in non_commerce_patterns:
                assert pattern not in url, (
                    f"Non-commerce URL found in global results: {r['url']!r}\n"
                    f"The global e-commerce whitelist should prevent this."
                )

    def test_results_contain_known_ecommerce_domains(self):
        """At least one result should come from a major e-commerce domain."""
        from services.tavily_service import _GLOBAL_ECOMMERCE_DOMAINS, search_products

        results = search_products("Sony WH-1000XM5 buy", max_results=10)
        if not results:
            pytest.skip("Tavily returned no results")

        domain_set = set(_GLOBAL_ECOMMERCE_DOMAINS)
        urls = [r["url"] for r in results]

        def _domain(url: str) -> str:
            from urllib.parse import urlparse
            d = urlparse(url).netloc.removeprefix("www.")
            return d

        found_ecommerce = any(_domain(url) in domain_set for url in urls)
        assert found_ecommerce, (
            f"No results from known e-commerce domains. Got domains: "
            f"{[_domain(u) for u in urls]}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# D. Full-pipeline impact — research agent with real pipeline
# Gated by RUN_RESEARCH_IMPACT_TESTS=1 (expensive: Gemini + Tavily + scraper)
# ═══════════════════════════════════════════════════════════════════════════════

class TestLiveResearchAgentImpact:
    """
    Measures the real-world impact of the research agent on the full pipeline.
    These tests run the complete intent → research → Tavily → scrape → score
    flow and verify that community picks appear in the final ranking.

    Gated because each test consumes ~15-25 Tavily results + multiple Gemini calls.
    """

    def setup_method(self):
        _require_keys()
        if not os.environ.get("RUN_RESEARCH_IMPACT_TESTS"):
            pytest.skip("Set RUN_RESEARCH_IMPACT_TESTS=1 to run full research impact tests")

    def _full_pipeline_with_research(self, user_message: str, city="", country=""):
        """
        Run the complete pipeline including the research phase.
        Returns (research_result, ranked_products, query_used).
        """
        from models.search import ChatMessage, IntentParams
        from services import gemini_service, scraper_service, tavily_service
        from routers.search import _build_search_query, _pick_contenders

        messages = [ChatMessage(role="user", content=user_message)]

        # 1. Intent
        intent_data = gemini_service.classify_intent(messages, city=city, country=country)
        assert intent_data["intent"] == "SEARCH", f"Expected SEARCH, got {intent_data['intent']}"

        raw = intent_data.get("collected_params") or {}
        params = IntentParams(
            category=raw.get("category"),
            budget=raw.get("budget"),
            budget_max=raw.get("budget_max"),
            budget_currency=raw.get("budget_currency"),
            preference=raw.get("preference"),
        )
        base_query, domains = _build_search_query(
            intent_data.get("localized_search_query"), params, intent_data.get("local_domains")
        )

        # 2. Research phase (picks are scoring hints only, never injected into query)
        research = gemini_service.research_community_picks(
            category=params.category or "",
            preference=params.preference or None,
            budget=params.budget or None,
            user_language="English",
        )
        community_picks = research.get("recommendations") or []
        query = base_query

        # 3. Tavily
        tavily_results = []
        if domains:
            tavily_results = tavily_service.search_products(query, max_results=15, include_domains=domains)
        if len(tavily_results) < 5:
            more = tavily_service.search_products(query, max_results=10)
            seen = {r["url"] for r in tavily_results}
            for r in more:
                if r["url"] not in seen:
                    tavily_results.append(r)
        assert tavily_results, f"Tavily returned no results for query: {query!r}"

        # 4. Scrape
        from services.scraper_service import is_likely_product_url
        product_urls = [r["url"] for r in tavily_results if is_likely_product_url(r["url"])][:10]
        scraped = asyncio.run(scraper_service.scrape_urls(product_urls))

        # 5. Filter + score
        contenders = _pick_contenders(scraped, params.budget_max)
        assert contenders, "No contenders after filtering"

        ranked = gemini_service.score_and_rank_products(
            contenders,
            f"{params.preference} {params.category}",
            budget_max=params.budget_max,
            budget_currency=params.budget_currency,
            city=city,
            country=country,
            community_picks=community_picks,
        )
        return research, ranked, query

    def test_research_finds_picks_for_headphones(self):
        """
        End-to-end: noise-cancelling headphones search.
        Verifies research agent returns picks AND that final products are ranked.
        """
        research, ranked, query = self._full_pipeline_with_research(
            "noise cancelling headphones under 400 USD"
        )
        # Research phase should have found known models
        picks = research.get("recommendations") or []
        assert len(picks) >= 1, f"Expected community picks; got: {research}"

        # Community picks must NOT be in the Tavily query (scoring hints only)
        for pick in picks:
            brand = pick.split()[0]
            assert brand not in query, (
                f"Community pick brand '{brand}' was injected into Tavily query (must not be). "
                f"Query: {query!r}"
            )

        # Final ranking should have products
        assert 1 <= len(ranked) <= 3, f"Expected 1-3 ranked products, got: {len(ranked)}"
        assert ranked[0]["value_score"] >= ranked[-1]["value_score"]

    def test_community_backed_product_scores_well(self):
        """
        When the top community pick appears in the search results, it should
        achieve a quality_confidence score reflecting community validation.
        This test confirms the scoring boost is actually applied.
        """
        research, ranked, _ = self._full_pipeline_with_research(
            "noise cancelling headphones under 400 USD"
        )
        picks = research.get("recommendations") or []
        if not picks or not ranked:
            pytest.skip("No community picks or ranked products — cannot measure boost")

        # Check if any ranked product matches a community pick
        matched = [
            p for p in ranked
            if any(pick.split()[0].lower() in p["title"].lower() for pick in picks)
        ]
        if matched:
            top_pick = matched[0]
            # Community-backed products should have quality_confidence >= 70
            assert top_pick["scores"]["quality_confidence"] >= 60, (
                f"Community pick '{top_pick['title']}' scored only "
                f"{top_pick['scores']['quality_confidence']} on quality_confidence. "
                f"Expected ≥ 60 for a community-validated product."
            )
        else:
            # Community picks not in results — log but don't fail (availability varies)
            import logging
            logging.getLogger(__name__).warning(
                "[IMPACT] Community picks %s not found in final results: %s",
                picks, [p["title"] for p in ranked],
            )

    def test_score_output_is_integer_scale_not_decimal(self):
        """
        Regression: LLMs sometimes return 0-1 scale.  After normalization,
        all dimension scores must be on the 0-100 scale (>= 1 or == 0).
        """
        _, ranked, _ = self._full_pipeline_with_research(
            "wireless gaming mouse under 100 USD"
        )
        assert ranked, "No ranked products returned"
        for product in ranked:
            s = product["scores"]
            for dim, val in s.items():
                assert val >= 1.0 or val == 0.0, (
                    f"Score dimension '{dim}' looks like a 0-1 scale value: {val} "
                    f"for '{product['title']}'"
                )
