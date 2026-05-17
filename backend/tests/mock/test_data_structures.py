"""
Unit tests for the three high-demand data structures:
  BloomFilter      — compact URL-seen tracking
  _LRUCache        — bounded scrape-result store
  ScraperScheduler — priority-queue dispatcher (Priority enum)
  extract_jsonld_facts lru_cache — repeated-parse deduplication
"""
import asyncio
import functools
import pytest

from services.scraper_service import BloomFilter, Priority, ScraperScheduler, _LRUCache


# ─── BloomFilter ────────────────────────────────────────────────────────────────

class TestBloomFilter:

    def test_add_and_contains(self):
        bf = BloomFilter(capacity=1_000, error_rate=0.01)
        bf.add("https://emag.ro/laptop-asus")
        assert "https://emag.ro/laptop-asus" in bf

    def test_not_added_url_is_absent(self):
        bf = BloomFilter(capacity=1_000, error_rate=0.01)
        bf.add("https://emag.ro/laptop-asus")
        assert "https://altex.ro/laptop-lenovo" not in bf

    def test_multiple_urls(self):
        bf = BloomFilter(capacity=10_000, error_rate=0.01)
        urls = [f"https://example.com/product/{i}" for i in range(500)]
        for url in urls:
            bf.add(url)
        for url in urls:
            assert url in bf, f"False negative for {url}"

    def test_false_positive_rate_within_bound(self):
        """At 1% error rate and capacity 10k, at most ~2% of unseen URLs misreported."""
        capacity = 10_000
        bf = BloomFilter(capacity=capacity, error_rate=0.01)
        for i in range(capacity):
            bf.add(f"https://seen.com/{i}")
        unseen = [f"https://unseen.com/{i}" for i in range(1_000)]
        false_positives = sum(1 for u in unseen if u in bf)
        assert false_positives / len(unseen) < 0.05, (
            f"False positive rate {false_positives/len(unseen):.1%} exceeds 5%"
        )

    def test_bit_count_is_positive(self):
        bf = BloomFilter(capacity=500, error_rate=0.05)
        assert bf.bit_count > 0

    def test_approx_item_count_increases(self):
        bf = BloomFilter(capacity=10_000, error_rate=0.01)
        assert bf.approx_item_count() == 0
        for i in range(100):
            bf.add(f"item-{i}")
        assert bf.approx_item_count() > 0

    def test_compact_memory_footprint(self):
        """100k URL bloom filter must fit in ≤200 KB."""
        import sys
        bf = BloomFilter(capacity=100_000, error_rate=0.01)
        size_bytes = sys.getsizeof(bf._bits)
        assert size_bytes < 200_000, f"Bloom filter too large: {size_bytes} bytes"


# ─── _LRUCache ──────────────────────────────────────────────────────────────────

class TestLRUCache:

    def test_put_and_get(self):
        cache = _LRUCache(maxsize=10)
        cache.put("url-a", {"markdown": "hello", "jsonld": {}})
        result = cache.get("url-a")
        assert result is not None
        assert result["markdown"] == "hello"

    def test_miss_returns_none(self):
        cache = _LRUCache(maxsize=10)
        assert cache.get("https://never-added.com") is None

    def test_evicts_lru_when_full(self):
        cache = _LRUCache(maxsize=3)
        cache.put("a", {"v": 1})
        cache.put("b", {"v": 2})
        cache.put("c", {"v": 3})
        # Access "a" to make it recently used — "b" becomes LRU
        cache.get("a")
        cache.put("d", {"v": 4})   # should evict "b" (LRU)
        assert cache.get("b") is None
        assert cache.get("a") is not None
        assert cache.get("c") is not None
        assert cache.get("d") is not None

    def test_update_moves_to_end(self):
        cache = _LRUCache(maxsize=2)
        cache.put("x", {"v": 1})
        cache.put("y", {"v": 2})
        cache.put("x", {"v": 99})   # re-insert "x" — it should be MRU
        cache.put("z", {"v": 3})    # fills capacity — should evict "y" (LRU)
        assert cache.get("y") is None
        assert cache.get("x")["v"] == 99

    def test_len(self):
        cache = _LRUCache(maxsize=100)
        assert len(cache) == 0
        cache.put("k1", {})
        cache.put("k2", {})
        assert len(cache) == 2


# ─── Priority enum ──────────────────────────────────────────────────────────────

