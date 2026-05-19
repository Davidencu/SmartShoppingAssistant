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
import logging
import math
import re
from collections import OrderedDict
from enum import IntEnum
from typing import Optional
from urllib.parse import urljoin

import trafilatura
from bs4 import BeautifulSoup
from curl_cffi.requests import Session

from services.jsonld_service import extract_bs4_facts, extract_jsonld_facts

logger = logging.getLogger(__name__)

_TIMEOUT = 30
_IMPERSONATE = "chrome124"


# ─── Priority levels ────────────────────────────────────────────────────────────

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


# ─── Bloom Filter ───────────────────────────────────────────────────────────────

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

    # ── internal helpers ──────────────────────────────────────────────────────

    def _positions(self, item: str) -> list[int]:
        encoded = item.encode()
        h1 = int.from_bytes(hashlib.md5(encoded, usedforsecurity=False).digest(), "little")
        h2 = int.from_bytes(hashlib.sha1(encoded).digest(), "little")  # noqa: S324
        return [(h1 + i * h2) % self._size for i in range(self._hash_count)]

    # ── public API ────────────────────────────────────────────────────────────

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


# ─── URL result LRU cache ───────────────────────────────────────────────────────

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


# ─── Module-level singletons ────────────────────────────────────────────────────

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


# ─── Scraper core (synchronous, runs in thread pool) ────────────────────────────

def _fetch_one_sync(url: str) -> dict:
    """
    Fetch URL with curl_cffi (Chrome fingerprint bypasses basic bot detection),
    extract main content with trafilatura, and pull JSON-LD from raw HTML.
    Runs synchronously — called via run_in_executor from the async scheduler.
    """
    html = ""
    try:
        with Session(impersonate=_IMPERSONATE) as session:
            resp = session.get(url, timeout=_TIMEOUT)
            if resp.status_code == 200:
                html = resp.text or ""
            else:
                logger.warning("HTTP %d for %s", resp.status_code, url)
    except Exception as exc:
        logger.warning("Fetch failed for %s: %s", url, exc)

    if not html:
        return {"url": url, "markdown": "", "jsonld": {}, "shipping_policy_url": None, "return_policy_text": None}

    # Extract structured data from raw HTML before trafilatura strips tags.
    # BS4 covers Open Graph meta, itemprop, aria-labels, and data-* attributes —
    # all common on e-commerce pages that don't emit full JSON-LD.
    # JSON-LD is authoritative: it wins on any key conflict with BS4.
    jsonld = {**extract_bs4_facts(html), **extract_jsonld_facts(html)}
    markdown = trafilatura.extract(html, include_tables=True, include_links=False) or ""

    # ── Two-hop: find shipping + return policy pages once per domain ─────────
    domain = _extract_domain(url)
    if domain not in _policy_cache:
        shipping_url, return_url = _find_policy_links(html, url)
        return_text: str | None = None
        if return_url:
            try:
                with Session(impersonate=_IMPERSONATE) as rs:
                    rr = rs.get(return_url, timeout=10)
                    if rr.status_code == 200:
                        return_text = trafilatura.extract(rr.text, include_comments=False) or None
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


# ─── Priority-queue scrape scheduler ───────────────────────────────────────────

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

    # ── Lazy startup (requires a running event loop) ─────────────────────────

    async def _ensure_started(self) -> None:
        # No await between check and set — safe from asyncio re-entrancy
        if self._started:
            return
        self._started = True
        for _ in range(self._num_workers):
            asyncio.create_task(self._worker())

    # ── Worker loop ──────────────────────────────────────────────────────────

    async def _worker(self) -> None:
        loop = asyncio.get_event_loop()
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

                result = await loop.run_in_executor(None, _fetch_one_sync, url)

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

    # ── Public API ────────────────────────────────────────────────────────────

    async def submit(self, url: str, priority: int) -> asyncio.Future:
        """
        Enqueue a URL for scraping and return an asyncio.Future.
        If the URL is probably-seen (bloom) AND the result is cached (LRU),
        the future is resolved immediately without touching the queue.
        """
        await self._ensure_started()

        loop = asyncio.get_event_loop()
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


# ─── Public API ────────────────────────────────────────────────────────────────

async def scrape_urls(
    urls: list[str],
    priority: int = Priority.P1_USER_REQUEST,
) -> list[dict]:
    """
    Scrape all URLs via the priority-queue scheduler.

    priority — use Priority.P1_USER_REQUEST for live user searches (default),
               Priority.P5_BACKGROUND for background/refresh tasks.
    Returns [{"url": "...", "markdown": "...", "jsonld": {...}}].
    """
    if not urls:
        return []
    futures = [await _scheduler.submit(url, priority) for url in urls]
    return list(await asyncio.gather(*futures))
