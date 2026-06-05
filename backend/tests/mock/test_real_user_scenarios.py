"""
Real-user scenario tests.
Every test class models a type of query a real person would type into the chat.
All external API calls (Gemini, Tavily, Jina, Supabase) are mocked.

Run with: pytest tests/mock/test_real_user_scenarios.py
"""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from tests.conftest import sse_result

CHAT_URL = "/search/chat"


# Score helpers

def _value_score(cost_eff, quality, logistics, trust) -> float:
    from services.gemini_service import SCORE_WEIGHTS
    return round(
        cost_eff   * SCORE_WEIGHTS["cost_efficiency"]
        + quality  * SCORE_WEIGHTS["quality_confidence"]
        + logistics * SCORE_WEIGHTS["logistics"]
        + trust    * SCORE_WEIGHTS["trust"],
        1,
    )


def _product(rank, title, url, price, currency, cost_eff, quality, logistics, trust):
    return {
        "rank": rank,
        "title": title,
        "url": url,
        "price": price,
        "currency": currency,
        "image_url": None,
        "scores": {
            "cost_efficiency": cost_eff,
            "quality_confidence": quality,
            "logistics": logistics,
            "trust": trust,
        },
        "value_score": _value_score(cost_eff, quality, logistics, trust),
        "reasoning": f"Price {price} {currency}.",
    }


def _rich_markdown(title: str, price: float, currency: str) -> str:
    """Produce markdown that clears the >200-char content filter in the search router."""
    return (
        f"# {title}\n\n"
        f"**Price:** {price} {currency}\n\n"
        "**Availability:** In Stock. Ships within 1-3 business days.\n\n"
        "**Rating:** 4.3 out of 5 stars based on 150 verified reviews.\n\n"
        "**Description:** High-quality product with excellent build quality and durability. "
        "Comes with a 12-month manufacturer warranty. Free standard shipping on all orders "
        "over 200 RON. Sold and fulfilled by an authorised retailer.\n\n"
        "**Specifications:** Key features include modern design, reliable performance, "
        "and compatibility with all major accessories in this product category."
    )


def _mock_full_pipeline(mocker, intent_payload, products):
    mocker.patch("services.gemini_service.classify_intent", return_value=intent_payload)
    mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
    mocker.patch(
        "services.gemini_service.research_community_picks",
        return_value={"recommendations": [], "insight": None},
    )
    # Bypass the product-URL heuristic so short test URLs are never filtered out.
    mocker.patch("routers.search.is_likely_product_url", return_value=True)
    mocker.patch("services.cache_service.lookup_cache", return_value=None)
    mocker.patch("services.tavily_service.search_products", return_value=[
        {"url": p["url"], "title": p["title"]} for p in products
    ])
    mocker.patch("services.scraper_service.scrape_urls", new=AsyncMock(return_value=[
        {"url": p["url"], "markdown": _rich_markdown(p["title"], p["price"], p["currency"])}
        for p in products
    ]))
    mocker.patch("services.gemini_service.score_and_rank_products", return_value=products)
    mocker.patch("services.cache_service.save_cache")


def _search_intent(category, budget, budget_max, currency, preference, domains=None):
    return {
        "intent": "SEARCH",
        "reply": None,
        "collected_params": {
            "category": category,
            "budget": budget,
            "budget_max": budget_max,
            "budget_currency": currency,
            "preference": preference,
        },
        "search_query": f"{preference} {category} buy {budget}",
        "local_domains": domains,
    }


def _clarify_intent(reply, collected=None):
    return {
        "intent": "CLARIFY",
        "reply": reply,
        "collected_params": collected or {
            "category": None, "budget": None,
            "budget_max": None, "budget_currency": None, "preference": None,
        },
        "search_query": None,
        "local_domains": None,
    }


# 1. Score-weight unit tests

