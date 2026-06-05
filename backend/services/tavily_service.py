import logging

from tavily import TavilyClient

from core.config import settings

logger = logging.getLogger(__name__)

_client = TavilyClient(api_key=settings.tavily_api_key)

# Global e-commerce whitelist — used when Gemini returns no local_domains.
# Prevents Tavily from surfacing Reddit threads, Wikipedia, review blogs, or
# news articles when the user is asking for a product to buy.
_GLOBAL_ECOMMERCE_DOMAINS: list[str] = [
    # ── North America ────────────────────────────────────────────────────────
    "amazon.com", "walmart.com", "target.com", "bestbuy.com", "newegg.com",
    "bhphotovideo.com", "adorama.com", "costco.com", "macys.com",
    "nordstrom.com", "apple.com", "nike.com", "adidas.com",
    # ── UK ───────────────────────────────────────────────────────────────────
    "amazon.co.uk", "currys.co.uk", "argos.co.uk", "johnlewis.com",
    "asos.com", "ebay.co.uk",
    # ── Germany / Austria ────────────────────────────────────────────────────
    "amazon.de", "mediamarkt.de", "saturn.de", "otto.de", "zalando.de",
    "alternate.de", "notebooksbilliger.de", "cyberport.de", "ebay.de",
    # ── France ───────────────────────────────────────────────────────────────
    "amazon.fr", "fnac.fr", "cdiscount.com", "darty.com", "boulanger.com",
    "ebay.fr", "zalando.fr",
    # ── Italy ────────────────────────────────────────────────────────────────
    "amazon.it", "mediaworld.it", "unieuro.it", "ebay.it",
    # ── Spain ────────────────────────────────────────────────────────────────
    "amazon.es", "pccomponentes.com", "mediamarkt.es", "ebay.es",
    # ── Poland ───────────────────────────────────────────────────────────────
    "amazon.pl", "allegro.pl", "morele.net", "x-kom.pl", "mediaexpert.pl",
    # ── Netherlands / Belgium ────────────────────────────────────────────────
    "amazon.nl", "coolblue.nl", "bol.com", "mediamarkt.nl",
    # ── Romania ──────────────────────────────────────────────────────────────
    "emag.ro", "altex.ro", "pcgarage.ro", "flanco.ro", "cel.ro",
    "elefant.ro", "dedeman.ro",
    # ── Czech / Slovakia ─────────────────────────────────────────────────────
    "alza.cz", "alza.sk",
    # ── Nordics ──────────────────────────────────────────────────────────────
    "amazon.se", "webhallen.com", "komplett.no", "power.fi",
    # ── Global / multi-region ────────────────────────────────────────────────
    "amazon.ca", "amazon.com.au", "amazon.co.jp", "amazon.in",
    "ebay.com", "zalando.com", "hm.com", "uniqlo.com", "decathlon.com",
    "aliexpress.com", "jd.com",
]


def search_products(
    query: str,
    max_results: int = 10,
    include_domains: list[str] | None = None,
) -> list[dict]:
    """
    Find up to max_results product listing URLs via Tavily.
    Returns [{"url": "...", "title": "...", "content": "..."}].

    include_domains — explicit retailer list from Gemini (e.g. ["emag.ro"]).
    When None, falls back to _GLOBAL_ECOMMERCE_DOMAINS so Tavily never returns
    blog posts, Reddit threads, or Wikipedia articles for a product search.
    Runs synchronously — call via run_in_threadpool from async handlers.
    """
    try:
        domains = include_domains if include_domains is not None else _GLOBAL_ECOMMERCE_DOMAINS
        result = _client.search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
            include_answer=False,
            include_domains=domains,
        )
        return result.get("results", [])
    except Exception as exc:
        logger.error("Tavily search failed: %s", exc)
        return []
