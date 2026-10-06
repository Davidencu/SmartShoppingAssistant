"""
Retailers service — single source of truth for:
  • Which domains are active per country (used by Tavily for targeted searches)
  • Which product categories each domain sells (so a fridge search skips beauty shops)
  • Which domains require a residential proxy (replaces hardcoded _HARD_DOMAINS)
  • Country name → ISO 3166-1 alpha-2 code mapping

Data lives in the `supported_retailers` Supabase table and is cached in-process
with a 5-minute TTL so every request isn't a DB round-trip.

Every domain getter accepts an optional `categories` filter. A domain matches when
its `category` array overlaps the requested categories OR contains 'general'
(marketplaces / department stores). No categories → no filtering.
"""
import logging
import re
import threading
import time
from collections.abc import Iterable

logger = logging.getLogger(__name__)

# Keep in sync with the valid_category CHECK constraint in
# supabase/migrations/011_retailer_categories.sql.
SHOP_CATEGORIES: frozenset[str] = frozenset({
    "general", "electronics", "appliances", "gaming", "fashion", "beauty",
    "health", "sports", "cycling", "outdoor", "books", "home", "diy",
    "pets", "toys", "baby", "music", "auto",
})
_GENERAL = frozenset({"general"})

# ── In-memory TTL cache ───────────────────────────────────────────────────────
_LOCK = threading.Lock()
_domains_by_country: dict[str, list[str]] = {}
_niche_domains_by_country: dict[str, list[str]] = {}
_categories_by_domain: dict[str, frozenset[str]] = {}
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

def _fetch_rows() -> list[dict]:
    """Load active retailers. Falls back to the pre-011 column set when the
    `category` column doesn't exist yet, so the app keeps working (unfiltered)
    until the migration is applied."""
    from services.supabase_service import get_supabase_admin
    table = get_supabase_admin().table("supported_retailers")
    try:
        return (
            table.select("domain,target_country,requires_proxy,tier,category")
            .eq("is_active", True).execute().data or []
        )
    except Exception as exc:
        logger.warning(
            "[RETAILERS] category column unavailable (apply migration 011) — "
            "loading without category filtering: %s", exc,
        )
        return (
            get_supabase_admin().table("supported_retailers")
            .select("domain,target_country,requires_proxy,tier")
            .eq("is_active", True).execute().data or []
        )


def _refresh() -> None:
    """Reload all active retailers from Supabase. Called when cache is stale."""
    global _domains_by_country, _niche_domains_by_country, _categories_by_domain
    global _proxy_domains, _last_refresh
    try:
        rows = _fetch_rows()
        by_country: dict[str, list[str]] = {}
        niche: dict[str, list[str]] = {}
        cats: dict[str, frozenset[str]] = {}
        proxy: set[str] = set()
        n_mainstream = 0
        for row in rows:
            by_country.setdefault(row["target_country"], []).append(row["domain"])
            if row.get("tier") == "niche":
                niche.setdefault(row["target_country"], []).append(row["domain"])
            elif row.get("tier") == "mainstream":
                n_mainstream += 1
            if row.get("requires_proxy"):
                proxy.add(row["domain"])
            cats[row["domain"]] = frozenset(row.get("category") or ()) or _GENERAL
        with _LOCK:
            _domains_by_country = by_country
            _niche_domains_by_country = niche
            _categories_by_domain = cats
            _proxy_domains = frozenset(proxy)
            _last_refresh = time.monotonic()
        logger.info(
            "[RETAILERS] loaded %d active retailers (%d niche, %d mainstream) from DB",
            len(rows), sum(len(v) for v in niche.values()), n_mainstream,
        )
    except Exception as exc:
        logger.warning("[RETAILERS] DB refresh failed (using cache/fallback): %s", exc)


def _ensure_fresh() -> None:
    if time.monotonic() - _last_refresh > _TTL:
        _refresh()


