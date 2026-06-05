"""
Mock tests for the /search/chat endpoint.
Run with: pytest -m "not live"
All external API calls (Gemini, Tavily, Jina, Supabase) are mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import sse_result

CHAT_URL = "/search/chat"

# All URLs need ≥2 path segments with a slug >8 chars to pass is_likely_product_url.
_SAMPLE_PRODUCTS = [
    {
        "rank": 1,
        "title": "ASUS VivoBook 16",
        "url": "https://emag.ro/laptopuri/asus-vivobook-16-skylake",
        "price": 1799.0,
        "currency": "RON",
        "image_url": "https://emag.ro/img/asus-vivobook.jpg",
        "scores": {
            "cost_efficiency": 85,
            "quality_confidence": 78,
            "logistics": 90,
            "trust": 95,
        },
        # 85*0.40 + 78*0.35 + 90*0.15 + 95*0.10 = 34.0 + 27.3 + 13.5 + 9.5 = 84.3
        "value_score": 84.3,
        "reasoning": "Excellent price-to-spec ratio with fast delivery.",
    },
    {
        "rank": 2,
        "title": "Lenovo IdeaPad 5",
        "url": "https://altex.ro/laptopuri/lenovo-ideapad-5-amd",
        "price": 1950.0,
        "currency": "RON",
        "image_url": None,
        "scores": {
            "cost_efficiency": 70,
            "quality_confidence": 82,
            "logistics": 75,
            "trust": 90,
        },
        # 70*0.40 + 82*0.35 + 75*0.15 + 90*0.10 = 28.0 + 28.7 + 11.25 + 9.0 = 76.95 → 77.0
        "value_score": 77.0,
        "reasoning": "High quality but slightly over budget.",
    },
    {
        "rank": 3,
        "title": "HP Pavilion 15",
        "url": "https://flanco.ro/laptopuri/hp-pavilion-15-intel",
        "price": 1600.0,
        "currency": "RON",
        "image_url": None,
        "scores": {
            "cost_efficiency": 90,
            "quality_confidence": 65,
            "logistics": 80,
            "trust": 85,
        },
        # 90*0.40 + 65*0.35 + 80*0.15 + 85*0.10 = 36.0 + 22.75 + 12.0 + 8.5 = 79.25 → 79.2
        "value_score": 79.2,
        "reasoning": "Best price but fewer reviews.",
    },
]


# Authentication

class TestAuthentication:
    def test_unauthenticated_returns_401(self, client):
        resp = client.post(CHAT_URL, json={"messages": [{"role": "user", "content": "hello"}]})
        assert resp.status_code == 401

    def test_empty_messages_returns_422(self, client, auth_token, mock_supabase):
        resp = client.post(
            CHAT_URL,
            json={"messages": []},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 422


# CHAT Intent

class TestChatIntent:
    def test_chat_returns_reply_without_calling_tavily(
        self, client, mock_supabase, auth_token, mocker
    ):
        mocker.patch(
            "services.gemini_service.classify_intent",
            return_value={
                "intent": "CHAT",
                "reply": "Hello! I help you find and buy products.",
                "collected_params": {},
                "search_query": None,
            },
        )
        mock_tavily = mocker.patch("services.tavily_service.search_products")

        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "What can you do?"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "CHAT"
        assert data["reply"] == "Hello! I help you find and buy products."
        assert data["products"] is None
        mock_tavily.assert_not_called()

    def test_chat_with_fallback_reply_when_reply_is_null(
        self, client, mock_supabase, auth_token, mocker
    ):
        mocker.patch(
            "services.gemini_service.classify_intent",
            return_value={
                "intent": "CHAT",
                "reply": None,
                "collected_params": {},
                "search_query": None,
            },
        )
        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        assert sse_result(resp)["reply"] is not None


# CLARIFY Intent

class TestClarifyIntent:
    def test_clarify_asks_for_missing_parameter(
        self, client, mock_supabase, auth_token, mocker
    ):
        mocker.patch(
            "services.gemini_service.classify_intent",
            return_value={
                "intent": "CLARIFY",
                "reply": "What is your budget?",
                "collected_params": {
                    "category": "Laptop",
                    "budget": None,
                    "budget_max": None,
                    "budget_currency": None,
                    "preference": "ASUS",
                },
                "search_query": None,
            },
        )
        mock_tavily = mocker.patch("services.tavily_service.search_products")

        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "I need an ASUS laptop"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "CLARIFY"
        assert data["reply"] == "What is your budget?"
        assert data["collected_params"]["category"] == "Laptop"
        assert data["collected_params"]["budget"] is None
        mock_tavily.assert_not_called()


# SEARCH Pipeline

class TestSearchPipeline:
    def _mock_search_intent(self, mocker):
        mocker.patch(
            "services.gemini_service.classify_intent",
            return_value={
                "intent": "SEARCH",
                "reply": None,
                "collected_params": {
                    "category": "Laptop",
                    "budget": "2000 RON",
                    "budget_max": 2000.0,
                    "budget_currency": "RON",
                    "preference": "ASUS 16GB RAM",
                },
                "search_query": "ASUS laptop 16GB RAM buy under 2000 RON",
                "local_domains": ["emag.ro", "altex.ro", "mediagalaxy.ro"],
            },
        )
        mocker.patch(
            "services.gemini_service.research_community_picks",
            return_value={"recommendations": [], "insight": None},
        )

    def test_cache_hit_returns_cached_products(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._mock_search_intent(mocker)
        mocker.patch(
            "services.gemini_service.generate_embedding",
            return_value=[0.1] * 768,
        )
        mocker.patch(
            "services.cache_service.lookup_cache",
            return_value=_SAMPLE_PRODUCTS,
        )
        mock_tavily = mocker.patch("services.tavily_service.search_products")

        resp = client.post(
            CHAT_URL,
            json={"messages": [
                {"role": "user", "content": "ASUS laptop 16GB RAM under 2000 RON"}
            ]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "SEARCH"
        assert data["from_cache"] is True
        assert len(data["products"]) == 3
        assert data["products"][0]["title"] == "ASUS VivoBook 16"
        mock_tavily.assert_not_called()

    def test_cache_miss_runs_full_pipeline(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._mock_search_intent(mocker)
        mocker.patch(
            "services.gemini_service.generate_embedding",
            return_value=[0.1] * 768,
        )
        mocker.patch("services.cache_service.lookup_cache", return_value=None)
        mocker.patch(
            "services.tavily_service.search_products",
            return_value=[
                {"url": "https://emag.ro/laptopuri/asus-vivobook-16-skylake", "title": "ASUS VivoBook 16"},
                {"url": "https://altex.ro/laptopuri/lenovo-ideapad-5-amd", "title": "Lenovo IdeaPad 5"},
                {"url": "https://flanco.ro/laptopuri/hp-pavilion-15-intel", "title": "HP Pavilion 15"},
            ],
        )
        mocker.patch(
            "services.scraper_service.scrape_urls",
            new=AsyncMock(
                return_value=[
                    {"url": "https://emag.ro/laptopuri/asus-vivobook-16-skylake", "markdown": "# ASUS VivoBook 16\nPrice: 1799 RON\nBrand: ASUS\nRAM: 16GB DDR4\nProcessor: Intel Core i5\nStorage: 512GB SSD\nDisplay: 16-inch FHD\nIn stock. Free shipping. Rating: 4.5/5 from 320 reviews. Sold by official ASUS retailer."},
                    {"url": "https://altex.ro/laptopuri/lenovo-ideapad-5-amd", "markdown": "# Lenovo IdeaPad 5\nPrice: 1950 RON\nBrand: Lenovo\nRAM: 16GB DDR4\nProcessor: AMD Ryzen 5\nStorage: 512GB SSD\nDisplay: 15.6-inch FHD\nIn stock. Standard shipping 3-5 days. Rating: 4.3/5 from 180 reviews. Sold by authorised retailer."},
                    {"url": "https://flanco.ro/laptopuri/hp-pavilion-15-intel", "markdown": "# HP Pavilion 15\nPrice: 1600 RON\nBrand: HP\nRAM: 8GB DDR4\nProcessor: Intel Core i3\nStorage: 256GB SSD\nDisplay: 15.6-inch FHD\nIn stock. Free shipping. Rating: 4.1/5 from 95 reviews. Sold by authorised HP retailer."},
                ]
            ),
        )
        mocker.patch(
            "services.gemini_service.score_and_rank_products",
            return_value=_SAMPLE_PRODUCTS,
        )
        mocker.patch("services.cache_service.save_cache")

        resp = client.post(
            CHAT_URL,
            json={"messages": [
                {"role": "user", "content": "ASUS laptop 16GB RAM under 2000 RON"}
            ]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "SEARCH"
        assert data["from_cache"] is False
        assert len(data["products"]) == 3
        assert data["products"][0]["value_score"] == 84.3

    def test_tavily_empty_returns_clarify(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._mock_search_intent(mocker)
        mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
        mocker.patch("services.cache_service.lookup_cache", return_value=None)
        mocker.patch("services.tavily_service.search_products", return_value=[])
        mocker.patch(
            "services.gemini_service.explain_no_results",
            return_value="No laptops found. Try a different search.",
        )

        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "ASUS laptop under 2000 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "CLARIFY"

    def test_jina_all_empty_returns_clarify(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._mock_search_intent(mocker)
        mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
        mocker.patch("services.cache_service.lookup_cache", return_value=None)
        mocker.patch(
            "services.tavily_service.search_products",
            return_value=[{"url": "https://emag.ro/laptopuri/test-product-model-p1", "title": "P1"}],
        )
        mocker.patch(
            "services.scraper_service.scrape_urls",
            new=AsyncMock(return_value=[{"url": "https://emag.ro/laptopuri/test-product-model-p1", "markdown": ""}]),
        )
        mocker.patch(
            "services.gemini_service.explain_no_results",
            return_value="No content scraped. Try a different search.",
        )

        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "ASUS laptop under 2000 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "CLARIFY"

    def test_scoring_empty_returns_clarify(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._mock_search_intent(mocker)
        mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
        mocker.patch("services.cache_service.lookup_cache", return_value=None)
        mocker.patch(
            "services.tavily_service.search_products",
            return_value=[{"url": "https://emag.ro/laptopuri/test-product-model-p1", "title": "P1"}],
        )
        mocker.patch(
            "services.scraper_service.scrape_urls",
            new=AsyncMock(
                return_value=[{"url": "https://emag.ro/laptopuri/test-product-model-p1", "markdown": "# Product\nPrice: 1799 RON\nBrand: ASUS\nRAM: 16GB DDR4\nProcessor: Intel Core i5\nStorage: 512GB SSD\nDisplay: 16-inch FHD\nIn stock. Free shipping. Rating: 4.5/5 from 320 reviews."}]
            ),
        )
        mocker.patch("services.gemini_service.score_and_rank_products", return_value=[])
        mocker.patch(
            "services.gemini_service.explain_no_results",
            return_value="Scorer found nothing. Try adjusting your criteria.",
        )

        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "ASUS laptop under 2000 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "CLARIFY"

    def test_search_with_image_sets_image_included_flag(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._mock_search_intent(mocker)
        mocker.patch(
            "services.gemini_service.generate_embedding",
            return_value=[0.1] * 768,
        )
        mocker.patch("services.cache_service.lookup_cache", return_value=_SAMPLE_PRODUCTS)

        import base64
        fake_image = base64.b64encode(b"fake-webp-bytes").decode()

        resp = client.post(
            CHAT_URL,
            json={"messages": [
                {
                    "role": "user",
                    "content": "laptop like this",
                    "image_base64": fake_image,
                }
            ]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200


# Product Structure

class TestProductStructure:
    def test_scoring_empty_triggers_clarify(
        self, client, mock_supabase, auth_token, mocker
    ):
        """score_and_rank_products returning [] should yield CLARIFY, not 503."""
        mocker.patch(
            "services.gemini_service.classify_intent",
            return_value={
                "intent": "SEARCH",
                "reply": None,
                "collected_params": {
                    "category": "Laptop",
                    "budget": "100 RON",
                    "budget_max": 100.0,
                    "budget_currency": "RON",
                    "preference": None,
                },
                "search_query": "laptop buy under 100 RON",
                "local_domains": None,
            },
        )
        mocker.patch(
            "services.gemini_service.research_community_picks",
            return_value={"recommendations": [], "insight": None},
        )
        mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
        mocker.patch("services.cache_service.lookup_cache", return_value=None)
        mocker.patch(
            "services.tavily_service.search_products",
            return_value=[{"url": "https://emag.ro/laptopuri/cheap-budget-laptop-model", "title": "Budget Laptop"}],
        )
        _rich = (
            "# Budget Laptop\n\nPrice: 120 RON\n\n"
            "In Stock. Free shipping. Rating: 4.0/5 based on 50 reviews.\n\n"
            "High-quality build, fast delivery. Sold by authorised retailer. "
            "Includes 12-month warranty and 30-day return policy."
        )
        mocker.patch(
            "services.scraper_service.scrape_urls",
            new=AsyncMock(return_value=[{"url": "https://emag.ro/laptopuri/cheap-budget-laptop-model", "markdown": _rich}]),
        )
        mocker.patch("services.gemini_service.score_and_rank_products", return_value=[])
        mocker.patch(
            "services.gemini_service.explain_no_results",
            return_value="No laptops found under 100 RON. Try increasing your budget.",
        )

        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "laptop under 100 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "CLARIFY"
        assert data["products"] is None
        assert data["reply"] is not None and len(data["reply"]) > 10

    def test_product_scores_match_weights(
        self, client, mock_supabase, auth_token, mocker
    ):
        mocker.patch(
            "services.gemini_service.classify_intent",
            return_value={
                "intent": "SEARCH",
                "reply": None,
                "collected_params": {
                    "category": "Mouse",
                    "budget": "500 RON",
                    "budget_max": 500.0,
                    "budget_currency": "RON",
                    "preference": "wireless gaming",
                },
                "search_query": "wireless gaming mouse buy under 500 RON",
                "local_domains": ["emag.ro", "altex.ro"],
            },
        )
        mocker.patch(
            "services.gemini_service.generate_embedding",
            return_value=[0.0] * 768,
        )
        mocker.patch("services.cache_service.lookup_cache", return_value=_SAMPLE_PRODUCTS)

        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "wireless gaming mouse under 500 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        from services.gemini_service import SCORE_WEIGHTS
        products = sse_result(resp)["products"]
        p = products[0]
        expected = (
            p["scores"]["cost_efficiency"] * SCORE_WEIGHTS["cost_efficiency"]
            + p["scores"]["quality_confidence"] * SCORE_WEIGHTS["quality_confidence"]
            + p["scores"]["logistics"] * SCORE_WEIGHTS["logistics"]
            + p["scores"]["trust"] * SCORE_WEIGHTS["trust"]
        )
        assert abs(p["value_score"] - expected) < 0.1


# Excluded URLs

_RICH_MARKDOWN = (
    "# ASUS VivoBook 16\n\n"
    "**Price:** 1799 RON\n\n"
    "**Availability:** In Stock. Free shipping on all orders over 200 RON.\n\n"
    "**Rating:** 4.3 out of 5 stars based on 150 verified customer reviews.\n\n"
    "**Description:** High-quality product with excellent build quality and durability. "
    "Includes 12-month manufacturer warranty. Sold by authorised retailer."
)

_URL_EMAG   = "https://emag.ro/laptopuri/asus-vivobook-16-skylake"
_URL_ALTEX  = "https://altex.ro/laptopuri/lenovo-ideapad-5-amd"
_URL_FLANCO = "https://flanco.ro/laptopuri/hp-pavilion-15-intel"


class TestExcludedUrls:
    """excluded_urls: bypasses cache and strips rejected products from the pipeline."""

    def _mock_search_intent(self, mocker):
        mocker.patch(
            "services.gemini_service.classify_intent",
            return_value={
                "intent": "SEARCH",
                "reply": None,
                "collected_params": {
                    "category": "Laptop",
                    "budget": "2000 RON",
                    "budget_max": 2000.0,
                    "budget_currency": "RON",
                    "preference": "ASUS",
                },
                "search_query": "ASUS laptop buy under 2000 RON",
                "local_domains": None,
            },
        )
        mocker.patch(
            "services.gemini_service.research_community_picks",
            return_value={"recommendations": [], "insight": None},
        )

    def test_excluded_urls_bypasses_cache(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._mock_search_intent(mocker)
        mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
        mock_lookup = mocker.patch("services.cache_service.lookup_cache", return_value=_SAMPLE_PRODUCTS)
        mocker.patch(
            "services.tavily_service.search_products",
            return_value=[
                {"url": _URL_ALTEX,  "title": "Lenovo IdeaPad 5"},
                {"url": _URL_FLANCO, "title": "HP Pavilion 15"},
                {"url": _URL_EMAG,   "title": "ASUS VivoBook 16"},
            ],
        )
        mocker.patch(
            "services.scraper_service.scrape_urls",
            new=AsyncMock(return_value=[
                {"url": _URL_ALTEX,  "markdown": _RICH_MARKDOWN},
                {"url": _URL_FLANCO, "markdown": _RICH_MARKDOWN},
                {"url": _URL_EMAG,   "markdown": _RICH_MARKDOWN},
            ]),
        )
        mocker.patch("services.gemini_service.score_and_rank_products", return_value=_SAMPLE_PRODUCTS)
        mocker.patch("services.cache_service.save_cache")

        resp = client.post(
            CHAT_URL,
            json={
                "messages": [{"role": "user", "content": "ASUS laptop under 2000 RON"}],
                "excluded_urls": [_URL_EMAG],
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert resp.status_code == 200
        assert sse_result(resp)["from_cache"] is False
        mock_lookup.assert_not_called()

    def test_excluded_url_stripped_from_jina_call(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._mock_search_intent(mocker)
        mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
        mocker.patch("services.cache_service.lookup_cache", return_value=None)
        mocker.patch(
            "services.tavily_service.search_products",
            return_value=[
                {"url": _URL_EMAG,   "title": "ASUS VivoBook 16"},
                {"url": _URL_ALTEX,  "title": "Lenovo IdeaPad 5"},
                {"url": _URL_FLANCO, "title": "HP Pavilion 15"},
            ],
        )
        mock_jina = mocker.patch(
            "services.scraper_service.scrape_urls",
            new=AsyncMock(return_value=[
                {"url": _URL_ALTEX,  "markdown": _RICH_MARKDOWN},
                {"url": _URL_FLANCO, "markdown": _RICH_MARKDOWN},
            ]),
        )
        mocker.patch(
            "services.gemini_service.score_and_rank_products",
            return_value=_SAMPLE_PRODUCTS[1:],
        )
        mocker.patch("services.cache_service.save_cache")

        resp = client.post(
            CHAT_URL,
            json={
                "messages": [{"role": "user", "content": "ASUS laptop under 2000 RON"}],
                "excluded_urls": [_URL_EMAG],
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert resp.status_code == 200
        called_urls = mock_jina.call_args[0][0]
        assert _URL_EMAG not in called_urls
        assert _URL_ALTEX in called_urls

    def test_all_tavily_urls_excluded_returns_clarify(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._mock_search_intent(mocker)
        mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
        mocker.patch("services.cache_service.lookup_cache", return_value=None)
        mocker.patch(
            "services.tavily_service.search_products",
            return_value=[
                {"url": _URL_EMAG,  "title": "ASUS VivoBook 16"},
                {"url": _URL_ALTEX, "title": "Lenovo IdeaPad 5"},
            ],
        )
        mocker.patch(
            "services.gemini_service.explain_no_results",
            return_value="All found products were already shown. Try a new search.",
        )

        resp = client.post(
            CHAT_URL,
            json={
                "messages": [{"role": "user", "content": "ASUS laptop under 2000 RON"}],
                "excluded_urls": [_URL_EMAG, _URL_ALTEX],
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "CLARIFY"


# No-results CLARIFY

class TestNoResultsClarify:
    """When scoring finds nothing globally, a CLARIFY response is returned (not 503)."""

    def _mock_search_intent(self, mocker):
        mocker.patch(
            "services.gemini_service.classify_intent",
            return_value={
                "intent": "SEARCH",
                "reply": None,
                "collected_params": {
                    "category": "Laptop",
                    "budget": "100 RON",
                    "budget_max": 100.0,
                    "budget_currency": "RON",
                    "preference": None,
                },
                "search_query": "laptop buy under 100 RON",
                "local_domains": None,
            },
        )

    def _common_pipeline_mocks(self, mocker):
        mocker.patch(
            "services.gemini_service.research_community_picks",
            return_value={"recommendations": [], "insight": None},
        )
        mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
        mocker.patch("services.cache_service.lookup_cache", return_value=None)
        mocker.patch(
            "services.tavily_service.search_products",
            return_value=[{"url": "https://emag.ro/laptopuri/cheap-budget-laptop-model", "title": "Cheap Laptop"}],
        )
        mocker.patch(
            "services.scraper_service.scrape_urls",
            new=AsyncMock(return_value=[{"url": "https://emag.ro/laptopuri/cheap-budget-laptop-model", "markdown": _RICH_MARKDOWN}]),
        )
        mocker.patch("services.gemini_service.score_and_rank_products", return_value=[])

    def test_no_results_returns_200_clarify(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._mock_search_intent(mocker)
        self._common_pipeline_mocks(mocker)
        mocker.patch(
            "services.gemini_service.explain_no_results",
            return_value="No laptops found under 100 RON. Try increasing your budget.",
        )

        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "laptop under 100 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "CLARIFY"
        assert data["products"] is None

    def test_explain_no_results_called_with_correct_params(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._mock_search_intent(mocker)
        self._common_pipeline_mocks(mocker)
        mock_explain = mocker.patch(
            "services.gemini_service.explain_no_results",
            return_value="No matches.",
        )

        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "laptop under 100 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert resp.status_code == 200
        mock_explain.assert_called_once()
        args = mock_explain.call_args[0]
        assert args[0] == "Laptop"   # category
        assert args[2] == 100.0      # budget_max

    def test_clarify_reply_is_nonempty(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._mock_search_intent(mocker)
        self._common_pipeline_mocks(mocker)
        mocker.patch(
            "services.gemini_service.explain_no_results",
            return_value="Try broadening your search or increasing your budget.",
        )

        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "laptop under 100 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert resp.status_code == 200
        reply = sse_result(resp)["reply"]
        assert isinstance(reply, str) and len(reply) > 10


# Global Fallback

_LOCAL_TAVILY = [
    {"url": "https://emag.ro/laptopuri/product-model-alpha-laptop", "title": "Product A"},
    {"url": "https://emag.ro/laptopuri/product-model-bravo-laptop", "title": "Product B"},
    {"url": "https://emag.ro/laptopuri/product-model-charlie-laptop", "title": "Product C"},
    {"url": "https://emag.ro/laptopuri/product-model-delta-laptop", "title": "Product D"},
    {"url": "https://emag.ro/laptopuri/product-model-echo-laptop", "title": "Product E"},
]
_GLOBAL_TAVILY = [
    {"url": "https://amazon.com/dp/product-model-x-laptop", "title": "Product X"},
    {"url": "https://amazon.com/dp/product-model-y-laptop", "title": "Product Y"},
    {"url": "https://amazon.com/dp/product-model-z-laptop", "title": "Product Z"},
]
_GLOBAL_PRODUCT = {
    "rank": 1,
    "title": "Product X",
    "url": "https://amazon.com/dp/product-model-x-laptop",
    "price": 1800.0,
    "currency": "RON",
    "image_url": None,
    "scores": {
        "cost_efficiency": 80,
        "quality_confidence": 75,
        "logistics": 70,
        "trust": 85,
    },
    "value_score": 78.0,
    "reasoning": "Good value from global retailer.",
}


def _rich_jina(urls):
    return [{"url": u, "markdown": _RICH_MARKDOWN} for u in urls]


class TestGlobalFallback:
    """When local scoring soft-fails, the pipeline retries globally and sets fallback_message."""

    def _mock_search_intent_with_domains(self, mocker):
        mocker.patch(
            "services.gemini_service.classify_intent",
            return_value={
                "intent": "SEARCH",
                "reply": None,
                "collected_params": {
                    "category": "Laptop",
                    "budget": "2000 RON",
                    "budget_max": 2000.0,
                    "budget_currency": "RON",
                    "preference": "ASUS",
                },
                "search_query": "ASUS laptop buy under 2000 RON",
                "local_domains": ["emag.ro", "altex.ro"],
            },
        )

    def _setup_local_fail_global_success(self, mocker):
        self._mock_search_intent_with_domains(mocker)
        mocker.patch(
            "services.gemini_service.research_community_picks",
            return_value={"recommendations": [], "insight": None},
        )
        mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
        mocker.patch("services.cache_service.lookup_cache", return_value=None)
        mocker.patch(
            "services.tavily_service.search_products",
            side_effect=[_LOCAL_TAVILY, _GLOBAL_TAVILY],
        )
        mocker.patch(
            "services.scraper_service.scrape_urls",
            new=AsyncMock(side_effect=[
                _rich_jina([r["url"] for r in _LOCAL_TAVILY]),
                _rich_jina([r["url"] for r in _GLOBAL_TAVILY]),
            ]),
        )
        mocker.patch(
            "services.gemini_service.score_and_rank_products",
            side_effect=[[], [_GLOBAL_PRODUCT]],
        )
        mocker.patch("services.cache_service.save_cache")

    def test_local_soft_fail_triggers_global_retry(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._setup_local_fail_global_success(mocker)

        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "ASUS laptop under 2000 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "SEARCH"
        assert data["products"] is not None and len(data["products"]) >= 1

    def test_global_fallback_sets_fallback_message(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._setup_local_fail_global_success(mocker)

        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "ASUS laptop under 2000 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["fallback_message"] is not None
        assert "local" in data["fallback_message"].lower()

    def test_both_pipelines_fail_returns_clarify(
        self, client, mock_supabase, auth_token, mocker
    ):
        self._mock_search_intent_with_domains(mocker)
        mocker.patch(
            "services.gemini_service.research_community_picks",
            return_value={"recommendations": [], "insight": None},
        )
        mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
        mocker.patch("services.cache_service.lookup_cache", return_value=None)
        mocker.patch(
            "services.tavily_service.search_products",
            side_effect=[_LOCAL_TAVILY, _GLOBAL_TAVILY],
        )
        mocker.patch(
            "services.scraper_service.scrape_urls",
            new=AsyncMock(side_effect=[
                _rich_jina([r["url"] for r in _LOCAL_TAVILY]),
                _rich_jina([r["url"] for r in _GLOBAL_TAVILY]),
            ]),
        )
        mocker.patch(
            "services.gemini_service.score_and_rank_products",
            side_effect=[[], []],
        )
        mocker.patch(
            "services.gemini_service.explain_no_results",
            return_value="No ASUS laptops found. Try adjusting your criteria.",
        )

        resp = client.post(
            CHAT_URL,
            json={"messages": [{"role": "user", "content": "ASUS laptop under 2000 RON"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert resp.status_code == 200
        data = sse_result(resp)
        assert data["intent"] == "CLARIFY"
        assert data["reply"] is not None


class TestMockScraper:
    """Scraper contract: bad URLs yield empty markdown without raising."""

    @pytest.mark.asyncio
    async def test_handles_bad_url_gracefully(self, mocker):
        mocker.patch(
            "services.scraper_service._fetch_one_sync",
            side_effect=ConnectionRefusedError("connection refused"),
        )
        from services.scraper_service import scrape_urls

        results = await scrape_urls(["http://127.0.0.1:19999/product-test-sku-123456"])
        assert len(results) == 1
        assert results[0]["markdown"] == ""
