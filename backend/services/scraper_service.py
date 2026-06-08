"""
High-throughput scraper service with three concurrency primitives:

1. BloomFilter  — compact bit-array tracking every URL ever scraped.
                  Eliminates the need to hold 10,000+ URL strings in RAM.
                  ~1% false-positive rate at 100k capacity ≈ 120 KB of bits.

2. _LRUCache    — exact scrape-result store (markdown + jsonld) for recently
                  seen URLs.  Bloom filter says "probably seen"; this confirms
                  and returns the actual payload without a network round-trip.

3. ScraperScheduler — asyncio.PriorityQueue-backed worker pool.
                  P1 (user request) → processed immediately, no delay.
                  P5 (background refresh) → 3 s between scrapes = polite,
                  server-friendly rate that avoids IP bans.
                  Tiebreaker: monotonic sequence number keeps same-priority
                  requests FIFO and prevents asyncio from ever comparing
                  Future objects (which are not orderable).
"""
import asyncio
import hashlib
import json as _json
import logging
import math
import random
import re
import threading
import time
import urllib.request
import urllib.parse
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from collections.abc import Awaitable, Callable
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi.requests import Session

from services.jsonld_service import extract_bs4_facts, extract_jsonld_facts

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 10   # seconds to establish TCP + TLS (direct / CF Swarm)
_READ_TIMEOUT    = 25   # seconds to receive first byte after connect (direct)
_TIMEOUT         = _CONNECT_TIMEOUT + _READ_TIMEOUT  # asyncio hard cap
_GHOST_READ_TIMEOUT = 8  # Wayback Machine hangs indefinitely for never-archived URLs
# Residential proxy peers are real home/mobile connections — they need more time.
_PROXY_CONNECT_TIMEOUT = 20  # longer TCP setup through the proxy peer chain
_PROXY_READ_TIMEOUT    = 35  # heavy pages (eMAG 3 MB+) take longer over residential hop

# Diverse Chrome/Edge fingerprints — each has a different TLS JA3 hash.
# Domain is hashed → consistent profile per domain (same browser across
# cache misses) while distributing traffic across profiles globally.
_BROWSER_PROFILES: list[Any] = [
    "chrome131",   # Dec 2024 — newest
    "chrome124",   # Apr 2024
    "chrome120",   # Dec 2023
    "chrome116",   # Aug 2023
    "chrome110",   # Feb 2023
    "edge101",     # Apr 2022 — Chromium engine, distinct TLS profile
]

# Curated per-domain profile overrides — bypass the hash for known sites
# where empirical testing shows a specific fingerprint works best.
# Safari profiles slip through Amazon / Walmart WAFs better than Chrome
# because their bot-detection is heavily tuned to Chrome fingerprints.
# Romanian retailers work reliably on recent Chrome versions.
_DOMAIN_PROFILE_OVERRIDES: dict[str, Any] = {
    # ── Romanian e-commerce ──────────────────────────────────────────────
    "emag.ro":          "chrome120",
    "pcgarage.ro":      "safari17_0",
    "altex.ro":         "chrome116",
    "flanco.ro":        "chrome124",
    "cel.ro":           "chrome120",
    "elefant.ro":       "chrome116",
    "dedeman.ro":       "chrome120",
    # ── Amazon (all regions) — Safari slips through Chrome-tuned WAF ─────
    "amazon.com":       "safari17_0",
    "amazon.de":        "safari17_0",
    "amazon.co.uk":     "safari17_0",
    "amazon.fr":        "safari17_0",
    "amazon.it":        "safari17_0",
    "amazon.es":        "safari17_0",
    "amazon.pl":        "safari17_0",
    "amazon.nl":        "safari17_0",
    "amazon.se":        "safari17_0",
    # ── Other heavily protected global retailers ──────────────────────────
    "walmart.com":      "safari17_0",
    "bestbuy.com":      "edge101",
    "newegg.com":       "chrome124",
    "bhphotovideo.com": "chrome120",
    # ── German / Austrian ────────────────────────────────────────────────
    "otto.de":          "chrome120",
    "mediamarkt.de":    "chrome116",
    "saturn.de":        "chrome116",
    "mediamarkt.at":    "chrome116",
    # ── French ────────────────────────────────────────────────────────────
    "fnac.com":         "chrome120",
    "cdiscount.com":    "chrome116",
    "darty.com":        "chrome120",
    "boulanger.com":    "chrome120",
    # ── UK ────────────────────────────────────────────────────────────────
    "argos.co.uk":      "chrome124",
    "johnlewis.com":    "edge101",
    "currys.co.uk":     "chrome120",
    # ── Spanish ───────────────────────────────────────────────────────────
    "pccomponentes.com": "chrome120",
    "mediamarkt.es":    "chrome116",
    # ── Polish ────────────────────────────────────────────────────────────
    "allegro.pl":       "chrome120",
    "mediaexpert.pl":   "chrome116",
    "neonet.pl":        "chrome120",
    # ── Italian ───────────────────────────────────────────────────────────
    "mediaworld.it":    "chrome116",
    "unieuro.it":       "chrome120",
}

def _proxy_required(domain: str) -> bool:
    """Return True when this domain must go straight to the residential proxy.
    Reads from retailers_service (DB-backed, TTL-cached) so the list is managed
    in Supabase instead of in code. Falls back to a hardcoded set when the DB
    is unavailable (cold start, network error)."""
    from services import retailers_service  # lazy to avoid circular import at module load
    return retailers_service.requires_proxy(domain) or domain in _proxy_required_domains

# ── Cloudflare Worker Swarm ────────────────────────────────────────────────
# Loaded once at startup from config.  Workers are round-robin rotated for
# IP diversity (each Cloudflare PoP has a distinct outbound IP).

_cf_worker_urls: list[str] = []
_cf_worker_secret: str = ""
_cf_worker_idx: int = 0
_cf_worker_lock = threading.Lock()

