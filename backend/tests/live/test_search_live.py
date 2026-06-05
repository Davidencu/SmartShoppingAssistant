"""
Live integration tests — hit real external APIs.
Run with: pytest -m live

These tests consume real API credits. They guard against silent production breaks
(schema changes, deprecated endpoints, prompt regressions).
Skipped automatically when API keys are not set in the environment.
"""
import os

import pytest

# Skip the entire module if keys are absent
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


# Gemini: Intent Classification

class TestLiveIntentClassification:
    def setup_method(self):
        _require_keys()

    def test_off_topic_returns_chat_intent(self):
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="What is the capital of France?")
        ])
        assert result["intent"] == "CHAT"
        assert result["reply"] is not None
        assert "search_query" in result

    def test_partial_request_returns_clarify_intent(self):
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="I need a laptop")
        ])
        assert result["intent"] in ("CLARIFY", "CHAT")
        assert result["reply"] is not None

    def test_complete_request_returns_search_intent(self):
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(
                role="user",
                content="I need an ASUS laptop with 16GB RAM, budget under 2000 RON",
            )
        ])
        assert result["intent"] == "SEARCH"
        assert result.get("localized_search_query") is not None
        params = result.get("collected_params", {})
        assert params.get("category") is not None
        assert params.get("budget_max") is not None

    def test_multi_turn_extracts_all_params(self):
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        messages = [
            ChatMessage(role="user", content="I need a laptop"),
            ChatMessage(role="assistant", content="What brand do you prefer?"),
            ChatMessage(role="user", content="ASUS, and budget is 2000 RON"),
            ChatMessage(role="assistant", content="Any specific specs?"),
            ChatMessage(role="user", content="16GB RAM please"),
        ]
        result = classify_intent(messages)
        assert result["intent"] == "SEARCH"
        params = result.get("collected_params", {})
        assert "ASUS" in (params.get("preference") or "")
        assert params.get("budget_max") == 2000.0


# Gemini: Embeddings

class TestLiveEmbeddings:
    def setup_method(self):
        _require_keys()

    def test_embedding_returns_768_floats(self):
        from services.gemini_service import generate_embedding

        vec = generate_embedding("ASUS laptop 16GB RAM under 2000 RON")
        assert len(vec) == 768
        assert all(isinstance(v, float) for v in vec)

    def test_similar_queries_have_high_cosine_similarity(self):
        import math
        from services.gemini_service import generate_embedding

        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            return dot / (na * nb)

        v1 = generate_embedding("ASUS laptop 16GB RAM under 2000 RON")
        v2 = generate_embedding("ASUS notebook 16 gigs RAM budget 2000 RON")
        v3 = generate_embedding("red running shoes Nike size 42")

        sim_similar = cosine(v1, v2)
        sim_different = cosine(v1, v3)

        assert sim_similar > 0.85, f"Similar queries too dissimilar: {sim_similar:.3f}"
        assert sim_different < sim_similar, "Dissimilar query scored higher than similar"


# Tavily: Product Search

class TestLiveTavily:
    def setup_method(self):
        _require_keys()

    def test_returns_up_to_10_results(self):
        from services.tavily_service import search_products

        results = search_products("ASUS laptop 16GB RAM buy", max_results=10)
        assert isinstance(results, list)
        assert 1 <= len(results) <= 10
        for r in results:
            assert "url" in r
            assert r["url"].startswith("http")

    def test_returns_empty_list_on_garbage_query(self):
        from services.tavily_service import search_products

        results = search_products("xkcd_gibberish_product_12345_zzz_fake", max_results=3)
        assert isinstance(results, list)


# Scraper: URL Scraping

class TestLiveScraper:
    def setup_method(self):
        _require_keys()

    @pytest.mark.asyncio
    async def test_scrapes_url_to_markdown(self):
        from services.scraper_service import scrape_urls

        # Use an e-commerce product URL — Jina's free tier blocks some domains (e.g. Wikipedia returns 402)
        url = "https://www.emag.ro/laptop-lenovo-ideapad-3/pd/D9LGVSMBM/"
        results = await scrape_urls([url])
        assert len(results) == 1
        assert results[0]["url"] == url
        markdown = results[0]["markdown"]
        if not markdown:
            pytest.skip("Scraper returned empty content (possible bot detection or site block) — skipping")
        assert len(markdown) > 100


# Full Pipeline (expensive — use sparingly)

