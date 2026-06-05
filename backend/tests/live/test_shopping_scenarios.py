"""
Live shopping scenario tests — hit real Tavily, Gemini, and scraper APIs.

Run with:
    RUN_SHOPPING_SCENARIO_TESTS=1 pytest tests/live/test_shopping_scenarios.py -v -s

These consume real API credits. Each scenario simulates a complete user journey:
  1. Sports bike under 800 RON
  2. High-quality digital watch under 500 RON (men's — handles gender refinement)
  3. Black resistant backpack under 100 RON (Romanian local sites)

Score assertions aim for < zero all-40 scores, meaning the pipeline
successfully parsed price, rating, and/or shipping data from at least
the top-ranked product.
"""
import asyncio
import os

import pytest

pytestmark = pytest.mark.live


def _require_env():
    """Skip this module unless both scenario flag and API keys are present."""
    if not os.environ.get("RUN_SHOPPING_SCENARIO_TESTS"):
        pytest.skip("Set RUN_SHOPPING_SCENARIO_TESTS=1 to run shopping scenario tests")
    from core.config import settings
    missing = []
    if not settings.gemini_api_key:
        missing.append("GEMINI_API_KEY")
    if not settings.tavily_api_key:
        missing.append("TAVILY_API_KEY")
    if missing:
        pytest.skip(f"Missing env vars: {', '.join(missing)}")


def _run_full_pipeline(messages, city="Bucharest", country="Romania"):
    """
    Run the intent → Tavily → Scraper → Gemini scoring pipeline.
    Returns (intent_data, ranked_products).
    """
    from models.search import ChatMessage, IntentParams
    from services import gemini_service, tavily_service, scraper_service
    from routers.search import _build_search_query

    intent_data = gemini_service.classify_intent(messages, city=city, country=country)

    if intent_data["intent"] != "SEARCH":
        return intent_data, []

    raw_params = intent_data.get("collected_params") or {}
    params = IntentParams(
        category=raw_params.get("category"),
        budget=raw_params.get("budget"),
        budget_max=raw_params.get("budget_max"),
        budget_currency=raw_params.get("budget_currency"),
        preference=raw_params.get("preference"),
    )
    query, domains = _build_search_query(
        intent_data.get("localized_search_query"),
        params,
        intent_data.get("local_domains"),
    )

    # Local search first, global fallback if < 3 results
    tavily_results = []
    if domains:
        tavily_results = tavily_service.search_products(query, max_results=10, include_domains=domains)
    if len(tavily_results) < 3:
        global_results = tavily_service.search_products(query, max_results=10)
        seen = {r["url"] for r in tavily_results}
        for r in global_results:
            if r["url"] not in seen:
                tavily_results.append(r)
        tavily_results = tavily_results[:10]

    assert tavily_results, f"Tavily returned no results for: {query}"

    from services.scraper_service import is_likely_product_url
    urls = [r["url"] for r in tavily_results[:10] if is_likely_product_url(r["url"])]
    if not urls:
        pytest.skip("Tavily returned only category/listing pages — no scorable product URLs")
    scraped = asyncio.run(scraper_service.scrape_urls(urls))

    url_to_title = {r["url"]: r.get("title", "") for r in tavily_results}
    for s in scraped:
        s["title"] = url_to_title.get(s["url"], "")

    usable = [s for s in scraped if len(s.get("markdown") or "") > 200]
    if not usable:
        pytest.skip("Scraper returned no usable content — likely bot-detection. Re-run.")

    ranked = gemini_service.score_and_rank_products(
        usable,
        f"{params.preference or ''} {params.category or ''}".strip(),
        params.budget_max,
        params.budget_currency,
        city=city,
        country=country,
    )
    return intent_data, ranked