class TestScoreWeights:
    def test_weights_sum_to_one(self):
        from services.gemini_service import SCORE_WEIGHTS
        assert abs(sum(SCORE_WEIGHTS.values()) - 1.0) < 1e-9

    def test_quality_price_ratio_dominates(self):
        """cost_efficiency + quality_confidence must account for ≥70% of the score."""
        from services.gemini_service import SCORE_WEIGHTS
        qp_weight = SCORE_WEIGHTS["cost_efficiency"] + SCORE_WEIGHTS["quality_confidence"]
        assert qp_weight >= 0.70, f"Quality-price weight is only {qp_weight:.0%}"

    def test_under_budget_product_outranks_near_budget_product(self):
        """
        Phone at 400 RON (half of 800 RON budget) with decent quality should beat
        a phone at 750 RON with higher reviews — because the price gap is huge.
        """
        cheap  = _value_score(cost_eff=95, quality=72, logistics=70, trust=70)
        pricey = _value_score(cost_eff=40, quality=88, logistics=82, trust=88)
        assert cheap > pricey, (
            f"Under-budget product ({cheap}) must outrank near-budget product ({pricey})"
        )

    def test_over_budget_product_loses_to_same_quality_in_budget(self):
        """
        An over-budget product (cost_eff=0) must lose to an identical product that is
        within budget (cost_eff=80), when all other dimensions are equal.
        """
        over_budget   = _value_score(cost_eff=0,  quality=80, logistics=80, trust=80)
        in_budget     = _value_score(cost_eff=80, quality=80, logistics=80, trust=80)
        assert over_budget < in_budget


# 2. Under-budget product scoring