# ── Residential Proxy ─────────────────────────────────────────────────────
# Optional IPRoyal (or compatible) residential proxy.  Used lazily:
# _fetch_direct_sync tries a free direct connection first; the proxy is only
# activated when the direct attempt fails (403/429/soft-block).  Domains that
# fail once are remembered in _proxy_required_domains so future fetches skip
# the wasted direct attempt and go straight to the proxy.
_proxy_url: str = ""   # "http://user:pass@host:port" — empty = no proxy
_proxy_host: str = ""
_proxy_port: str = ""
_proxy_username: str = ""
_proxy_password: str = ""

# In-memory learner: domains where a direct attempt has already failed this
# session.  Seeded from Supabase hostile_domains table on startup so learned
# knowledge survives Railway deployments.
_proxy_required_domains: set[str] = set()

# ── Step 1: Supabase scrape cache (24 h TTL) ─────────────────────────────────
# Persists across server restarts — the in-process LRU cache is cleared on
# each Railway deploy.  Only called from executor threads (safe for sync I/O).
#
# Required Supabase tables (run once in the SQL editor):
#
#   CREATE TABLE IF NOT EXISTS scrape_cache (
#     url                TEXT PRIMARY KEY,
#     markdown           TEXT,
#     jsonld             JSONB,
#     shipping_policy_url TEXT,
#     return_policy_text  TEXT,
#     scraped_at         TIMESTAMPTZ DEFAULT NOW()
#   );
#
#   CREATE TABLE IF NOT EXISTS hostile_domains (
#     domain     TEXT PRIMARY KEY,
#     flagged_at TIMESTAMPTZ DEFAULT NOW()
#   );

_DB_CACHE_TTL_HOURS = 24


def _db_cache_get(url: str) -> dict | None:
    """
    Return a cached scrape result from Supabase when it is < 24 h old.
    Returns None on cache miss or any DB error (graceful degradation).
    """
    try:
        from services.supabase_service import get_supabase_admin
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=_DB_CACHE_TTL_HOURS)).isoformat()
        res = (
            get_supabase_admin()
            .table("scrape_cache")
            .select("url, markdown, jsonld, shipping_policy_url, return_policy_text")
            .eq("url", url)
            .gte("scraped_at", cutoff)
            .limit(1)
            .execute()
        )
        if res.data:
            logger.debug("[DB-CACHE] hit for %s", url)
            return res.data[0]
    except Exception as exc:
        logger.debug("[DB-CACHE] get error for %s: %s", url, exc)
    return None


def _db_cache_put(url: str, result: dict) -> None:
    """
    Upsert a successful scrape result into Supabase scrape_cache.
    Only caches pages that produced real markdown (not blocked/empty responses).
    Runs in a daemon thread so it never adds latency to the caller.
    """
    if not result.get("markdown"):
        return
    try:
        from services.supabase_service import get_supabase_admin
        get_supabase_admin().table("scrape_cache").upsert({
            "url": url,
            "markdown": result.get("markdown", ""),
            "jsonld": result.get("jsonld") or {},
            "shipping_policy_url": result.get("shipping_policy_url"),
            "return_policy_text": result.get("return_policy_text"),
        }).execute()
        logger.debug("[DB-CACHE] saved %s (%d chars)", url, len(result.get("markdown", "")))
    except Exception as exc:
        logger.debug("[DB-CACHE] put error for %s: %s", url, exc)


def _db_cache_put_bg(url: str, result: dict) -> None:
    """Fire-and-forget wrapper: Supabase write runs in a daemon thread."""
    threading.Thread(target=_db_cache_put, args=(url, result), daemon=True).start()


# ── Hostile-domain persistence ────────────────────────────────────────────────