# ── Category filtering ────────────────────────────────────────────────────────

def normalize_categories(raw: Iterable[str] | str | None) -> frozenset[str]:
    """
    Clean the shop categories produced by the intent model.
    Drops unknown values and 'general'. An empty result means "don't filter".
    """
    if not raw:
        return frozenset()
    if isinstance(raw, str):
        raw = [raw]
    cleaned = {str(c).strip().lower() for c in raw if c}
    return frozenset(cleaned & SHOP_CATEGORIES) - _GENERAL


def _filter(domains: Iterable[str], categories: Iterable[str] | None) -> list[str]:
    """Keep domains whose categories overlap `categories` or include 'general'.
    Domains with no category data are treated as 'general'."""
    wanted = normalize_categories(categories)
    if not wanted:
        return list(domains)
    out = []
    for d in domains:
        shop = _categories_by_domain.get(d, _GENERAL)
        if "general" in shop or shop & wanted:
            out.append(d)
    return out


def get_domain_categories(domain: str) -> frozenset[str]:
    """Return the categories a domain is tagged with ('general' when unknown)."""
    _ensure_fresh()
    return _categories_by_domain.get(_bare_domain(domain), _GENERAL)


# ── Public API ────────────────────────────────────────────────────────────────

def get_domains_for_country(
    country_code: str, categories: Iterable[str] | None = None,
) -> list[str]:
    """Return active retailer domains for an ISO country code (e.g. 'RO', 'DE'),
    optionally restricted to shops selling the given categories."""
    _ensure_fresh()
    return _filter(_domains_by_country.get(country_code.upper(), []), categories)


def get_niche_domains_for_country(
    country_code: str, categories: Iterable[str] | None = None,
) -> list[str]:
    """Return only mid-market/specialty (tier='niche') domains for a country.
    Used for the niche-first search pass — these sites have lighter anti-bot
    measures and richer JSON-LD than mainstream platforms like Amazon or eMag."""
    _ensure_fresh()
    return _filter(_niche_domains_by_country.get(country_code.upper(), []), categories)


def get_global_domains(categories: Iterable[str] | None = None) -> list[str]:
    """Return GLOBAL-tagged retailer domains (Amazon, eBay, AliExpress, etc.).
    Falls back to the list embedded in tavily_service when the DB is empty."""
    _ensure_fresh()
    db_global = _filter(_domains_by_country.get("GLOBAL", []), categories)
    if db_global:
        return db_global
    # Graceful fallback — tavily_service already has this list
    try:
        from services.tavily_service import _GLOBAL_ECOMMERCE_DOMAINS
        return _filter(_GLOBAL_ECOMMERCE_DOMAINS, categories)
    except Exception:
        return []


def get_global_niche_domains(categories: Iterable[str] | None = None) -> list[str]:
    """Return only niche/specialty GLOBAL-tagged domains (reverb.com, sweetwater.com, etc.).
    Used for the combined local+global niche pass — lighter anti-bot, no proxy needed."""
    _ensure_fresh()
    return _filter(_niche_domains_by_country.get("GLOBAL", []), categories)


def get_global_mainstream_domains(categories: Iterable[str] | None = None) -> list[str]:
    """Return GLOBAL mainstream domains (Amazon, eBay, AliExpress, etc.) excluding niche ones.
    Used as the last-resort fallback after niche and local passes have failed."""
    _ensure_fresh()
    global_all = _domains_by_country.get("GLOBAL", [])
    niche_set = frozenset(_niche_domains_by_country.get("GLOBAL", []))
    mainstream = _filter([d for d in global_all if d not in niche_set], categories)
    if mainstream:
        return mainstream
    # If tier data not yet populated fall back to the full global list
    if global_all:
        return _filter(global_all, categories)
    try:
        from services.tavily_service import _GLOBAL_ECOMMERCE_DOMAINS
        return _filter(_GLOBAL_ECOMMERCE_DOMAINS, categories)
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