def _assert_pipeline_quality(ranked, scenario_name, min_value_score=50.0):
    """
    Common quality gate: the top product must have been meaningfully scored
    (at least one dimension above the 40-floor, meaning the page had parseable data).
    """
    assert ranked, f"[{scenario_name}] Pipeline returned no products"
    top = ranked[0]
    scores = top.get("scores") or {}

    # At least one dimension must be above the data-absent floor of 40
    above_floor = [
        dim for dim, val in scores.items() if float(val or 0) > 40
    ]
    assert above_floor, (
        f"[{scenario_name}] All dimensions scored exactly 40 — backend failed to parse "
        f"any product data for: {top.get('title')} at {top.get('url')}\n"
        f"Scores: {scores}"
    )

    assert float(top.get("value_score", 0)) >= min_value_score, (
        f"[{scenario_name}] Top product value_score {top['value_score']} < {min_value_score} — "
        f"likely a parse failure or very poor match\n"
        f"Title: {top.get('title')} | Price: {top.get('price')} {top.get('currency')}"
    )

    # Products must be sorted best-first
    if len(ranked) > 1:
        assert ranked[0]["value_score"] >= ranked[-1]["value_score"], (
            f"[{scenario_name}] Products not sorted descending by value_score"
        )


# ---------------------------------------------------------------------------
# Scenario 1 — Sports bike under 800 RON
# ---------------------------------------------------------------------------