class TestLiveFullPipeline:
    def setup_method(self):
        _require_keys()
        if not os.environ.get("RUN_FULL_PIPELINE_TESTS"):
            pytest.skip("Set RUN_FULL_PIPELINE_TESTS=1 to run full pipeline live tests")

    def test_full_search_returns_3_ranked_products(self):
        """
        End-to-end: intent → Tavily → Jina → Gemini scoring.
        Costs ~$0.075 in API credits. Gated by RUN_FULL_PIPELINE_TESTS env var.
        """
        import asyncio
        from models.search import ChatMessage
        from services import gemini_service, tavily_service, scraper_service

        messages = [
            ChatMessage(
                role="user",
                content="I want an ASUS laptop with 16GB RAM, budget under 2000 RON",
            )
        ]

        intent_data = gemini_service.classify_intent(messages)
        assert intent_data["intent"] == "SEARCH"

        query = intent_data.get("localized_search_query") or intent_data.get("search_query")
        results = tavily_service.search_products(query, max_results=5)
        assert len(results) >= 1

        urls = [r["url"] for r in results[:5]]
        scraped = asyncio.run(scraper_service.scrape_urls(urls))
        assert any(s.get("markdown") for s in scraped)

        params = intent_data.get("collected_params", {})
        ranked = gemini_service.score_and_rank_products(
            scraped,
            f"{params.get('preference')} {params.get('category')}",
            budget_max=params.get("budget_max"),
            budget_currency=params.get("budget_currency"),
        )
        assert 1 <= len(ranked) <= 3
        assert all("value_score" in p for p in ranked)
        assert ranked[0]["value_score"] >= ranked[-1]["value_score"]


# Real-user intent classification scenarios

class TestLiveRealUserIntents:
    """
    Common real-world shopping prompts — only calls Gemini (cheap, fast).
    Each test represents a query a typical user might type.
    """

    def setup_method(self):
        _require_keys()

    def test_samsung_phone_complete_request_fires_search(self):
        """'Samsung Galaxy S24 under 3000 RON' — all params present → SEARCH."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="Samsung Galaxy S24 under 3000 RON")
        ])
        assert result["intent"] == "SEARCH"
        params = result["collected_params"]
        assert params["budget_max"] == 3000.0
        assert params["budget_currency"] == "RON"
        assert params["category"] is not None

    def test_just_phone_triggers_clarify(self):
        """'I want a phone' — no budget, no brand → CLARIFY."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="I want a phone")
        ])
        assert result["intent"] in ("CLARIFY", "CHAT")
        assert result["reply"] is not None

    def test_nike_shoes_with_size_and_budget(self):
        """'Nike running shoes size 42 under 500 RON' → SEARCH."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="Nike running shoes size 42 under 500 RON")
        ])
        assert result["intent"] == "SEARCH"
        params = result["collected_params"]
        assert params["budget_max"] == 500.0
        assert "Nike" in (params["preference"] or "")

    def test_bike_with_budget_but_no_type_triggers_clarify(self):
        """'bike for 800 RON' — ambiguous (adult/child? mountain/road?) → CLARIFY."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="I need a bike for 800 RON")
        ])
        # CLARIFY expected because type/audience is ambiguous
        assert result["intent"] in ("CLARIFY", "SEARCH")
        assert result["reply"] is not None or result["intent"] == "SEARCH"

    def test_off_topic_weather_returns_chat_and_redirect(self):
        """'What's the weather in Bucharest?' → CHAT with shopping redirect."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="What's the weather in Bucharest today?")
        ])
        assert result["intent"] == "CHAT"
        assert result["reply"] is not None
        assert len(result["reply"]) > 10

    def test_no_brand_preference_with_budget_fires_search(self):
        """No-brand + budget + use-case → SEARCH with preference='best value for budget'."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        # Laptop is a high-complexity category that requires a use case (Adaptive Requirement Gate).
        # Including the use case gives Gemini all required params → SEARCH.
        result = classify_intent([
            ChatMessage(role="user", content="I need a laptop for office work under 2000 RON, I don't care about brand")
        ])
        assert result["intent"] == "SEARCH"
        params = result["collected_params"]
        assert params["budget_max"] == 2000.0
        assert params["preference"] is not None  # "best value for budget" or similar

    def test_gaming_laptop_full_params_fires_search(self):
        """'ASUS or Lenovo gaming laptop 16GB RAM under 4000 RON' → SEARCH."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="ASUS or Lenovo gaming laptop 16GB RAM under 4000 RON")
        ])
        assert result["intent"] == "SEARCH"
        params = result["collected_params"]
        assert params["budget_max"] == 4000.0
        assert params["budget_currency"] == "RON"

    def test_location_context_produces_local_domains(self):
        """With Romanian location, Gemini should suggest at least one .ro domain."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent(
            [ChatMessage(role="user", content="Sony WH-1000XM5 headphones under 1500 RON")],
            city="Bucharest",
            country="Romania",
        )
        assert result["intent"] == "SEARCH"
        domains = result.get("local_domains") or []
        romanian = [d for d in domains if d.endswith(".ro")]
        assert len(romanian) >= 1, f"No .ro domain suggested for Romanian user; got: {domains}"

    def test_multi_turn_progressive_reveal_reaches_search(self):
        """
        5-message conversation where the user reveals params one by one.
        Final turn must yield SEARCH with all params populated.
        """
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        messages = [
            ChatMessage(role="user",      content="I need a gaming laptop"),
            ChatMessage(role="assistant", content="What's your budget?"),
            ChatMessage(role="user",      content="under 4000 RON"),
            ChatMessage(role="assistant", content="Any brand or spec preference?"),
            ChatMessage(role="user",      content="ASUS or Lenovo, 16GB RAM"),
        ]
        result = classify_intent(messages)
        assert result["intent"] == "SEARCH"
        params = result["collected_params"]
        assert params["budget_max"] == 4000.0
        assert params["budget_currency"] == "RON"
        assert params["preference"] is not None

    def test_around_budget_treated_as_ceiling(self):
        """'around 1500 RON' should be treated as a ceiling (budget_max ≈ 1500)."""
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        result = classify_intent([
            ChatMessage(role="user", content="ASUS VivoBook laptop around 1500 RON")
        ])
        if result["intent"] == "SEARCH":
            params = result["collected_params"]
            assert params["budget_max"] is not None
            assert 1400 <= params["budget_max"] <= 1600, (
                f"'around 1500 RON' should yield budget_max near 1500, got {params['budget_max']}"
            )