def _flag_domain_hostile(domain: str) -> None:
    """
    Mark a domain as proxy-required:
      1. Add to in-memory set immediately (takes effect for the rest of the session).
      2. Persist to Supabase hostile_domains so the label survives server restarts.
    """
    _proxy_required_domains.add(domain)
    logger.info("[PROXY] [LEARNER] %s → proxy-required (flagged hostile)", domain)

    def _persist() -> None:
        try:
            from services.supabase_service import get_supabase_admin
            get_supabase_admin().table("hostile_domains").upsert({
                "domain": domain,
                "flagged_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception:
            pass  # in-memory flag is already set; DB write is best-effort

    threading.Thread(target=_persist, daemon=True).start()


def _load_hostile_domains() -> None:
    """
    Seed retailers_service cache + _proxy_required_domains from Supabase on startup.
    retailers_service is now the authoritative source; _proxy_required_domains
    only augments it with runtime-learned hostile domains.
    Fails silently on first deploy (table may not exist yet).
    """
    try:
        from services import retailers_service
        retailers_service.preload()  # warms the TTL cache from supported_retailers
    except Exception as exc:
        logger.debug("[PROXY] retailers_service preload failed (first deploy?): %s", exc)


def _init_cf_workers() -> None:
    """Load Worker URLs + secret + residential proxy from settings."""
    global _cf_worker_urls, _cf_worker_secret, _proxy_url
    global _proxy_host, _proxy_port, _proxy_username, _proxy_password
    try:
        from core.config import settings  # local import avoids circular deps at module load
        raw = (settings.cf_worker_urls or "").strip()
        _cf_worker_urls = [u.strip() for u in raw.split(",") if u.strip()]
        _cf_worker_secret = (settings.cf_worker_secret or "").strip()
        if _cf_worker_urls:
            logger.info("[CF-SWARM] %d worker(s) configured", len(_cf_worker_urls))
        else:
            logger.debug("[CF-SWARM] no workers configured — hard domains use direct curl_cffi")

        # Residential proxy setup
        host = (settings.proxy_host or "").strip()
        port = (settings.proxy_port or "").strip()
        user = (settings.proxy_username or "").strip()
        pwd  = (settings.proxy_password or "").strip()
        if host and port and user and pwd:
            _proxy_url = f"http://{user}:{pwd}@{host}:{port}"
            _proxy_host, _proxy_port, _proxy_username, _proxy_password = host, port, user, pwd
            logger.info("[PROXY] residential proxy configured: %s:%s", host, port)
        else:
            logger.debug("[PROXY] no residential proxy configured")
    except Exception as exc:
        logger.warning("[CF-SWARM] could not load worker config: %s", exc)

    # Seed the in-memory hostile-domain learner from Supabase (best-effort).
    _load_hostile_domains()



def _next_worker() -> str | None:
    """Thread-safe round-robin selection across configured workers."""
    global _cf_worker_idx
    if not _cf_worker_urls:
        return None
    with _cf_worker_lock:
        url = _cf_worker_urls[_cf_worker_idx % len(_cf_worker_urls)]
        _cf_worker_idx += 1
    return url


# Accept-Language matched to the site's TLD so regional firewalls
# see a geographically plausible browser locale.
_TLD_LOCALE: dict[str, str] = {
    "ro": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
    "de": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "fr": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "es": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "it": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "pl": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "nl": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    "pt": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "hu": "hu-HU,hu;q=0.9,en-US;q=0.8,en;q=0.7",
    "cz": "cs-CZ,cs;q=0.9,en-US;q=0.8,en;q=0.7",
    "se": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
    "no": "nb-NO,nb;q=0.9,en-US;q=0.8,en;q=0.7",
    "dk": "da-DK,da;q=0.9,en-US;q=0.8,en;q=0.7",
    "uk": "en-GB,en;q=0.9,en-US;q=0.8",
    "au": "en-AU,en;q=0.9,en-US;q=0.8",
    "ca": "en-CA,en;q=0.9,en-US;q=0.8",
    "jp": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    "kr": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "br": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "mx": "es-MX,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "in": "en-IN,en;q=0.9,hi;q=0.8",
    "com": "en-US,en;q=0.9",
}


def _profile_for_domain(domain: str) -> Any:
    """
    Return the browser profile for a domain.
    Curated overrides take priority (empirically chosen per retailer).
    Unknown domains fall back to a deterministic hash assignment so the
    same domain always gets the same fingerprint across requests.
    """
    if domain in _DOMAIN_PROFILE_OVERRIDES:
        return _DOMAIN_PROFILE_OVERRIDES[domain]
    h = int(hashlib.md5(domain.encode(), usedforsecurity=False).hexdigest(), 16)
    return _BROWSER_PROFILES[h % len(_BROWSER_PROFILES)]


def _origin_referer(url: str) -> str:
    """
    Return the site's own origin as the Referer (same-origin navigation).
    Looks like a user who landed on the homepage and clicked a product link.
    A static google.com referer on deep pagination URLs is a WAF red flag
    because Google Search never links to page-3 of internal category results.
    """
    m = re.match(r"(https?://[^/]+)", url)
    return m.group(1) + "/" if m else url


def _headers_for_url(url: str) -> dict[str, str]:
    """Browser-matching headers: locale from TLD + same-origin referer."""
    tld = _extract_domain(url).rsplit(".", 1)[-1].lower()
    locale = _TLD_LOCALE.get(tld, "en-US,en;q=0.9")
    return {
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        ),
        "Accept-Language": locale,
        "Referer": _origin_referer(url),
        "Upgrade-Insecure-Requests": "1",
    }


# Priority levels

class Priority(IntEnum):
    P1_USER_REQUEST  = 1   # Direct user search — no delay, immediate processing
    P2_RETRY         = 2   # Failed URL being retried
    P3_PREFETCH      = 3   # Speculative cache warm-up
    P4_CACHE_REFRESH = 4   # Refreshing near-expiry cached results
    P5_BACKGROUND    = 5   # Background stock-data refresh — most polite to servers

# Seconds to sleep AFTER completing a scrape at the given priority level.
# P1 is instant; P5 waits 3 s between each request — prevents IP bans for
# low-urgency work without slowing down real users at all.
_PRIORITY_DELAYS: dict[int, float] = {
    Priority.P1_USER_REQUEST:  0.0,
    Priority.P2_RETRY:         0.5,
    Priority.P3_PREFETCH:      1.0,
    Priority.P4_CACHE_REFRESH: 2.0,
    Priority.P5_BACKGROUND:    3.0,
}


# Bloom Filter

class BloomFilter:
    """
    Space-efficient probabilistic URL-seen tracker.

    Uses Kirsch-Mitzenmacher double-hashing (md5 + sha1) to derive k hash
    positions from two base hashes, keeping per-item cost to two digests
    regardless of the number of hash functions.

    Memory: ~120 KB for capacity=100_000, error_rate=0.01.
    False negatives: impossible.  False positives: ~1% at capacity.
    """

    __slots__ = ("_size", "_hash_count", "_bits")

    def __init__(self, capacity: int = 100_000, error_rate: float = 0.01):
        # Optimal bit-array size: m = -n·ln(p) / (ln 2)²
        self._size: int = max(1, int(-capacity * math.log(error_rate) / math.log(2) ** 2))
        # Optimal number of hash functions: k = (m/n)·ln 2
        self._hash_count: int = max(1, int(self._size / capacity * math.log(2)))
        self._bits = bytearray(self._size // 8 + 1)

    # internal helpers

    def _positions(self, item: str) -> list[int]:
        encoded = item.encode()
        h1 = int.from_bytes(hashlib.md5(encoded, usedforsecurity=False).digest(), "little")
        h2 = int.from_bytes(hashlib.sha1(encoded).digest(), "little")  # noqa: S324
        return [(h1 + i * h2) % self._size for i in range(self._hash_count)]

    # public API

    def add(self, item: str) -> None:
        for pos in self._positions(item):
            self._bits[pos >> 3] |= 1 << (pos & 7)

    def __contains__(self, item: str) -> bool:
        return all(self._bits[pos >> 3] & (1 << (pos & 7)) for pos in self._positions(item))

    @property
    def bit_count(self) -> int:
        return self._size

    def approx_item_count(self) -> int:
        """Estimate number of distinct items added (based on set-bit ratio)."""
        set_bits = sum(bin(b).count("1") for b in self._bits)
        ratio = min(set_bits / self._size, 0.9999)
        return int(-self._size / self._hash_count * math.log(1.0 - ratio))


# URL result LRU cache

class _LRUCache:
    """
    Bounded LRU cache for scrape results (markdown + jsonld per URL).
    OrderedDict preserves insertion/access order; popitem(last=False)
    evicts the least-recently-used entry when at capacity.
    """

    def __init__(self, maxsize: int = 2_000):
        self._store: OrderedDict[str, dict] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> Optional[dict]:
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key]

    def put(self, key: str, value: dict) -> None:
        if key in self._store:
            self._store.move_to_end(key)
            self._store[key] = value              # update value in-place
        else:
            if len(self._store) >= self._maxsize:
                self._store.popitem(last=False)   # evict LRU entry
            self._store[key] = value

    def __len__(self) -> int:
        return len(self._store)


# Module-level singletons

# Bloom filter: ~120 KB covering 100k URLs, ~1% false-positive rate
_scraped_bloom = BloomFilter(capacity=100_000, error_rate=0.01)

# URL scrape-result cache: at most 2000 pages (~20–100 KB each) in RAM
_url_cache = _LRUCache(maxsize=2_000)

# Per-domain policy cache: domain → {"shipping_url": str|None, "return_text": str|None}
_policy_cache: dict[str, dict] = {}

_SHIPPING_KEYWORDS = [
    "shipping", "delivery", "livrare", "transport", "versand", "livraison",
    "expedition", "envio", "frete", "spedizione", "bezorging",
    "shipping-policy", "delivery-info", "delivery-policy",
]

_RETURN_KEYWORDS = [
    "return", "refund", "retur", "ramburs", "retour", "rückgabe",
    "reembolso", "reso", "terugsturen", "exchange", "cancellation",
]


def _extract_domain(url: str) -> str:
    m = re.search(r"(?:https?://)?(?:www\.)?([^/]+)", url)
    return m.group(1).lower() if m else ""


def _find_policy_links(html: str, base_url: str) -> tuple[str | None, str | None]:
    """
    Scan all links checking both href and anchor text for shipping and return
    policy pages on the same domain. Returns (shipping_url, return_url).
    """
    base_domain = _extract_domain(base_url)
    soup = BeautifulSoup(html, "html.parser")
    shipping_url: str | None = None
    return_url: str | None = None

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        combined = (href + " " + a_tag.get_text(strip=True)).lower()
        full = urljoin(base_url, href)
        if _extract_domain(full) != base_domain or full == base_url:
            continue
        if shipping_url is None and any(kw in combined for kw in _SHIPPING_KEYWORDS):
            shipping_url = full
        if return_url is None and any(kw in combined for kw in _RETURN_KEYWORDS):
            return_url = full
        if shipping_url and return_url:
            break

    return shipping_url, return_url


# ── Text extraction ───────────────────────────────────────────────────────

def _extract_text_bs4(html: str) -> str:
    """
    BS4 product-page text extraction.
    Removes boilerplate (nav/footer/scripts) and returns the full body text
    so Gemini sees spec tables, review excerpts, and feature bullets.
    """
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return ""
    for noise in soup(["script", "style", "nav", "footer", "header", "aside",
                       "noscript", "iframe", "svg"]):
        noise.decompose()
    # Strip form internals but keep enabled button text — disabled buttons signal OOS
    # and must be dropped so Gemini doesn't misread a greyed-out "Add to Cart" as
    # an active checkout path.
    for form in soup.find_all("form"):
        valid_buttons = []
        for b in form.find_all(["button", "input"]):
            if b.has_attr("disabled") or "disabled" in b.get("class", []):
                continue
            valid_buttons.append(b.get_text(" ", strip=True))
        form.replace_with(soup.new_string(" ".join(valid_buttons)))
    body = soup.body or soup
    text = body.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)[:50_000]