class TestUnderBudgetProductScoring:
    """
    Tests the Python-side score recomputation in gemini_service.score_and_rank_products.
    Mocks _client.models.generate_content so we control what "Gemini" returns.
    """

    def _run_scoring(self, mocker, gemini_products, scraped=None):
        response_mock = MagicMock()
        response_mock.text = json.dumps({"ranked_products": gemini_products})
        mocker.patch(
            "services.gemini_service._client.models.generate_content",
            return_value=response_mock,
        )
        from services.gemini_service import score_and_rank_products
        return score_and_rank_products(
            scraped or [{"url": p["url"], "markdown": "# Title\nPrice visible\nIn stock.", "title": p["title"]} for p in gemini_products],
            "test search",
            budget_max=1000.0,
            budget_currency="RON",
        )

    def test_python_recomputes_value_score_regardless_of_gemini_value(self, mocker):
        """Even if Gemini returns value_score=0.0, Python recomputes the correct number."""
        raw = [{
            "rank": 1, "title": "Cheap Phone", "url": "https://emag.ro/p",
            "price": 499.0, "currency": "RON", "image_url": None,
            "scores": {"cost_efficiency": 95, "quality_confidence": 72, "logistics": 75, "trust": 80},
            "value_score": 0.0,  # Gemini returned garbage — Python must override
            "reasoning": "Well below budget.",
        }]
        ranked = self._run_scoring(mocker, raw)
        expected = _value_score(95, 72, 75, 80)
        assert len(ranked) == 1
        assert ranked[0]["value_score"] == expected
        assert ranked[0]["value_score"] > 50

    def test_half_budget_product_ranks_above_near_budget_product(self, mocker):
        """
        Headphones at 150 RON (half of 300 RON budget) should beat
        headphones at 270 RON with better reviews, because the price gap matters more.
        """
        budget_headphones = {
            "rank": 2, "title": "Budget Headphones", "url": "https://emag.ro/budget",
            "price": 150.0, "currency": "RON", "image_url": None,
            "scores": {"cost_efficiency": 95, "quality_confidence": 70, "logistics": 70, "trust": 72},
            "value_score": 0.0, "reasoning": "150 RON, half the budget.",
        }
        premium_headphones = {
            "rank": 1, "title": "Premium Headphones", "url": "https://emag.ro/premium",
            "price": 270.0, "currency": "RON", "image_url": None,
            "scores": {"cost_efficiency": 55, "quality_confidence": 88, "logistics": 80, "trust": 85},
            "value_score": 0.0, "reasoning": "270 RON, near 300 RON ceiling.",
        }
        # Gemini incorrectly ranked the expensive one first
        ranked = self._run_scoring(mocker, [premium_headphones, budget_headphones])
        assert ranked[0]["title"] == "Budget Headphones", (
            f"Under-budget product should rank first, got '{ranked[0]['title']}' "
            f"(scores: {[(p['title'][:15], p['value_score']) for p in ranked]})"
        )

    def test_products_always_sorted_by_recomputed_score(self, mocker):
        """After recomputation the list is always sorted descending by value_score."""
        products = [
            {"rank": 1, "title": "Mid", "url": "https://x.com/mid", "price": 500, "currency": "RON",
             "image_url": None,
             "scores": {"cost_efficiency": 70, "quality_confidence": 70, "logistics": 70, "trust": 70},
             "value_score": 99.9, "reasoning": ""},
            {"rank": 2, "title": "Best", "url": "https://x.com/best", "price": 200, "currency": "RON",
             "image_url": None,
             "scores": {"cost_efficiency": 100, "quality_confidence": 80, "logistics": 80, "trust": 80},
             "value_score": 0.0, "reasoning": ""},
            {"rank": 3, "title": "Worst", "url": "https://x.com/worst", "price": 950, "currency": "RON",
             "image_url": None,
             "scores": {"cost_efficiency": 30, "quality_confidence": 50, "logistics": 50, "trust": 50},
             "value_score": 0.0, "reasoning": ""},
        ]
        ranked = self._run_scoring(mocker, products)
        scores = [p["value_score"] for p in ranked]
        assert scores == sorted(scores, reverse=True), f"Not sorted: {scores}"
        assert ranked[0]["title"] == "Best"

    def test_rank_numbers_reassigned_after_sort(self, mocker):
        """rank field should be 1, 2, 3 after Python re-sorts, not Gemini's original order."""
        products = [
            {"rank": 3, "title": "Actually First", "url": "https://x.com/1", "price": 200,
             "currency": "RON", "image_url": None,
             "scores": {"cost_efficiency": 100, "quality_confidence": 80, "logistics": 80, "trust": 80},
             "value_score": 0.0, "reasoning": ""},
            {"rank": 1, "title": "Actually Second", "url": "https://x.com/2", "price": 600,
             "currency": "RON", "image_url": None,
             "scores": {"cost_efficiency": 70, "quality_confidence": 70, "logistics": 70, "trust": 70},
             "value_score": 0.0, "reasoning": ""},
            {"rank": 2, "title": "Actually Third", "url": "https://x.com/3", "price": 900,
             "currency": "RON", "image_url": None,
             "scores": {"cost_efficiency": 30, "quality_confidence": 50, "logistics": 50, "trust": 50},
             "value_score": 0.0, "reasoning": ""},
        ]
        ranked = self._run_scoring(mocker, products)
        assert [p["rank"] for p in ranked] == [1, 2, 3]
        assert ranked[0]["title"] == "Actually First"

    def test_score_clamped_to_0_100(self, mocker):
        """Gemini sometimes returns out-of-range scores; they must be clamped."""
        products = [{
            "rank": 1, "title": "Item", "url": "https://x.com/item", "price": 100,
            "currency": "RON", "image_url": None,
            "scores": {"cost_efficiency": 120, "quality_confidence": -10, "logistics": 50, "trust": 50},
            "value_score": 0.0, "reasoning": "",
        }]
        ranked = self._run_scoring(mocker, products)
        s = ranked[0]["scores"]
        assert s["cost_efficiency"] == 100.0
        assert s["quality_confidence"] == 0.0


# 3. Common product search requests