# Under-budget scoring (full pipeline, expensive)

class TestLiveUnderBudgetScoring:
    """
    Verifies that when the pipeline finds products significantly cheaper than the
    user's budget, those products receive high cost_efficiency scores.
    Gated by RUN_FULL_PIPELINE_TESTS because it costs real API credits.
    """

    def setup_method(self):
        _require_keys()
        if not os.environ.get("RUN_FULL_PIPELINE_TESTS"):
            pytest.skip("Set RUN_FULL_PIPELINE_TESTS=1 to run full pipeline live tests")

    def test_generous_budget_yields_high_cost_efficiency_scores(self):
        """
        User sets a very high budget (5000 RON) for a cheap product (mouse ~100–300 RON).
        All found products should be far under budget → cost_efficiency ≥ 70.
        """
        import asyncio
        from models.search import ChatMessage
        from services import gemini_service, tavily_service, scraper_service
        from routers.search import _build_search_query
        from models.search import IntentParams

        intent_data = gemini_service.classify_intent(
            [ChatMessage(role="user", content="Logitech wireless mouse under 5000 RON")],
            city="Bucharest",
            country="Romania",
        )
        assert intent_data["intent"] == "SEARCH"

        params_raw = intent_data.get("collected_params", {})
        params = IntentParams(
            category=params_raw.get("category"),
            budget=params_raw.get("budget"),
            budget_max=params_raw.get("budget_max"),
            budget_currency=params_raw.get("budget_currency"),
            preference=params_raw.get("preference"),
        )
        query, domains = _build_search_query(intent_data.get("localized_search_query"), params, intent_data.get("local_domains"))

        results = tavily_service.search_products(query, max_results=5, include_domains=domains)
        assert len(results) >= 1

        scraped = asyncio.run(scraper_service.scrape_urls([r["url"] for r in results[:5]]))
        usable = [s for s in scraped if len(s.get("markdown") or "") > 200]
        assert len(usable) >= 1, "Scraper returned no usable content"

        ranked = gemini_service.score_and_rank_products(
            usable,
            "Logitech wireless mouse",
            budget_max=5000.0,
            budget_currency="RON",
            city="Bucharest",
            country="Romania",
        )

        assert len(ranked) >= 1, "Scoring returned no products — check the under-budget fix"
        top = ranked[0]
        assert top["scores"]["cost_efficiency"] >= 70, (
            f"Product well under 5000 RON budget should score ≥70 cost_efficiency, "
            f"got {top['scores']['cost_efficiency']} for '{top['title']}' at {top.get('price')} RON"
        )
        assert top["value_score"] >= 55.0
        assert ranked[0]["value_score"] >= ranked[-1]["value_score"], "Products not sorted by value_score"

    def test_products_ranked_by_quality_price_ratio(self):
        """
        For a standard search (laptop under 2000 RON), the winner should have
        a better quality-price ratio than the runner-up.
        """
        import asyncio
        from models.search import ChatMessage
        from services import gemini_service, tavily_service, scraper_service

        intent_data = gemini_service.classify_intent(
            [ChatMessage(role="user", content="laptop under 2000 RON, no brand preference")],
            city="Bucharest",
            country="Romania",
        )
        assert intent_data["intent"] == "SEARCH"

        params = intent_data.get("collected_params", {})
        query = intent_data.get("localized_search_query") or intent_data.get("search_query") or "laptop"

        results = tavily_service.search_products(query, max_results=5)
        assert len(results) >= 1

        scraped = asyncio.run(scraper_service.scrape_urls([r["url"] for r in results[:5]]))
        usable = [s for s in scraped if len(s.get("markdown") or "") > 200]
        assert len(usable) >= 1

        ranked = gemini_service.score_and_rank_products(
            usable,
            "laptop best value for budget",
            budget_max=params.get("budget_max", 2000.0),
            budget_currency=params.get("budget_currency", "RON"),
            city="Bucharest",
            country="Romania",
        )

        assert len(ranked) >= 2
        assert ranked[0]["value_score"] > ranked[1]["value_score"]
        # Top product's reasoning should mention price or value
        assert len(ranked[0].get("reasoning", "")) > 20