# ── URL shape heuristics ──────────────────────────────────────────────────────

_CAT_PATH_RE = re.compile(
    r"/(?:"
    r"cat|category|categorie|kategorie|kategori|kategoria|"
    r"collections|catalog|catalogo|catalogue|katalog|catalogus|wholesale|"
    r"search|cautare|recherche|suche|buscar|busqueda|ricerca|szukaj|zoeken|sok|sog|"
    r"filter|filtru|filtre|filtro|filtr|szuro"
    r")(?:/|$|\?)",
    re.IGNORECASE,
)

_PRODUCT_KEYWORDS = re.compile(
    r"(?:bicicleta|bike|rucsac|backpack|ceas|watch|laptop|notebook|pantofi|shoes|adidasi)",
    re.IGNORECASE,
)
_CAT_PARAM_RE = re.compile(
    r"[?&](?:category|cat|department|brand|sort|filter|page|p|offset|from|"
    r"q|query|search|tag|type|collection|gender|keywords)=",
    re.IGNORECASE,
)

# App store and platform-download hosts — never contain buyable products
_JUNK_HOSTS: frozenset[str] = frozenset({
    "apps.apple.com",
    "play.google.com",
    "appgallery.huawei.com",
})
_SKU_RE = re.compile(
    r"[-/](?:[A-Z]{1,4}-?\d{4,}|\d{6,}|[a-z]{2,8}-\d{3,})(?:/|$|\?)",
    re.IGNORECASE,
)


def is_likely_product_url(url: str) -> bool:
    """
    Heuristic filter: True when the URL looks like a product detail page (PDP),
    False for category / search / listing pages that waste a scrape slot.
    """
    try:
        if _CAT_PATH_RE.search(url):
            return False

        path = urlparse(url).path.strip("/")
        segments = [s for s in path.split("/") if s]
        depth = len(segments)

        if depth == 0:
            return False

        if _SKU_RE.search(url):
            return True
        if depth >= 2 and len(segments[-1]) > 10:
            return True
        if depth == 1 and any(char.isdigit() for char in segments[0] if char in "-_"):
            return True

        # Niche bypass: flat SEO slug containing a product noun lets through
        # stores that never embed numeric IDs (e.g. /rucsac-columbia-trail-elite).
        if depth == 1 and _PRODUCT_KEYWORDS.search(segments[0]):
            logger.info("[SHAPE FILTER] allowed depth-1 niche product via keyword pass: %s", url)
            return True

        logger.debug("[SHAPE FILTER] dropped structurally non-conforming URL: %s", url)
        return False
    except Exception:
        return True  # on parse error, allow through