class TestCommonProductRequests:
    """
    Complete requests (all 3 required params present) should trigger the full
    search pipeline and return 3 ranked products.
    """

    def test_samsung_phone_under_3000_ron(self, client, mock_supabase, auth_token, mocker):
        """User: 'Samsung Galaxy S24 under 3000 RON'"""
        phones = [
            _product(1, "Samsung Galaxy S24 128GB", "https://emag.ro/s24", 2499, "RON", 88, 92, 85, 95),
            _product(2, "Samsung Galaxy S23 128GB", "https://emag.ro/s23", 1799, "RON", 96, 85, 85, 95),
            _product(3, "Samsung Galaxy A55 5G",   "https://altex.ro/a55", 1299, "RON", 100, 72, 80, 90),
        ]
        _mock_full_pipeline(
            mocker,
            _search_intent("Phone", "under 3000 RON", 3000.0, "RON", "Samsung Galaxy S24", ["emag.ro", "altex.ro"]),
            phones,
        )
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "Samsung Galaxy S24 under 3000 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "SEARCH"
        assert len(data["products"]) == 3
        assert data["from_cache"] is False
        assert data["collected_params"]["budget_max"] == 3000.0
        assert data["collected_params"]["budget_currency"] == "RON"

    def test_nike_running_shoes_size_42_under_500_ron(self, client, mock_supabase, auth_token, mocker):
        """User: 'Nike Air Max size 42 under 500 RON'"""
        shoes = [
            _product(1, "Nike Air Max 270 Size 42", "https://answear.ro/am270", 379, "RON", 95, 80, 75, 90),
            _product(2, "Nike Revolution 6 Size 42","https://emag.ro/rev6",    299, "RON", 100, 70, 80, 88),
            _product(3, "Nike Air Force 1 Size 42", "https://sport.ro/af1",    449, "RON", 78, 87, 70, 85),
        ]
        _mock_full_pipeline(
            mocker,
            _search_intent("Shoes", "under 500 RON", 500.0, "RON", "Nike Air Max size 42", ["emag.ro", "answear.ro"]),
            shoes,
        )
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "Nike Air Max size 42 under 500 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "SEARCH"
        assert data["collected_params"]["category"] == "Shoes"

    def test_sony_headphones_noise_cancelling_under_1500_ron(self, client, mock_supabase, auth_token, mocker):
        """User: 'Sony WH-1000XM5 noise cancelling under 1500 RON'"""
        # XM4 at 899 RON is well under budget: cost_eff=100 gives it the highest value_score.
        # Products are pre-sorted by value_score (as score_and_rank_products would do).
        headphones = [
            _product(1, "Sony WH-1000XM4",      "https://altex.ro/xm4",   899, "RON", 100, 88, 85, 97),
            _product(2, "Sony WH-1000XM5",      "https://emag.ro/xm5",   1299, "RON",  88, 95, 85, 98),
            _product(3, "Bose QuietComfort 45", "https://flanco.ro/bose", 1399, "RON",  72, 92, 80, 95),
        ]
        _mock_full_pipeline(
            mocker,
            _search_intent("Headphones", "under 1500 RON", 1500.0, "RON", "Sony WH-1000XM5 noise cancelling"),
            headphones,
        )
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "Sony WH-1000XM5 noise cancelling under 1500 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "SEARCH"
        products = data["products"]
        # XM4 at 899 RON (well under budget) ranks first due to high cost_efficiency
        assert products[0]["title"] == "Sony WH-1000XM4"
        assert products[0]["scores"]["cost_efficiency"] == 100

    def test_asus_gaming_laptop_under_4000_ron(self, client, mock_supabase, auth_token, mocker):
        """User: 'ASUS gaming laptop 16GB RAM under 4000 RON'"""
        # TUF (90 cost_eff, 85 quality) beats ROG Strix (78, 94) because the price advantage
        # (cost_efficiency weight 40%) outweighs the quality gap on this balanced comparison.
        # Products are pre-sorted by value_score, as score_and_rank_products would return them.
        laptops = [
            _product(1, "ASUS TUF Gaming F15",   "https://altex.ro/tuf", 2999, "RON", 90, 85, 85, 94),
            _product(2, "ASUS ROG Strix G15",    "https://emag.ro/rog",  3799, "RON", 78, 94, 85, 95),
            _product(3, "ASUS VivoBook Pro 15", "https://emag.ro/vivo",  2499, "RON", 95, 78, 80, 90),
        ]
        _mock_full_pipeline(
            mocker,
            _search_intent("Gaming Laptop", "under 4000 RON", 4000.0, "RON", "ASUS 16GB RAM gaming", ["emag.ro", "altex.ro"]),
            laptops,
        )
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "ASUS gaming laptop 16GB RAM under 4000 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        products = sse_result(resp)["products"]
        assert len(products) == 3
        # The most expensive option (ROG Strix at 3799) should not rank first
        assert products[0]["title"] != "ASUS ROG Strix G15"
        assert products[0]["value_score"] >= products[-1]["value_score"]

    def test_trek_mountain_bike_for_adults_under_2500_ron(self, client, mock_supabase, auth_token, mocker):
        """User: 'Trek mountain bike for adults under 2500 RON'"""
        bikes = [
            _product(1, "Trek Marlin 5 29\"",    "https://trek.ro/marlin5", 1899, "RON", 95, 85, 75, 92),
            _product(2, "Trek Marlin 7 29\"",    "https://ciclist.ro/m7",   2299, "RON", 85, 90, 72, 92),
            _product(3, "Trek Dual Sport 2",     "https://emag.ro/trek-ds", 1599, "RON", 100, 75, 70, 88),
        ]
        _mock_full_pipeline(
            mocker,
            _search_intent("Mountain Bike", "under 2500 RON", 2500.0, "RON", "Trek for adults", ["decathlon.ro"]),
            bikes,
        )
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "Trek mountain bike for adults under 2500 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "SEARCH"
        assert data["collected_params"]["category"] == "Mountain Bike"

    def test_apple_airpods_pro_under_200_usd(self, client, mock_supabase, auth_token, mocker):
        """User: 'Apple AirPods Pro under 200 USD' — different currency"""
        earbuds = [
            _product(1, "Apple AirPods Pro 2nd Gen", "https://apple.com/airpods-pro", 179, "USD", 88, 95, 90, 100),
            _product(2, "Apple AirPods Pro 1st Gen", "https://amazon.com/aap1",       129, "USD", 100, 85, 85, 98),
            _product(3, "Sony LinkBuds S",           "https://sony.com/linkbuds",     149, "USD", 92, 88, 82, 92),
        ]
        _mock_full_pipeline(
            mocker,
            _search_intent("Earbuds", "under 200 USD", 200.0, "USD", "Apple AirPods Pro"),
            earbuds,
        )
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "Apple AirPods Pro under 200 USD"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["collected_params"]["budget_currency"] == "USD"
        assert len(data["products"]) == 3