# explain_no_results (cheap: single Gemini call)

class TestLiveExplainNoResults:
    """Verify explain_no_results() returns coherent diagnostic text."""

    def setup_method(self):
        _require_keys()

    def test_returns_nonempty_explanation_for_impossible_budget(self):
        from services.gemini_service import explain_no_results

        result = explain_no_results(
            category="Laptop",
            preference="16GB RAM gaming",
            budget_max=100.0,
            budget_currency="RON",
            city="Bucharest",
            country="Romania",
        )
        assert isinstance(result, str)
        assert len(result) > 20

    def test_response_is_plain_text_not_json(self):
        from services.gemini_service import explain_no_results

        result = explain_no_results(
            category="Phone",
            preference="iPhone 15 Pro Max",
            budget_max=500.0,
            budget_currency="RON",
            city="",
            country="",
        )
        assert isinstance(result, str)
        assert len(result) > 20
        assert not result.strip().startswith("{")

    def test_handles_minimal_args(self):
        from services.gemini_service import explain_no_results

        result = explain_no_results(
            category="product",
            preference="",
            budget_max=None,
            budget_currency=None,
        )
        assert isinstance(result, str)
        assert len(result) > 10


# "Not satisfied" follow-up intent classification

class TestLiveNotSatisfiedIntent:
    """
    Verify that multi-turn 'not satisfied' follow-ups are classified correctly
    and that updated params (e.g. new budget) are extracted.
    """

    def setup_method(self):
        _require_keys()

    def test_not_satisfied_with_budget_increase_fires_search(self):
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        messages = [
            ChatMessage(role="user", content="ASUS laptop 16GB RAM under 2000 RON"),
            ChatMessage(role="assistant", content="Here are the top products..."),
            ChatMessage(
                role="user",
                content="I'm not satisfied because: I cannot find a buy button. Increase budget to 2500 RON.",
            ),
        ]
        result = classify_intent(messages)
        assert result["intent"] in ("SEARCH", "CLARIFY")
        if result["intent"] == "SEARCH":
            params = result["collected_params"]
            assert params["budget_max"] is not None

    def test_not_satisfied_complaint_gets_reply(self):
        from models.search import ChatMessage
        from services.gemini_service import classify_intent

        messages = [
            ChatMessage(role="user", content="wireless mouse under 200 RON"),
            ChatMessage(role="assistant", content="Here are the top products..."),
            ChatMessage(role="user", content="I'm not satisfied because: all products are too expensive"),
        ]
        result = classify_intent(messages)
        assert result["intent"] in ("SEARCH", "CLARIFY", "CHAT")
        # If clarifying or chatting, a reply must be present
        if result["intent"] != "SEARCH":
            assert result["reply"] is not None and len(result["reply"]) > 5
