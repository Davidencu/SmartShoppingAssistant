"""
Retailers service — single source of truth for:
  • Which domains are active per country (used by Tavily for targeted searches)
  • Which domains require a residential proxy (replaces hardcoded _HARD_DOMAINS)
  • Country name → ISO 3166-1 alpha-2 code mapping

Data lives in the `supported_retailers` Supabase table and is cached in-process
with a 5-minute TTL so every request isn't a DB round-trip.
"""
import logging
import re
import threading
import time

logger = logging.getLogger(__name__)

# ── In-memory TTL cache ───────────────────────────────────────────────────────
_LOCK = threading.Lock()
_domains_by_country: dict[str, list[str]] = {}
_proxy_domains: frozenset[str] = frozenset()
_last_refresh: float = 0.0
_TTL = 300.0  # seconds

# ── Country name → ISO 3166-1 alpha-2 ────────────────────────────────────────
_COUNTRY_TO_ISO: dict[str, str] = {
    "romania": "RO",
    "germany": "DE", "deutschland": "DE",
    "france": "FR",
    "italy": "IT", "italia": "IT",
    "spain": "ES", "españa": "ES",
    "poland": "PL", "polska": "PL",
    "netherlands": "NL", "holland": "NL", "nederland": "NL",
    "belgium": "BE", "belgique": "BE", "belgië": "BE",
    "portugal": "PT",
    "czech republic": "CZ", "czechia": "CZ", "czech": "CZ",
    "slovakia": "SK",
    "hungary": "HU", "magyarország": "HU",
    "sweden": "SE", "sverige": "SE",
    "norway": "NO", "norge": "NO",
    "denmark": "DK", "danmark": "DK",
    "finland": "FI", "suomi": "FI",
    "greece": "GR", "hellas": "GR",
    "turkey": "TR", "türkiye": "TR",
    "russia": "RU",
    "japan": "JP",
    "china": "CN",
    "south korea": "KR", "korea": "KR",
    "united states": "US", "usa": "US", "us": "US",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "australia": "AU",
    "canada": "CA",
    "brazil": "BR", "brasil": "BR",
    "india": "IN",
    "new zealand": "NZ",
    "ireland": "IE",
    "south africa": "ZA",
    "austria": "AT", "österreich": "AT",
    "switzerland": "CH", "schweiz": "CH",
}


def country_name_to_iso(name: str) -> str:
    """Map a free-text country name (from user profile) to an ISO code. Returns '' if unknown."""
    return _COUNTRY_TO_ISO.get((name or "").strip().lower(), "")


# ── DB loader ─────────────────────────────────────────────────────────────────

def _refresh() -> None:
    """Reload all active retailers from Supabase. Called when cache is stale."""
    global _domains_by_country, _proxy_domains, _last_refresh
    try:
        from services.supabase_service import get_supabase_admin
        rows = (
            get_supabase_admin()
            .table("supported_retailers")
            .select("domain,target_country,requires_proxy")
            .eq("is_active", True)
            .execute()
            .data or []
        )
        by_country: dict[str, list[str]] = {}
        proxy: set[str] = set()
        for row in rows:
            by_country.setdefault(row["target_country"], []).append(row["domain"])
            if row["requires_proxy"]:
                proxy.add(row["domain"])
        with _LOCK:
            _domains_by_country = by_country
            _proxy_domains = frozenset(proxy)
            _last_refresh = time.monotonic()
        logger.info("[RETAILERS] loaded %d active retailers from DB", len(rows))
    except Exception as exc:
        logger.warning("[RETAILERS] DB refresh failed (using cache/fallback): %s", exc)


def _ensure_fresh() -> None:
    if time.monotonic() - _last_refresh > _TTL:
        _refresh()


# ── Public API ────────────────────────────────────────────────────────────────

def get_domains_for_country(country_code: str) -> list[str]:
    """Return active retailer domains for a given ISO country code (e.g. 'RO', 'DE')."""
    _ensure_fresh()
    return list(_domains_by_country.get(country_code.upper(), []))


def get_global_domains() -> list[str]:
    """Return GLOBAL-tagged retailer domains (Amazon, eBay, AliExpress, etc.).
    Falls back to the list embedded in tavily_service when the DB is empty."""
    _ensure_fresh()
    db_global = list(_domains_by_country.get("GLOBAL", []))
    if db_global:
        return db_global
    # Graceful fallback — tavily_service already has this list
    try:
        from services.tavily_service import _GLOBAL_ECOMMERCE_DOMAINS
        return list(_GLOBAL_ECOMMERCE_DOMAINS)
    except Exception:
        return []


def _bare_domain(raw: str) -> str:
    """Strip scheme and www. from a URL or bare domain so lookups always match."""
    m = re.search(r"(?:https?://)?(?:www\.)?([^/?#]+)", raw or "")
    return m.group(1).lower() if m else (raw or "").lower()


def requires_proxy(domain: str) -> bool:
    """Return True when this domain requires a residential proxy.
    Accepts a bare domain ('emag.ro') or a full URL ('https://www.emag.ro/…').
    Replaces the hardcoded _HARD_DOMAINS frozenset in scraper_service."""
    _ensure_fresh()
    bare = _bare_domain(domain)
    if _proxy_domains:
        return bare in _proxy_domains
    # Fallback: mirror the original hardcoded set so prod never degrades
    return bare in _PROXY_FALLBACK


def preload() -> None:
    """Warm the cache at startup — call once from the FastAPI lifespan."""
    _refresh()


# Hardcoded proxy fallback — mirrors the original _HARD_DOMAINS.
# Only used when the DB is completely unavailable (first deploy, network error).
_PROXY_FALLBACK: frozenset[str] = frozenset({
    "emag.ro", "altex.ro", "flanco.ro",
    "amazon.com",    "amazon.de",    "amazon.co.uk", "amazon.fr",
    "amazon.it",     "amazon.es",    "amazon.pl",    "amazon.nl",
    "amazon.se",     "amazon.ca",    "amazon.co.jp", "amazon.com.au",
    "amazon.com.br", "amazon.com.mx", "amazon.in",
    "walmart.com", "target.com",
})