def is_cloudflare_challenge(html_content: str, status_code: int) -> bool:
    """Detect a Cloudflare waiting room or JS challenge page (returns 200 or 503)."""
    if status_code == 503:
        return True
    if not html_content:
        return False
    challenge_markers = [
        "<title>Just a moment...</title>",
        "cf-turnstile",
        "cf-browser-verification",
        "window._cf_chl_opt",
    ]
    return any(marker in html_content for marker in challenge_markers)


def is_valid_product_page(html: str) -> bool:
    """
    Detect SPA shells and WAF honeypot pages that return HTTP 200 but carry no
    product data.  A real e-commerce page always has at least one of:
      - JSON-LD structured data
      - __NEXT_DATA__ (Next.js SSR hydration)
      - __INITIAL_STATE__ / __nuxt (Vue/Nuxt)
      - More than 15 KB of raw HTML (enough for meaningful BS4 extraction)
    Anything under 5 KB is definitively an empty shell.
    """
    size = len(html)
    if size < 5_000:
        return False
    if size < 15_000:
        has_jsonld    = "application/ld+json" in html
        has_next_data = "__NEXT_DATA__" in html
        has_vue_state = "__INITIAL_STATE__" in html or "__nuxt" in html.lower()
        return has_jsonld or has_next_data or has_vue_state
    return True


# ── __NEXT_DATA__ logistics extraction ───────────────────────────────────

_NEXT_LOGISTICS_KEYS: frozenset[str] = frozenset({
    "delivery", "shipping", "freight", "transport", "livrare",
    "deliveryoptions", "shippingoptions", "deliverytime",
    "deliveryfee", "shippingfee", "shippingcost", "shippingrate",
})


def _dig_hydration(obj: Any, facts: dict, depth: int) -> None:
    """Recursively walk Next.js hydration JSON for logistics signals."""
    if depth > 6 or not isinstance(obj, (dict, list)):
        return
    if isinstance(obj, list):
        for item in obj[:20]:
            _dig_hydration(item, facts, depth + 1)
        return
    for key, val in obj.items():
        k = key.lower().replace("_", "").replace("-", "")
        if k in _NEXT_LOGISTICS_KEYS:
            if isinstance(val, (int, float)) and "shipping_cost" not in facts:
                facts["shipping_cost"] = float(val)
            elif isinstance(val, dict):
                cost = val.get("cost") or val.get("price") or val.get("fee") or val.get("amount")
                if cost is not None and "shipping_cost" not in facts:
                    try:
                        facts["shipping_cost"] = float(str(cost).replace(",", "."))
                    except (ValueError, TypeError):
                        pass
                days = val.get("days") or val.get("estimatedDays") or val.get("minDays")
                if days is not None and "delivery_days" not in facts:
                    facts["delivery_days"] = str(days)
        _dig_hydration(val, facts, depth + 1)


def _extract_next_data_logistics(html: str) -> dict:
    """
    Pull delivery/shipping data from the Next.js __NEXT_DATA__ hydration blob.
    React/Next.js storefronts embed the full server-side state here — including
    deliveryOptions, shippingFee, estimatedDays — before any API call fires.
    Zero extra network requests: the data is already in the initial HTML.
    """
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>([\s\S]*?)</script>',
        html, re.IGNORECASE,
    )
    if not m:
        return {}
    try:
        data = _json.loads(m.group(1))
    except Exception:
        return {}
    facts: dict = {}
    _dig_hydration(data, facts, depth=0)
    return facts


# Scraper core (synchronous, runs in thread pool)

def _parse_html(url: str, html: str) -> dict:
    """
    Extract structured facts from already-fetched HTML.
    JSON-LD wins on key conflict with BS4 heuristics.
    Logistics data is merged from JSON-LD shippingDetails and __NEXT_DATA__.
    Policy pages are fetched once per domain and cached in _policy_cache.
    """
    if not html:
        return {"url": url, "markdown": "", "jsonld": {}, "shipping_policy_url": None, "return_policy_text": None}

    # JSON-LD fills gaps from BS4, but visual OOS signals win over stale JSON-LD cache.
    # Mid-market sites cache HTML (including JSON-LD) for hours; the dynamic frontend
    # injects real-time stock state that BS4 reads from visible text — that reading
    # must override a "InStock" declaration frozen in a server-side cache.
    bs4_facts = extract_bs4_facts(html)
    jsonld_facts = extract_jsonld_facts(html)
    jsonld = {**bs4_facts, **jsonld_facts}
    if bs4_facts.get("availability") == "Out of Stock":
        jsonld["availability"] = "Out of Stock"

    # Merge logistics from __NEXT_DATA__ hydration (JSON-LD still wins on conflict).
    for k, v in _extract_next_data_logistics(html).items():
        if k not in jsonld:
            jsonld[k] = v

    # BS4 text extraction
    markdown = _extract_text_bs4(html)

    # Two-hop: find shipping + return policy pages once per domain
    domain = _extract_domain(url)
    if domain not in _policy_cache:
        shipping_url, return_url = _find_policy_links(html, url)
        return_text: str | None = None
        if return_url:
            try:
                # Use proxy only if this domain is known-hostile (same rule as _fetch_direct_sync).
                _pol_proxies = _proxies() if _proxy_required(domain) else None
                with Session(impersonate=_profile_for_domain(domain)) as rs:
                    rr = rs.get(
                        return_url,
                        timeout=10,
                        headers=_headers_for_url(return_url),
                        proxies=_pol_proxies,
                    )
                    if rr.status_code == 200:
                        return_text = _extract_text_bs4(rr.text) or None
            except Exception as exc:
                logger.debug("[SCRAPER] return policy fetch failed for %s: %s", return_url, exc)
        _policy_cache[domain] = {"shipping_url": shipping_url, "return_text": return_text}
        if shipping_url:
            logger.info("[SCRAPER] shipping policy URL found for %s: %s", domain, shipping_url)
        if return_text:
            logger.info("[SCRAPER] return policy fetched for %s (%d chars)", domain, len(return_text))

    cached = _policy_cache.get(domain, {})
    return {
        "url": url,
        "markdown": markdown,
        "jsonld": jsonld,
        "shipping_policy_url": cached.get("shipping_url"),
        "return_policy_text": cached.get("return_text"),
    }