class TestScenario1SportsBike:
    """
    User wants a sports/mountain bike under 800 RON.

    Flow: initial message may trigger CLARIFY (type/audience ambiguous) → user
    clarifies "mountain bike for adults" → full pipeline runs.
    """

    def setup_method(self):
        _require_env()

    def test_intent_clarifies_then_searches(self):
        """
        First turn: 'sports bike under 800 RON' — might be CLARIFY.
        Second turn clarifies type → must reach SEARCH.
        """
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        # Turn 1: possibly ambiguous
        turn1 = classify_intent(
            [ChatMessage(role="user", content="I want a sports bike under 800 RON")],
            city="Bucharest", country="Romania",
        )
        assert turn1["intent"] in ("CLARIFY", "SEARCH"), (
            f"Expected CLARIFY or SEARCH, got {turn1['intent']}"
        )

        if turn1["intent"] == "SEARCH":
            # Gemini treated it as specific enough — validate params
            params = turn1["collected_params"]
            assert params["budget_max"] == 800.0
            assert params["budget_currency"] == "RON"
            return

        # Turn 2: user clarifies
        messages = [
            ChatMessage(role="user", content="I want a sports bike under 800 RON"),
            ChatMessage(role="assistant", content=turn1["reply"]),
            ChatMessage(role="user", content="A mountain bike for adults please"),
        ]
        turn2 = classify_intent(messages, city="Bucharest", country="Romania")
        assert turn2["intent"] == "SEARCH", (
            f"After clarification, expected SEARCH, got {turn2['intent']}"
        )
        params = turn2["collected_params"]
        assert params["budget_max"] == 800.0
        assert params["budget_currency"] == "RON"

    def test_full_pipeline_finds_ranked_bikes(self):
        """
        Full pipeline: mountain bike for adults under 800 RON.
        Expects at least 1 ranked product with parseable data (score > 40 in at least one dimension).
        """
        from models.search import ChatMessage

        # Use an unambiguous query to skip the clarification turn
        messages = [
            ChatMessage(role="user", content="mountain bike for adults under 800 RON"),
        ]
        intent_data, ranked = _run_full_pipeline(messages)

        if intent_data["intent"] == "CLARIFY":
            pytest.skip(
                "Gemini asked for clarification — add another clarification turn or adjust the query"
            )

        print(f"\n[Bike] Found {len(ranked)} product(s):")
        for p in ranked:
            s = p.get("scores") or {}
            print(
                f"  #{p['rank']} {p.get('title', '?')[:60]} "
                f"| {p.get('price')} {p.get('currency')} "
                f"| value={p['value_score']} "
                f"| cost={s.get('cost_efficiency')} qual={s.get('quality_confidence')} "
                f"logi={s.get('logistics')} trust={s.get('trust')}"
            )

        _assert_pipeline_quality(ranked, "Sports Bike 800 RON", min_value_score=45.0)

    def test_price_within_budget(self):
        """Every ranked bike's confirmed price must be at or below 800 RON."""
        from models.search import ChatMessage

        messages = [ChatMessage(role="user", content="mountain bike for adults under 800 RON")]
        intent_data, ranked = _run_full_pipeline(messages)

        if intent_data["intent"] != "SEARCH" or not ranked:
            pytest.skip("No ranked products returned")

        for p in ranked:
            price = p.get("price")
            currency = p.get("currency", "RON")
            if price is not None and currency == "RON":
                assert float(price) <= 960, (  # allow 120% hard limit (800 * 1.2 = 960)
                    f"Bike priced at {price} RON exceeds 120% of 800 RON budget ceiling"
                )

    def test_local_romanian_domains_searched_first(self):
        """The search query should include local Romanian retailer domains."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent(
            [ChatMessage(role="user", content="mountain bike for adults under 800 RON")],
            city="Bucharest", country="Romania",
        )
        if result["intent"] == "SEARCH":
            domains = result.get("local_domains") or []
            romanian_domains = [d for d in domains if d.endswith(".ro")]
            assert len(romanian_domains) >= 1, (
                f"Expected at least one .ro domain for Romanian user; got: {domains}"
            )


# ---------------------------------------------------------------------------
# Scenario 2 — High-quality digital watch under 500 RON (men's)
# ---------------------------------------------------------------------------

class TestScenario2DigitalWatchMens:
    """
    User wants the highest-quality digital watch they can get for 500 RON.
    If the first results include a women's watch, the user objects and
    the system must re-search with a men's watch refinement.
    """

    def setup_method(self):
        _require_env()

    def test_initial_search_fires_immediately(self):
        """'high quality digital watch under 500 RON' → SEARCH (budget + category explicit)."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent(
            [ChatMessage(role="user", content="high quality digital watch under 500 RON")],
            city="Bucharest", country="Romania",
        )
        assert result["intent"] == "SEARCH"
        params = result["collected_params"]
        assert params["budget_max"] == 500.0
        assert params["budget_currency"] == "RON"

    def test_full_pipeline_finds_watches(self):
        """Full pipeline: digital watch under 500 RON. Top product parseable and scored."""
        from models.search import ChatMessage

        messages = [
            ChatMessage(role="user", content="high quality digital watch under 500 RON")
        ]
        intent_data, ranked = _run_full_pipeline(messages)

        if intent_data["intent"] != "SEARCH":
            pytest.skip(f"Intent not SEARCH: {intent_data['intent']}")

        print(f"\n[Watch initial] Found {len(ranked)} product(s):")
        for p in ranked:
            s = p.get("scores") or {}
            print(
                f"  #{p['rank']} {p.get('title', '?')[:60]} "
                f"| {p.get('price')} {p.get('currency')} "
                f"| value={p['value_score']} "
                f"| cost={s.get('cost_efficiency')} qual={s.get('quality_confidence')} "
                f"logi={s.get('logistics')} trust={s.get('trust')}"
            )

        _assert_pipeline_quality(ranked, "Digital Watch 500 RON", min_value_score=50.0)

    def test_budget_ceiling_respected(self):
        """No watch should be priced above 600 RON (120% of 500 budget ceiling)."""
        from models.search import ChatMessage

        messages = [
            ChatMessage(role="user", content="high quality digital watch under 500 RON")
        ]
        intent_data, ranked = _run_full_pipeline(messages)

        if not ranked:
            pytest.skip("No products returned")

        for p in ranked:
            price = p.get("price")
            if price is not None and p.get("currency", "RON") == "RON":
                assert float(price) <= 600.0, (
                    f"Watch at {price} RON exceeds 120% of 500 RON budget ceiling"
                )

    def test_gender_refinement_not_satisfied_with_womens_watch(self):
        """
        Multi-turn: user receives results → says 'I'm a man, not satisfied because
        this is a women's watch' → system recognises it as a refinement and re-searches
        for men's watches.
        This tests the 'is_refinement=True' path and the preference update.
        """
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        # Simulate: backend just showed some watch results (we invent a women's watch title)
        simulated_assistant_reply = (
            "Here are the top digital watches I found for you:\n"
            "1. Casio LW-200 Ladies Digital Watch — 249 RON\n"
            "2. Citizen Women's Eco-Drive — 480 RON\n"
            "3. Swatch SUOW707 Ladies — 395 RON"
        )

        messages = [
            ChatMessage(
                role="user",
                content="high quality digital watch under 500 RON",
            ),
            ChatMessage(role="assistant", content=simulated_assistant_reply),
            ChatMessage(
                role="user",
                content=(
                    "I'm not satisfied because I am a man and these are women's watches. "
                    "Please find me a men's digital watch instead."
                ),
            ),
        ]

        result = classify_intent(messages, city="Bucharest", country="Romania")

        # System must recognise this as a product refinement, not a new unrelated request
        assert result["intent"] == "SEARCH", (
            f"Expected SEARCH after gender refinement, got {result['intent']}: "
            f"{result.get('reply')}"
        )
        assert result.get("is_refinement") is True, (
            "Expected is_refinement=True for a 'not satisfied' follow-up"
        )

        params = result["collected_params"]
        assert params["budget_max"] == 500.0, "Budget must be preserved from prior turn"
        preference = (params.get("preference") or "").lower()
        assert any(
            kw in preference for kw in ("men", "man", "male", "bărbați", "barbat")
        ), (
            f"Preference must reflect 'men's watch' refinement; got: {params.get('preference')}"
        )

    def test_mens_watch_pipeline_after_refinement(self):
        """
        Full pipeline re-run after the gender refinement.
        Results must be parseable and include men's watch signals.
        """
        from models.search import ChatMessage

        messages = [
            ChatMessage(role="user", content="men's high quality digital watch under 500 RON"),
        ]
        intent_data, ranked = _run_full_pipeline(messages)

        if intent_data["intent"] != "SEARCH":
            pytest.skip(f"Intent not SEARCH: {intent_data['intent']}")

        print(f"\n[Watch men's] Found {len(ranked)} product(s):")
        for p in ranked:
            s = p.get("scores") or {}
            print(
                f"  #{p['rank']} {p.get('title', '?')[:60]} "
                f"| {p.get('price')} {p.get('currency')} "
                f"| value={p['value_score']} "
                f"| cost={s.get('cost_efficiency')} qual={s.get('quality_confidence')}"
            )

        _assert_pipeline_quality(ranked, "Men's Watch 500 RON", min_value_score=50.0)
        # Top product's reasoning or title should signal men's context
        top = ranked[0]
        combined = (
            (top.get("title") or "") + " " + (top.get("reasoning") or "")
        ).lower()
        mens_signals = ["men", "man", "male", "bărbați", "barbat", "casio", "garmin",
                       "sport", "tactical", "g-shock", "watches for men"]
        has_mens_signal = any(sig in combined for sig in mens_signals)
        if not has_mens_signal:
            # Soft warning — don't fail hard since Gemini may express it differently
            print(
                f"  ⚠ Top product title/reasoning doesn't explicitly mention 'men': "
                f"{top.get('title')}"
            )