# 4. Ambiguous requests that should trigger CLARIFY

class TestAmbiguousRequestsTriggerClarify:

    def test_just_phone_no_budget_no_brand(self, client, mock_supabase, auth_token, mocker):
        """'I want a phone' — no budget, no brand → ask for both."""
        tavily = mocker.patch("services.tavily_service.search_products")
        mocker.patch("services.gemini_service.classify_intent", return_value=_clarify_intent(
            "What's your budget and do you have a brand preference (Samsung, Apple, Xiaomi)?"
        ))
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "I want a phone"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "CLARIFY"
        assert data["reply"] is not None
        assert data["products"] is None
        tavily.assert_not_called()

    def test_laptop_no_budget(self, client, mock_supabase, auth_token, mocker):
        """'I need a laptop' — category found, budget missing → ask for budget."""
        tavily = mocker.patch("services.tavily_service.search_products")
        mocker.patch("services.gemini_service.classify_intent", return_value=_clarify_intent(
            "What's your budget for the laptop?",
            collected={
                "category": "Laptop", "budget": None,
                "budget_max": None, "budget_currency": None, "preference": None,
            },
        ))
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "I need a laptop"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "CLARIFY"
        assert data["collected_params"]["category"] == "Laptop"
        assert data["collected_params"]["budget"] is None
        tavily.assert_not_called()

    def test_bike_for_unknown_person_triggers_clarify(self, client, mock_supabase, auth_token, mocker):
        """'I need a bike for 800 RON' — ambiguous (adult or child? mountain or road?)."""
        tavily = mocker.patch("services.tavily_service.search_products")
        mocker.patch("services.gemini_service.classify_intent", return_value=_clarify_intent(
            "Is this bike for an adult or a child? And what type — mountain, road, or city?",
            collected={
                "category": "Bike", "budget": "800 RON",
                "budget_max": 800.0, "budget_currency": "RON", "preference": None,
            },
        ))
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "I need a bike for 800 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "CLARIFY"
        assert data["collected_params"]["budget_max"] == 800.0
        assert data["collected_params"]["preference"] is None
        tavily.assert_not_called()

    def test_vague_quality_adjective_triggers_clarify(self, client, mock_supabase, auth_token, mocker):
        """'best quality laptop under 2000 RON' — 'best quality' is not a concrete spec."""
        tavily = mocker.patch("services.tavily_service.search_products")
        mocker.patch("services.gemini_service.classify_intent", return_value=_clarify_intent(
            "What will you use the laptop for — office work, gaming, or video editing?",
            collected={
                "category": "Laptop", "budget": "under 2000 RON",
                "budget_max": 2000.0, "budget_currency": "RON", "preference": None,
            },
        ))
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "best quality laptop under 2000 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        assert sse_result(resp)["intent"] == "CLARIFY"
        tavily.assert_not_called()

    def test_off_topic_request_returns_chat_and_no_search(self, client, mock_supabase, auth_token, mocker):
        """'What is the capital of France?' — completely off-topic → CHAT."""
        tavily = mocker.patch("services.tavily_service.search_products")
        mocker.patch("services.gemini_service.classify_intent", return_value={
            "intent": "CHAT",
            "reply": "I'm a shopping assistant and can't help with that — what product can I help you find?",
            "collected_params": {
                "category": None, "budget": None,
                "budget_max": None, "budget_currency": None, "preference": None,
            },
            "search_query": None,
            "local_domains": None,
        })
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "What is the capital of France?"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "CHAT"
        assert data["products"] is None
        tavily.assert_not_called()