def _proxies() -> dict | None:
    """Return a curl_cffi-compatible proxies dict when a residential proxy is configured."""
    if not _proxy_url:
        return None
    return {"http": _proxy_url, "https": _proxy_url}


def _country_for_url(url: str) -> str:
    """Map a URL's TLD to the 2-letter ISO country code used by the residential proxy."""
    tld = _extract_domain(url).rsplit(".", 1)[-1].lower()
    return "us" if tld in ("com", "net", "org", "io", "co") else tld


def fetch_via_residential_proxy(target_url: str, target_country: str) -> str | None:
    """
    Phase 2 Fallback: routes a dynamically generated URL through a location-matched
    residential proxy with a fresh session ID and a Chrome TLS fingerprint.

    Returns raw HTML on HTTP 200, None on any error or non-200 status.
    The caller is responsible for running is_cloudflare_challenge() on the result.
    """
    if not (_proxy_host and _proxy_username and _proxy_password):
        return None

    session_id = random.randint(100_000, 999_999)
    proxy_user = f"{_proxy_username}_country-{target_country}_session-{session_id}_lifetime-5m"
    proxy_url = f"http://{proxy_user}:{_proxy_password}@{_proxy_host}:{_proxy_port}"
    proxies = {"http": proxy_url, "https": proxy_url}

    try:
        with Session(impersonate="chrome120") as s:
            resp = s.get(
                target_url,
                proxies=proxies,
                timeout=(_PROXY_CONNECT_TIMEOUT, _PROXY_READ_TIMEOUT),
                headers=_headers_for_url(target_url),
            )
        if resp.status_code == 200:
            return resp.text
        logger.debug(
            "[PROXY] country-%s returned HTTP %d for %s",
            target_country, resp.status_code, target_url,
        )
        return None
    except Exception as exc:
        logger.debug("[PROXY] country-%s connection error for %s: %s", target_country, target_url, exc)
        return None


def _fetch_direct_sync(url: str, domain: str) -> dict:
    """
    Lazy-proxy curl_cffi fetch — two-attempt waterfall:

    Attempt 1 — Free direct connection (no proxy).
        Skipped for domains already known to require a proxy (hard-coded
        _HARD_DOMAINS or runtime-learned _proxy_required_domains).
    Attempt 2 — Residential proxy escalation.
        Activated on any failure from attempt 1: 429, 403/503, or a
        soft-block (valid HTTP 200 but empty/challenge page).  When a
        domain is escalated for the first time it is added to
        _proxy_required_domains so future calls skip the wasted direct hop.
        If no proxy is configured, marks the result as blocked immediately.
    """
    profile = _profile_for_domain(domain)
    headers = _headers_for_url(url)

    # Domains that are known-hostile skip the free direct attempt entirely.
    proxy_required = _proxy_required(domain)

    html = ""
    escalate = proxy_required  # hostile domains go straight to proxy

    # ── Attempt 1: free direct (skipped for known-hostile domains) ─────────
    if not escalate:
        try:
            with Session(impersonate=profile) as s:
                resp = s.get(url, timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT), headers=headers)
            if resp.status_code == 200:
                html = resp.text or ""
                if is_cloudflare_challenge(html, 200):
                    logger.warning("[SCRAPER] CF challenge (direct) for %s — escalating to proxy", url)
                    html = ""
                    escalate = True
                elif not is_valid_product_page(html):
                    logger.warning(
                        "[SCRAPER] soft-block (direct) for %s (%d chars) — escalating to proxy",
                        url, len(html),
                    )
                    html = ""
                    escalate = True
                # else: valid page — no escalation needed
            elif resp.status_code in (429, 403, 503):
                if is_cloudflare_challenge("", resp.status_code):
                    logger.debug("[SCRAPER] CF challenge HTTP %d (direct) for %s — escalating to proxy",
                                 resp.status_code, url)
                else:
                    logger.debug("[SCRAPER] HTTP %d (direct) for %s — escalating to proxy",
                                 resp.status_code, url)
                escalate = True
            else:
                logger.warning("HTTP %d for %s", resp.status_code, url)
                # Non-retriable status (404, 410, …) — mark blocked, skip proxy
                result = _parse_html(url, "")
                result["_blocked"] = True
                return result
        except Exception as exc:
            logger.warning("Direct fetch failed for %s: %s", url, exc)
            escalate = True

    # ── Attempt 2: residential proxy ───────────────────────────────────────
    cf_challenge = False
    blocked = False
    if escalate:
        if not _proxy_url:
            # No proxy configured — nothing left to try.
            result = _parse_html(url, "")
            result["_blocked"] = True
            return result

        if not proxy_required:
            # First failure — persist to Supabase + in-memory learner.
            _flag_domain_hostile(domain)

        delay = random.uniform(1.5, 3.0)
        logger.debug("[SCRAPER] proxy escalation for %s (%.1fs delay)", url, delay)
        time.sleep(delay)

        # chrome120 bypasses DataDome (Decathlon, SportsDirect, etc.); country-matched
        # session ID routes through a residential IP in the target market.
        country = _country_for_url(url)
        html = fetch_via_residential_proxy(url, country) or ""
        if not html:
            logger.warning("HTTP non-200 (proxy) for %s", url)
            blocked = True
        elif is_cloudflare_challenge(html, 200):
            logger.warning("[WAF WALL] CF challenge via proxy for %s — dropping contender", url)
            html = ""
            cf_challenge = True
            blocked = True
        elif not is_valid_product_page(html):
            logger.warning("[SCRAPER] soft-block even via proxy for %s", url)
            html = ""
            blocked = True

    result = _parse_html(url, html)
    if cf_challenge:
        result["_cf_challenge"] = True
    if blocked:
        result["_blocked"] = True
    return result


