"""
Unit tests for scraper_service:
  - _parse_html (extraction logic)
  - scrape_urls (curl_cffi priority-queue scheduler)
"""
import asyncio
from unittest.mock import patch

import services.scraper_service as svc


def run(coro):
    return asyncio.run(coro)


# Sample HTML fixture

MINIMAL_HTML = """
<html>
<head>
  <script type="application/ld+json">{"@type":"Product","name":"Widget","price":"99"}</script>
</head>
<body>
  <h1>Widget</h1>
  <p>A great product you should buy today. Available in multiple colors.</p>
</body>
</html>
"""


# _parse_html unit tests

class TestParseHtml:
    def setup_method(self):
        svc._policy_cache.clear()

    def test_returns_empty_markdown_for_empty_html(self):
        result = svc._parse_html("https://example.com/p", "")
        assert result["url"] == "https://example.com/p"
        assert result["markdown"] == ""
        assert result["jsonld"] == {}
        assert result["shipping_policy_url"] is None
        assert result["return_policy_text"] is None

    def test_extracts_markdown_from_valid_html(self):
        result = svc._parse_html("https://example.com/p", MINIMAL_HTML)
        assert isinstance(result["markdown"], str)
        assert len(result["markdown"]) > 0

    def test_extracts_jsonld_name_from_script_tag(self):
        result = svc._parse_html("https://example.com/p", MINIMAL_HTML)
        assert result["jsonld"].get("name") == "Widget"

    def test_result_has_all_required_keys(self):
        result = svc._parse_html("https://example.com/p", MINIMAL_HTML)
        assert {"url", "markdown", "jsonld", "shipping_policy_url", "return_policy_text"} <= result.keys()

    def test_url_preserved_in_result(self):
        url = "https://shop.test/item/42"
        result = svc._parse_html(url, MINIMAL_HTML)
        assert result["url"] == url

    def test_policy_cache_populated_for_domain(self):
        svc._parse_html("https://shop.example.com/product/1", MINIMAL_HTML)
        assert "shop.example.com" in svc._policy_cache

    def test_policy_cache_reused_on_second_call_same_domain(self):
        svc._parse_html("https://shop.example.com/product/1", MINIMAL_HTML)
        with patch.object(svc, "_find_policy_links") as mock_find:
            svc._parse_html("https://shop.example.com/product/2", MINIMAL_HTML)
            mock_find.assert_not_called()


# scrape_urls (Phase 2) and scrape_urls_deep (Phase 3)

def _make_resolved_future(result: dict) -> asyncio.Future:
    """Return an already-resolved Future in the *running* event loop."""
    loop = asyncio.get_running_loop()
    f: asyncio.Future = loop.create_future()
    f.set_result(result)
    return f


def _rich(url: str) -> dict:
    return {"url": url, "markdown": "Rich content.", "jsonld": {"name": "Item"}, "shipping_policy_url": None, "return_policy_text": None}


class TestScrapeUrls:
    """curl_cffi priority-queue scraper."""

    def setup_method(self):
        svc._policy_cache.clear()
        svc._url_cache._store.clear()

    def test_returns_scheduler_results_directly(self):
        urls = ["https://example.com/laptop-asus-vivobook-15-90NB0123"]

        async def _run():
            async def _submit(url, priority):
                return _make_resolved_future(_rich(url))

            with patch.object(svc._scheduler, "submit", side_effect=_submit):
                return await svc.scrape_urls(urls)

        results = run(_run())
        assert results[0]["markdown"] == "Rich content."

    def test_empty_url_list_returns_empty(self):
        assert run(svc.scrape_urls([])) == []