# 5. No-preference handling

class TestNoPreferenceHandling:
    """
    When the user says 'I don't care about brand' + gives category + budget,
    the system must fire SEARCH immediately with preference='best value for budget'.
    """

    def test_no_brand_preference_fires_search(self, client, mock_supabase, auth_token, mocker):
        laptops = [
            _product(1, "Lenovo IdeaPad 3",  "https://emag.ro/ideapad3", 1299, "RON", 100, 72, 80, 85),
            _product(2, "HP Pavilion 15",    "https://altex.ro/hp-pav",  1499, "RON",  90, 78, 80, 85),
            _product(3, "Acer Aspire 5",     "https://emag.ro/acer-a5",  1799, "RON",  78, 82, 75, 80),
        ]
        _mock_full_pipeline(
            mocker,
            _search_intent("Laptop", "under 2000 RON", 2000.0, "RON", "best value for budget", ["emag.ro", "altex.ro"]),
            laptops,
        )
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "best laptop under 2000 RON, I don't care about brand"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "SEARCH"
        assert data["collected_params"]["preference"] == "best value for budget"
        assert len(data["products"]) == 3

    def test_surprise_me_fires_search_not_clarify(self, client, mock_supabase, auth_token, mocker):
        """'Surprise me with a phone under 1000 RON' → SEARCH, not CLARIFY."""
        phones = [
            _product(1, "Xiaomi Redmi Note 13", "https://emag.ro/xm-rn13",  699, "RON", 100, 78, 82, 85),
            _product(2, "Motorola Moto G84",    "https://altex.ro/moto-g84", 799, "RON",  92, 75, 80, 82),
            _product(3, "Samsung Galaxy A25",   "https://emag.ro/a25",       849, "RON",  88, 80, 80, 90),
        ]
        _mock_full_pipeline(
            mocker,
            _search_intent("Phone", "under 1000 RON", 1000.0, "RON", "best value for budget"),
            phones,
        )
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "surprise me with a phone under 1000 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        assert sse_result(resp)["intent"] == "SEARCH"


# 6. Multi-turn conversations