def _fetch_via_workers_sync(url: str, domain: str) -> dict:
    """
    Route the request through the Cloudflare Worker Swarm instead of fetching
    directly from this server.  Workers run on Cloudflare edge PoPs — their
    outbound IPs are not in cloud/datacenter ranges that Amazon/Walmart block.

    Tries each worker in round-robin order; falls back to _fetch_direct_sync
    if all workers fail (network error, worker down, non-200 worker response).
    """
    headers_for_target = _headers_for_url(url)
    payload = _json.dumps({"url": url, "headers": headers_for_target}).encode()

    tried: set[str] = set()
    for _ in range(len(_cf_worker_urls)):
        worker_url = _next_worker()
        if worker_url is None or worker_url in tried:
            break
        tried.add(worker_url)
        try:
            req = urllib.request.Request(
                worker_url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Worker-Secret": _cf_worker_secret,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = _json.loads(resp.read().decode())

            if body.get("status") == 200 and body.get("html"):
                final_url = body.get("final_url") or url
                html_body = body["html"]
                if not is_valid_product_page(html_body):
                    logger.warning(
                        "[CF-SWARM] soft-block via worker %s for %s (%d chars) — trying next",
                        worker_url, url, len(html_body),
                    )
                    continue  # try next worker; ghost layer catches total failure
                logger.debug("[CF-SWARM] hit via %s → status 200 (%d chars)", worker_url, len(html_body))
                return _parse_html(final_url, html_body)

            logger.debug("[CF-SWARM] worker %s returned status=%s for %s",
                         worker_url, body.get("status"), url)
        except Exception as exc:
            logger.warning("[CF-SWARM] worker %s error for %s: %s", worker_url, url, exc)

    # All workers failed — hard domains block direct datacenter IPs too, so
    # skip the direct curl_cffi attempt and signal the waterfall to escalate.
    logger.warning("[CF-SWARM] all workers failed for %s — marking blocked", url)
    result = _parse_html(url, "")
    result["_blocked"] = True
    return result



def _fetch_ghost_layer_sync(url: str) -> dict:
    """
    Step 5 — Ghost Layer: Internet Archive (Wayback Machine).
    Free public archival snapshots that include JSON-LD structured data embedded
    in the static HTML — extraction works without live JS execution.
    Used only after Steps 3 and 4 both fail.

    Note: Google Web Cache was shut down in early 2024 and has been removed.
    Bing cache (cc.bingj.com) was also removed — DNS does not resolve from this host.
    """
    ghost_headers = {
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # ── Internet Archive (Wayback Machine) ───────────────────────────────
    archive_url = f"https://web.archive.org/web/{url}"
    try:
        with Session(impersonate="chrome131") as s:
            resp = s.get(archive_url, timeout=_GHOST_READ_TIMEOUT, headers=ghost_headers)
            if resp.status_code == 200 and len(resp.text) > 500:
                logger.info("[GHOST] Archive hit for %s", url)
                return _parse_html(url, resp.text)
    except Exception as exc:
        logger.debug("[GHOST] Archive error for %s: %s", url, exc)

    logger.warning("[GHOST] all cache sources exhausted for %s", url)
    return {"url": url, "markdown": "", "jsonld": {}}


def _fetch_one_sync(url: str) -> dict:
    """
    5-step cost-ordered waterfall.

    Step 1 — DB Cache (Supabase, 24 h TTL): $0. Returns instantly, zero retailer
             network traffic.
    Step 2 — Reputation Engine: known-hostile domains (emag.ro, amazon.*, etc.)
             skip Steps 3 and go directly to Step 4 (encoded in _HARD_DOMAINS /
             _proxy_required_domains and handled inside _fetch_direct_sync).
    Step 3 — Free Swarm (CF Workers / direct curl_cffi): $0. If 200 → parse, save,
             return.  If 403 → flag domain hostile (persisted) and fall to Step 4.
    Step 4 — Residential Proxy (~$0.0003/req): used exclusively for confirmed-hostile
             domains and those just flagged by Step 3.
    Step 5 — Ghost Layer (Google → Bing → Internet Archive): $0. Last resort;
             extracts JSON-LD from archival snapshots when the live page is blocked.
    """
    domain = _extract_domain(url)

    # ── Step 1: DB cache ────────────────────────────────────────────────────
    cached = _db_cache_get(url)
    if cached:
        return cached

    # ── Steps 3 + 4: live network fetch ─────────────────────────────────────
    # Step 2 (reputation) is explicit here: proxy-required domains are routed
    # DIRECTLY to the residential proxy — the CF Swarm is never called for them.
    # Sending a proxy-required domain through the Swarm first pre-flags the WAF
    # before the proxy runs, causing both attempts to fail.
    result: dict
    proxy_required = _proxy_required(domain)

    if proxy_required:
        # Known-hostile domain → straight to residential proxy, skip CF Swarm entirely.
        logger.info("[WATERFALL] proxy-required → residential proxy %s", url)
        result = _fetch_direct_sync(url, domain)
        if not result.get("_blocked"):
            _db_cache_put_bg(url, result)
            return result
    elif _cf_worker_urls:
        # Non-hostile domain → try CF Swarm (free) first, fall back to direct curl_cffi.
        logger.debug("[WATERFALL] CF swarm → %s", url)
        result = _fetch_via_workers_sync(url, domain)
        if not result.get("_blocked"):
            _db_cache_put_bg(url, result)
            return result
        logger.debug("[WATERFALL] workers blocked → direct curl_cffi %s", url)
        result = _fetch_direct_sync(url, domain)
        if not result.get("_blocked"):
            _db_cache_put_bg(url, result)
            return result
    else:
        # No CF workers configured: direct curl_cffi → residential proxy waterfall.
        logger.debug("[WATERFALL] direct curl_cffi → %s", url)
        result = _fetch_direct_sync(url, domain)
        if not result.get("_blocked"):
            _db_cache_put_bg(url, result)
            return result

    # ── Step 5: Ghost Layer ──────────────────────────────────────────────────
    if result.get("_cf_challenge"):
        logger.info("[WATERFALL] CF challenge on live site — skipping ghost layer for %s", url)
        return result
    logger.info("[WATERFALL] Steps 3+4 blocked — ghost layer → %s", url)
    result = _fetch_ghost_layer_sync(url)
    if result.get("markdown"):
        _db_cache_put_bg(url, result)
    return result


# Priority-queue scrape scheduler

class ScraperScheduler:
    """
    Min-heap priority queue that dispatches URL scrapes to a fixed worker pool.

    Queue item format: (priority: int, seq: int, url: str, future: Future)
    - priority  — lower number = processed first (P1 before P5)
    - seq       — monotonic counter used as tiebreaker; ensures FIFO within
                  the same priority level AND prevents Python from ever needing
                  to compare Future objects (which would raise TypeError).
    - future    — resolved by the worker with the scrape result dict

    Anti-ban mechanism: each worker sleeps _PRIORITY_DELAYS[priority] seconds
    AFTER completing a scrape.  P1 (0 s) is instant; P5 (3 s) is polite.
    High-priority items still jump ahead in the queue even while a worker is
    sleeping on a low-priority task, because other workers remain available.
    """

    def __init__(self, num_workers: int = 5):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._seq = 0
        self._num_workers = num_workers
        self._started = False

    # Lazy startup (requires a running event loop)

    async def _ensure_started(self) -> None:
        # No await between check and set — safe from asyncio re-entrancy
        if self._started:
            return
        self._started = True
        for _ in range(self._num_workers):
            asyncio.create_task(self._worker())

    # Worker loop

    async def _worker(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            priority, _seq, url, future = await self._queue.get()
            try:
                # Fast path: result already in LRU cache (confirmed by exact match)
                cached = _url_cache.get(url)
                if cached is not None:
                    logger.debug("[SCHEDULER] cache hit for %s", url)
                    if not future.done():
                        future.set_result(cached)
                    self._queue.task_done()
                    continue

                # Polite delay for low-priority work
                delay = _PRIORITY_DELAYS.get(priority, 0.0)
                if delay > 0:
                    await asyncio.sleep(delay)

                result = await asyncio.wait_for(
                    loop.run_in_executor(None, _fetch_one_sync, url),
                    timeout=_TIMEOUT + 5,
                )

                # Register in bloom filter; cache only pages with real content
                _scraped_bloom.add(url)
                if result.get("markdown"):
                    _url_cache.put(url, result)

                logger.debug(
                    "[SCHEDULER] scraped %s (p%d, %d chars)",
                    url, priority, len(result.get("markdown", "")),
                )
                if not future.done():
                    future.set_result(result)

            except Exception as exc:
                logger.warning("[SCHEDULER] worker error for %s: %s", url, exc)
                if not future.done():
                    future.set_result({"url": url, "markdown": "", "jsonld": {}})
            finally:
                self._queue.task_done()

    # Public API

    async def submit(self, url: str, priority: int) -> asyncio.Future:
        """
        Enqueue a URL for scraping and return an asyncio.Future.
        If the URL is probably-seen (bloom) AND the result is cached (LRU),
        the future is resolved immediately without touching the queue.
        """
        await self._ensure_started()

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        # Two-level fast path: bloom says "probably seen" → confirm in LRU cache
        if url in _scraped_bloom:
            cached = _url_cache.get(url)
            if cached is not None:
                future.set_result(cached)
                return future

        self._seq += 1
        await self._queue.put((priority, self._seq, url, future))
        return future

    def queue_size(self) -> int:
        return self._queue.qsize()


# Module-level scheduler — workers start lazily on first request
_scheduler = ScraperScheduler(num_workers=5)

# Load Cloudflare Worker config at import time (no-op if vars are empty)
_init_cf_workers()


def clear_memory_cache() -> dict:
    """
    Reset all in-process caches:
      • _url_cache  — LRU scrape-result store
      • _scraped_bloom — URL-seen Bloom filter

    Returns a dict with counts of evicted entries.
    """
    evicted = len(_url_cache)
    _url_cache._store.clear()
    _scraped_bloom._bits = bytearray(_scraped_bloom._size // 8 + 1)
    _policy_cache.clear()
    logger.info("[CACHE] in-memory cache cleared: %d LRU entries evicted", evicted)
    return {"lru_entries_evicted": evicted}


# Public API

async def scrape_urls(
    urls: list[str],
    priority: int = Priority.P1_USER_REQUEST,
    on_done: Callable[[str, int, int], Awaitable[None]] | None = None,
) -> list[dict]:
    """
    Parallel scrape via curl_cffi (Chrome fingerprint).
    Blasts all Tavily URLs simultaneously; results feed _pick_contenders
    which cuts the list to the top 10 before Gemini scoring.

    priority — use Priority.P1_USER_REQUEST for live searches (default),
               Priority.P5_BACKGROUND for background/refresh tasks.
    on_done  — optional async callback(url, done_count, total) fired as each
               URL resolves; use this to stream real-time progress to the client.
    Returns [{"url": "...", "markdown": "...", "jsonld": {...}}].
    """
    if not urls:
        return []

    futures = []
    for url in urls:
        if not is_likely_product_url(url):
            logger.info("[GATEKEEPER] dropping junk URL before scrape: %s", url)
            continue
        futures.append(await _scheduler.submit(url, priority))
    total = len(futures)

    if on_done is None:
        return list(await asyncio.gather(*futures))

    # Process completions as they arrive so the caller can stream live progress.
    results: list[dict] = []
    done_count = 0
    for coro in asyncio.as_completed(futures):
        result = await coro
        done_count += 1
        await on_done(result.get("url", ""), done_count, total)
        results.append(result)
    return results