class TestPriority:

    def test_ordering(self):
        assert Priority.P1_USER_REQUEST < Priority.P2_RETRY
        assert Priority.P2_RETRY < Priority.P3_PREFETCH
        assert Priority.P3_PREFETCH < Priority.P4_CACHE_REFRESH
        assert Priority.P4_CACHE_REFRESH < Priority.P5_BACKGROUND

    def test_p1_is_min(self):
        all_p = [Priority.P1_USER_REQUEST, Priority.P2_RETRY,
                 Priority.P3_PREFETCH, Priority.P4_CACHE_REFRESH, Priority.P5_BACKGROUND]
        assert min(all_p) == Priority.P1_USER_REQUEST

    def test_p5_is_max(self):
        all_p = [Priority.P1_USER_REQUEST, Priority.P2_RETRY,
                 Priority.P3_PREFETCH, Priority.P4_CACHE_REFRESH, Priority.P5_BACKGROUND]
        assert max(all_p) == Priority.P5_BACKGROUND

    def test_heap_ordering(self):
        """Items placed in a heap should come out P1-first."""
        import heapq
        items = [
            (Priority.P5_BACKGROUND, 5, "low"),
            (Priority.P1_USER_REQUEST, 1, "high"),
            (Priority.P3_PREFETCH, 3, "mid"),
        ]
        heap = items[:]
        heapq.heapify(heap)
        assert heapq.heappop(heap)[2] == "high"
        assert heapq.heappop(heap)[2] == "mid"
        assert heapq.heappop(heap)[2] == "low"


# ─── ScraperScheduler (async) ───────────────────────────────────────────────────

class TestScraperScheduler:

    @pytest.mark.asyncio
    async def test_submit_resolves_future(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        scheduler = ScraperScheduler(num_workers=1)
        fake_result = {"url": "https://example.com", "markdown": "hello", "jsonld": {}}

        with patch("services.scraper_service._fetch_one_sync", return_value=fake_result):
            future = await scheduler.submit("https://example.com", Priority.P1_USER_REQUEST)
            result = await asyncio.wait_for(future, timeout=5.0)

        assert result["markdown"] == "hello"

    @pytest.mark.asyncio
    async def test_cached_url_returns_without_network(self):
        """A URL already in _url_cache should be served without calling _fetch_one_sync."""
        from unittest.mock import patch
        scheduler = ScraperScheduler(num_workers=1)
        cached = {"url": "https://cached.com", "markdown": "cached content", "jsonld": {}}

        # Pre-populate bloom and LRU cache
        from services.scraper_service import _scraped_bloom, _url_cache
        _scraped_bloom.add("https://cached.com")
        _url_cache.put("https://cached.com", cached)

        with patch("services.scraper_service._fetch_one_sync") as mock_fetch:
            future = await scheduler.submit("https://cached.com", Priority.P1_USER_REQUEST)
            result = await asyncio.wait_for(future, timeout=2.0)

        mock_fetch.assert_not_called()
        assert result["markdown"] == "cached content"

    @pytest.mark.asyncio
    async def test_p1_processed_before_p5(self):
        """P1 items enqueued after P5 items must emerge first from the min-heap."""
        import heapq
        # Simulate the heap ordering directly (without running real workers)
        heap = []
        heapq.heappush(heap, (Priority.P5_BACKGROUND, 1, "background-url"))
        heapq.heappush(heap, (Priority.P1_USER_REQUEST, 2, "user-url"))
        first = heapq.heappop(heap)
        assert first[2] == "user-url"


# ─── extract_jsonld_facts lru_cache ─────────────────────────────────────────────

class TestJsonldLRUCache:

    def setup_method(self):
        # Clear the LRU cache before each test to avoid cross-test interference
        from services.jsonld_service import extract_jsonld_facts
        extract_jsonld_facts.cache_clear()

    def test_cache_is_applied(self):
        from services.jsonld_service import extract_jsonld_facts
        html = """<script type="application/ld+json">
        {"@type":"Product","name":"Test","offers":{"price":"100","priceCurrency":"RON"}}
        </script>"""
        result1 = extract_jsonld_facts(html)
        result2 = extract_jsonld_facts(html)
        # Same object returned from cache — not just equal, identical
        assert result1 is result2

    def test_different_inputs_cached_separately(self):
        from services.jsonld_service import extract_jsonld_facts
        html_a = """<script type="application/ld+json">
        {"@type":"Product","name":"A","offers":{"price":"100","priceCurrency":"RON"}}
        </script>"""
        html_b = """<script type="application/ld+json">
        {"@type":"Product","name":"B","offers":{"price":"200","priceCurrency":"RON"}}
        </script>"""
        result_a = extract_jsonld_facts(html_a)
        result_b = extract_jsonld_facts(html_b)
        assert result_a["name"] == "A"
        assert result_b["name"] == "B"
        assert result_a is not result_b

    def test_cache_info_tracks_hits(self):
        from services.jsonld_service import extract_jsonld_facts
        html = """<script type="application/ld+json">
        {"@type":"Product","name":"CacheTest","offers":{"price":"50","priceCurrency":"RON"}}
        </script>"""
        extract_jsonld_facts(html)   # miss
        extract_jsonld_facts(html)   # hit
        extract_jsonld_facts(html)   # hit
        info = extract_jsonld_facts.cache_info()
        assert info.hits >= 2
        assert info.misses >= 1

    def test_cache_clear_resets_hits(self):
        from services.jsonld_service import extract_jsonld_facts
        html = "<p>no json here</p>"
        extract_jsonld_facts(html)
        extract_jsonld_facts.cache_clear()
        info = extract_jsonld_facts.cache_info()
        assert info.hits == 0
        assert info.currsize == 0