class TestMultiTurnConversation:

    def test_budget_revealed_in_second_message(self, client, mock_supabase, auth_token, mocker):
        """
        Turn 1: 'I need an ASUS laptop'     → CLARIFY (budget?)
        Turn 2: 'budget is 2000 RON'         → SEARCH
        """
        mocker.patch("services.gemini_service.classify_intent", return_value=_clarify_intent(
            "What's your budget?",
            collected={"category": "Laptop", "budget": None, "budget_max": None, "budget_currency": None, "preference": "ASUS brand"},
        ))
        resp1 = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "I need an ASUS laptop"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        data1 = sse_result(resp1)
        assert data1["intent"] == "CLARIFY"
        assert data1["collected_params"]["preference"] == "ASUS brand"

        laptops = [
            _product(1, "ASUS VivoBook 16",  "https://emag.ro/vivo16", 1799, "RON", 88, 80, 85, 90),
            _product(2, "ASUS ZenBook 14",   "https://altex.ro/zen14", 1599, "RON", 95, 75, 80, 90),
            _product(3, "ASUS ExpertBook B1","https://emag.ro/exp",    1399, "RON", 100, 68, 75, 85),
        ]
        _mock_full_pipeline(
            mocker,
            _search_intent("Laptop", "2000 RON", 2000.0, "RON", "ASUS brand", ["emag.ro", "altex.ro"]),
            laptops,
        )
        resp2 = client.post(
            CHAT_URL,
            json={"messages": [
                {"role": "user",      "content": "I need an ASUS laptop"},
                {"role": "assistant", "content": "What's your budget?"},
                {"role": "user",      "content": "budget is 2000 RON"},
            ]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp2.status_code == 200
        data2 = sse_result(resp2)
        assert data2["intent"] == "SEARCH"
        assert data2["collected_params"]["budget_max"] == 2000.0
        assert data2["collected_params"]["preference"] == "ASUS brand"
        assert len(data2["products"]) == 3

    def test_three_turn_spec_revealed_progressively(self, client, mock_supabase, auth_token, mocker):
        """
        Turn 1: 'laptop'              → CLARIFY (brand/type?)
        Turn 2: 'ASUS'                → CLARIFY (budget?)
        Turn 3: '3000 RON for gaming' → SEARCH
        """
        mocker.patch("services.gemini_service.classify_intent", return_value=_clarify_intent(
            "What brand or type of laptop?",
            collected={"category": "Laptop", "budget": None, "budget_max": None, "budget_currency": None, "preference": None},
        ))
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "laptop"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert sse_result(resp)["intent"] == "CLARIFY"

        mocker.patch("services.gemini_service.classify_intent", return_value=_clarify_intent(
            "What's your budget?",
            collected={"category": "Laptop", "budget": None, "budget_max": None, "budget_currency": None, "preference": "ASUS brand"},
        ))
        resp = client.post(
            CHAT_URL,
            json={"messages": [
                {"role": "user",      "content": "laptop"},
                {"role": "assistant", "content": "What brand or type?"},
                {"role": "user",      "content": "ASUS"},
            ]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        data = sse_result(resp)
        assert data["intent"] == "CLARIFY"
        assert data["collected_params"]["preference"] == "ASUS brand"

        laptops = [
            _product(1, "ASUS ROG Strix G15",  "https://emag.ro/rog",  2999, "RON", 90, 92, 85, 95),
            _product(2, "ASUS TUF Gaming F15", "https://altex.ro/tuf", 2499, "RON", 95, 85, 82, 94),
            _product(3, "ASUS VivoBook Pro",   "https://emag.ro/vivo", 1999, "RON", 100, 75, 78, 90),
        ]
        _mock_full_pipeline(
            mocker,
            _search_intent("Gaming Laptop", "3000 RON", 3000.0, "RON", "ASUS gaming 16GB RAM", ["emag.ro", "altex.ro"]),
            laptops,
        )
        resp = client.post(
            CHAT_URL,
            json={"messages": [
                {"role": "user",      "content": "laptop"},
                {"role": "assistant", "content": "What brand or type?"},
                {"role": "user",      "content": "ASUS"},
                {"role": "assistant", "content": "What's your budget?"},
                {"role": "user",      "content": "3000 RON, for gaming"},
            ]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        data = sse_result(resp)
        assert data["intent"] == "SEARCH"
        assert data["collected_params"]["budget_max"] == 3000.0

    def test_user_corrects_budget_in_later_message(self, client, mock_supabase, auth_token, mocker):
        """
        User first says 1000 RON then corrects to 2000 RON.
        The second turn should reflect the updated budget.
        """
        laptops = [
            _product(1, "ASUS VivoBook 16",  "https://emag.ro/vivo16", 1799, "RON", 88, 80, 82, 90),
            _product(2, "HP Pavilion 15",    "https://altex.ro/hp",    1299, "RON", 100, 72, 80, 85),
            _product(3, "Lenovo IdeaPad 5",  "https://emag.ro/len5",   1499, "RON",  92, 78, 80, 88),
        ]
        _mock_full_pipeline(
            mocker,
            _search_intent("Laptop", "under 2000 RON", 2000.0, "RON", "ASUS office use"),
            laptops,
        )
        resp = client.post(
            CHAT_URL,
            json={"messages": [
                {"role": "user",      "content": "ASUS laptop for office under 1000 RON"},
                {"role": "assistant", "content": "I'm having trouble finding ASUS laptops under 1000 RON — could you consider a higher budget?"},
                {"role": "user",      "content": "ok fine, 2000 RON"},
            ]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "SEARCH"
        assert data["collected_params"]["budget_max"] == 2000.0


# 7. Location read from Supabase

class TestLocationFromSupabase:

    def test_city_and_country_from_profile_passed_to_classify_intent(
        self, client, mock_supabase, auth_token, mocker
    ):
        """The user's profile city/country must reach classify_intent as positional args."""
        profile_resp = MagicMock()
        profile_resp.data = {"city": "Bucharest", "country": "Romania"}
        (
            mock_supabase.table.return_value
            .select.return_value
            .eq.return_value
            .single.return_value
            .execute.return_value
        ) = profile_resp

        classify_mock = mocker.patch("services.gemini_service.classify_intent", return_value={
            "intent": "CHAT",
            "reply": "What are you looking to buy?",
            "collected_params": {
                "category": None, "budget": None,
                "budget_max": None, "budget_currency": None, "preference": None,
            },
            "search_query": None,
            "local_domains": None,
        })

        client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        classify_mock.assert_called_once()
        args = classify_mock.call_args[0]  # positional: (messages, city, country)
        assert args[1] == "Bucharest", f"Expected city='Bucharest', got '{args[1]}'"
        assert args[2] == "Romania",   f"Expected country='Romania', got '{args[2]}'"

    def test_missing_profile_location_passes_empty_strings(
        self, client, mock_supabase, auth_token, mocker
    ):
        """When the profile has no city/country, classify_intent gets empty strings, not None."""
        classify_mock = mocker.patch("services.gemini_service.classify_intent", return_value={
            "intent": "CHAT",
            "reply": "What are you looking to buy?",
            "collected_params": {
                "category": None, "budget": None,
                "budget_max": None, "budget_currency": None, "preference": None,
            },
            "search_query": None,
            "local_domains": None,
        })

        client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        args = classify_mock.call_args[0]
        assert isinstance(args[1], str), f"city should be str, got {type(args[1])}"
        assert isinstance(args[2], str), f"country should be str, got {type(args[2])}"

    def test_location_also_reaches_score_and_rank(self, client, mock_supabase, auth_token, mocker):
        """For SEARCH intents, city/country from Supabase must also reach score_and_rank_products."""
        profile_resp = MagicMock()
        profile_resp.data = {"city": "Cluj-Napoca", "country": "Romania"}
        (
            mock_supabase.table.return_value
            .select.return_value
            .eq.return_value
            .single.return_value
            .execute.return_value
        ) = profile_resp

        mocker.patch("services.gemini_service.classify_intent", return_value=_search_intent(
            "Laptop", "under 2000 RON", 2000.0, "RON", "ASUS", ["emag.ro"]
        ))
        mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
        mocker.patch(
            "services.gemini_service.research_community_picks",
            return_value={"recommendations": [], "insight": None},
        )
        mocker.patch("routers.search.is_likely_product_url", return_value=True)
        mocker.patch("services.cache_service.lookup_cache", return_value=None)
        mocker.patch("services.tavily_service.search_products", return_value=[
            {"url": "https://emag.ro/asus", "title": "ASUS Laptop"}
        ])
        mocker.patch("services.scraper_service.scrape_urls", new=AsyncMock(return_value=[
            {"url": "https://emag.ro/asus", "markdown": _rich_markdown("ASUS Laptop", 1799, "RON")}
        ]))

        score_mock = mocker.patch("services.gemini_service.score_and_rank_products", return_value=[
            _product(1, "ASUS Laptop", "https://emag.ro/asus", 1799, "RON", 88, 82, 82, 90)
        ])
        mocker.patch("services.cache_service.save_cache")

        client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "ASUS laptop under 2000 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        score_mock.assert_called_once()
        call_kwargs = score_mock.call_args
        # score_and_rank_products(scraped, description, budget_max, budget_currency, city, country)
        assert call_kwargs[1].get("city") == "Cluj-Napoca" or call_kwargs[0][4] == "Cluj-Napoca"
        assert call_kwargs[1].get("country") == "Romania" or call_kwargs[0][5] == "Romania"
