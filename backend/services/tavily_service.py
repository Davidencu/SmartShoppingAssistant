import logging

from tavily import TavilyClient

from core.config import settings

logger = logging.getLogger(__name__)

_client = TavilyClient(api_key=settings.tavily_api_key)

# Global e-commerce whitelist — used when Gemini returns no local_domains.
# Prevents Tavily from surfacing Reddit threads, Wikipedia, review blogs, or
# news articles when the user is asking for a product to buy.
_GLOBAL_ECOMMERCE_DOMAINS: list[str] = [
    # ── North America niche/specialty ────────────────────────────────────────
    "bhphotovideo.com", "adorama.com", "newegg.com", "overstock.com",
    "wayfair.com", "rei.com", "chewy.com", "sweetwater.com", "microcenter.com",
    # ── North America mainstream ──────────────────────────────────────────────
    "amazon.com", "walmart.com", "target.com", "bestbuy.com",
    "costco.com", "macys.com", "nordstrom.com", "apple.com", "nike.com", "adidas.com",
    # ── UK niche ─────────────────────────────────────────────────────────────
    "scan.co.uk", "ebuyer.com", "overclockers.co.uk", "laptopsdirect.co.uk",
    # ── UK mainstream ─────────────────────────────────────────────────────────
    "amazon.co.uk", "currys.co.uk", "argos.co.uk", "johnlewis.com", "asos.com",
    # ── Germany niche ────────────────────────────────────────────────────────
    "alternate.de", "notebooksbilliger.de", "cyberport.de", "mindfactory.de",
    "reichelt.de", "euronics.de",
    # ── Germany mainstream ────────────────────────────────────────────────────
    "amazon.de", "mediamarkt.de", "saturn.de", "otto.de", "zalando.de",
    # ── France niche ─────────────────────────────────────────────────────────
    "fnac.fr", "ldlc.com", "topachat.com", "rueducommerce.fr",
    # ── France mainstream ─────────────────────────────────────────────────────
    "amazon.fr", "cdiscount.com", "darty.com", "boulanger.com", "zalando.fr",
    # ── Italy ────────────────────────────────────────────────────────────────
    "amazon.it", "euronics.it", "trony.it", "mediaworld.it", "unieuro.it",
    # ── Spain ────────────────────────────────────────────────────────────────
    "pccomponentes.com", "fnac.es", "amazon.es", "mediamarkt.es",
    # ── Poland niche ─────────────────────────────────────────────────────────
    "morele.net", "x-kom.pl", "mediaexpert.pl",
    # ── Poland mainstream ─────────────────────────────────────────────────────
    "amazon.pl", "allegro.pl",
    # ── Netherlands / Belgium ────────────────────────────────────────────────
    "amazon.nl", "coolblue.nl", "bol.com", "mediamarkt.nl",
    # ── Romania niche ────────────────────────────────────────────────────────
    "pcgarage.ro", "evomag.ro", "decathlon.ro", "notino.ro",
    "intersport.ro", "answear.ro", "libris.ro", "zooplus.ro",
    # ── Romania mainstream ────────────────────────────────────────────────────
    "emag.ro", "altex.ro", "flanco.ro", "cel.ro",
    # ── Czech / Slovakia ─────────────────────────────────────────────────────
    "alza.cz", "czc.cz", "alza.sk", "sportisimo.cz", "notino.cz", "mall.cz",
    # ── Nordics niche ────────────────────────────────────────────────────────
    "webhallen.com", "komplett.no", "komplett.se", "digitec.ch", "galaxus.ch",
    "inet.se", "proshop.dk", "proshop.no",
    # ── Nordics mainstream ────────────────────────────────────────────────────
    "amazon.se", "power.fi",
    # ── Benelux niche ────────────────────────────────────────────────────────
    "vandenborre.be", "krefel.be", "wehkamp.nl", "bcc.nl", "megekko.nl", "fonq.nl",
    # ── UK niche (cycling / sports / home) ───────────────────────────────────
    "halfords.com", "ao.com", "sportsdirect.com", "dunelm.com", "screwfix.com",
    # ── DE niche (cycling / culture / home) ──────────────────────────────────
    "galaxus.de", "thalia.de", "rose-bikes.com", "fahrrad.de", "home24.de",
    # ── FR niche (DIY / culture / cycling) ───────────────────────────────────
    "manomano.fr", "cultura.com", "alltricks.fr", "materiel.net",
    # ── ES / IT / PL niche ───────────────────────────────────────────────────
    "sprinter.es", "empik.com", "ibs.it", "eprice.it",
    # ── AU / CA / IN / BR niche ──────────────────────────────────────────────
    "rebel.com.au", "catch.com.au", "memoryexpress.com", "mec.ca",
    "myntra.com", "nykaa.com", "kabum.com.br",
    # ── Global niche ─────────────────────────────────────────────────────────
    "decathlon.com", "zappos.com", "reverb.com", "backcountry.com",
    "wiggle.com", "chainreactioncycles.com", "bike24.com", "probikekit.com",
    "thomann.de", "iherb.com", "myprotein.com", "notino.com",
    "tradeinn.com", "manomano.com", "aboutyou.com", "zooplus.com",
    # ── Shopify DTC brands ────────────────────────────────────────────────────
    "gymshark.com", "allbirds.com", "skims.com", "fashionnova.com",
    "kyliecosmetics.com", "colourpop.com", "fentybeauty.com",
    "brooklinen.com", "ruggable.com", "casetify.com", "dbrand.com",
    "cotopaxi.com", "vuoriclothing.com", "nomadgoods.com",
    # ── Global mainstream ─────────────────────────────────────────────────────
    "amazon.ca", "amazon.com.au", "amazon.co.jp", "amazon.in",
    "ebay.com", "zalando.com", "hm.com", "uniqlo.com", "aliexpress.com",
]


def search_pdps_for_domain(
    query: str,
    domain: str,
    max_results: int = 5,
) -> list[dict]:
    """
    Targeted Tavily search to find product detail pages on a single mainstream domain.

    Uses the site: operator in the query string so Tavily's index returns only pages
    from that domain — the URLs are guaranteed to physically exist (no hallucination).
    Called by Lane B before passing URLs to Gemini for extraction-only reading.

    Runs synchronously — call via run_in_threadpool from async handlers.
    """
    site_query = f"site:{domain} {query}"
    try:
        result = _client.search(
            query=site_query,
            search_depth="advanced",
            max_results=max_results,
            include_answer=False,
            include_domains=[domain],
        )
        return result.get("results", [])
    except Exception as exc:
        logger.error("[TAVILY] PDP search failed for %s: %s", domain, exc)
        return []


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
            search_depth="basic",
            max_results=max_results,
            include_answer=False,
            include_domains=domains,
        )
        return result.get("results", [])
    except Exception as exc:
        logger.error("Tavily search failed: %s", exc)
        return []