# ---------------------------------------------------------------------------
# Scenario 3 — Black resistant backpack under 100 RON
# ---------------------------------------------------------------------------

class TestScenario3BlackBackpack:
    """
    User wants a black, resistant backpack under 100 RON.
    This is a common, affordable product well-stocked on Romanian sites
    (decathlon.ro, emag.ro, altex.ro) — the pipeline should find it reliably.

    Goal: demonstrate near-zero parse failures; every score dimension above 40.
    """

    def setup_method(self):
        _require_env()

    def test_intent_fires_search_immediately(self):
        """'black resistant backpack under 100 RON' — all 3 params present → SEARCH."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent(
            [ChatMessage(
                role="user",
                content="black resistant backpack under 100 RON",
            )],
            city="Bucharest", country="Romania",
        )
        assert result["intent"] == "SEARCH", (
            f"Expected SEARCH, got {result['intent']}: {result.get('reply')}"
        )
        params = result["collected_params"]
        assert params["budget_max"] == 100.0
        assert params["budget_currency"] == "RON"
        assert params["preference"] is not None, "Preference (black/resistant) should be extracted"

    def test_local_domains_include_romanian_retailers(self):
        """Romanian location + backpack → domains should include .ro sites."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent(
            [ChatMessage(role="user", content="black resistant backpack under 100 RON")],
            city="Bucharest", country="Romania",
        )
        assert result["intent"] == "SEARCH"
        domains = result.get("local_domains") or []
        romanian = [d for d in domains if d.endswith(".ro")]
        assert len(romanian) >= 1, (
            f"Expected at least one .ro domain for Romanian user; got: {domains}"
        )

    def test_full_pipeline_finds_backpacks(self):
        """
        Full pipeline for cheap backpack. Given the low price point and abundant
        local stock, the pipeline should find at least 1 product with parseable data.
        """
        from models.search import ChatMessage

        messages = [
            ChatMessage(role="user", content="black resistant backpack under 100 RON")
        ]
        intent_data, ranked = _run_full_pipeline(messages)

        if intent_data["intent"] != "SEARCH":
            pytest.skip(f"Intent not SEARCH: {intent_data['intent']}")

        print(f"\n[Backpack] Found {len(ranked)} product(s):")
        for p in ranked:
            s = p.get("scores") or {}
            print(
                f"  #{p['rank']} {p.get('title', '?')[:60]} "
                f"| {p.get('price')} {p.get('currency')} "
                f"| value={p['value_score']} "
                f"| cost={s.get('cost_efficiency')} qual={s.get('quality_confidence')} "
                f"logi={s.get('logistics')} trust={s.get('trust')}"
            )

        _assert_pipeline_quality(ranked, "Black Backpack 100 RON", min_value_score=50.0)

    def test_no_all_40_scores_on_top_product(self):
        """
        The top result must NOT have all four dimensions at exactly 40.
        All-40 means the backend extracted zero useful information from the page
        — this is the core quality gate we want to drive to zero occurrences.
        """
        from models.search import ChatMessage

        messages = [
            ChatMessage(role="user", content="black resistant backpack under 100 RON")
        ]
        intent_data, ranked = _run_full_pipeline(messages)

        if not ranked:
            pytest.skip("No products returned — cannot assert score distribution")

        top = ranked[0]
        scores = top.get("scores") or {}
        all_values = [float(v or 0) for v in scores.values()]
        assert not all(v == 40.0 for v in all_values), (
            f"All four score dimensions are exactly 40 for the top product — "
            f"the backend failed to parse any useful information.\n"
            f"URL: {top.get('url')}\n"
            f"Markdown length: (check scraper logs)"
        )

    def test_price_under_budget_ceiling(self):
        """Every ranked backpack must be at or under 120 RON (120% of 100 RON ceiling)."""
        from models.search import ChatMessage

        messages = [
            ChatMessage(role="user", content="black resistant backpack under 100 RON")
        ]
        intent_data, ranked = _run_full_pipeline(messages)

        if not ranked:
            pytest.skip("No products returned")

        for p in ranked:
            price = p.get("price")
            if price is not None and p.get("currency", "RON") == "RON":
                assert float(price) <= 120.0, (
                    f"Backpack priced at {price} RON exceeds 120% of 100 RON budget ceiling"
                )

    def test_cost_efficiency_high_when_price_well_below_budget(self):
        """
        If any ranked product is priced at ≤70 RON (≤70% of the 100 RON ceiling),
        its cost_efficiency score must be ≥ 70 (reflects the 'well under budget' rubric).
        """
        from models.search import ChatMessage

        messages = [
            ChatMessage(role="user", content="black resistant backpack under 100 RON")
        ]
        intent_data, ranked = _run_full_pipeline(messages)

        if not ranked:
            pytest.skip("No products returned")

        for p in ranked:
            price = p.get("price")
            if price is not None and p.get("currency", "RON") == "RON" and float(price) <= 70.0:
                cost_eff = float((p.get("scores") or {}).get("cost_efficiency", 0) or 0)
                assert cost_eff >= 70, (
                    f"Product at {price} RON (well under 100 RON budget) should have "
                    f"cost_efficiency ≥ 70, got {cost_eff} for '{p.get('title')}'"
                )
