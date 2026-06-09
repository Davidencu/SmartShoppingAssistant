"""
Cloudflare Worker Swarm health tests.

Tests three things:
  Part 1 — Raw worker reachability (unit-style, no scraper machinery):
    POST to each worker URL directly with urllib.request and verify the
    JSON envelope comes back with status == 200 and non-empty html.
    Uses https://example.com — always up, never blocks Cloudflare IPs.

  Part 2 — Round-robin rotation (_next_worker):
    Verifies that successive calls to _next_worker() cycle through all
    configured worker URLs and wrap around correctly.

  Part 3 — End-to-end via _fetch_via_workers_sync:
    Calls the actual scraper function with a real public product URL and
    asserts that at least one worker returns parseable markdown.

Run (needs CF_WORKER_URLS + CF_WORKER_SECRET in .env):
    pytest tests/live/test_cf_swarm.py -v -s
"""
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

import pytest

# Make sure the backend package root is on sys.path when running standalone.
_BACKEND = Path(__file__).parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

pytestmark = pytest.mark.live

_TEST_URL = "https://example.com"

# A real, publicly scrapable product page for the end-to-end test.
# Carturesti is a Romanian bookshop — reliably accessible without bot-protection.
_PRODUCT_URL = "https://carturesti.ro/carte/dune-frank-herbert"


def _load_swarm_config() -> tuple[list[str], str]:
    """Return (worker_urls, secret) from settings; skip if not configured."""
    from core.config import settings
    raw = (settings.cf_worker_urls or "").strip()
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    secret = (settings.cf_worker_secret or "").strip()
    if not urls:
        pytest.skip("CF_WORKER_URLS not set — skipping CF swarm tests")
    if not secret:
        pytest.skip("CF_WORKER_SECRET not set — skipping CF swarm tests")
    return urls, secret


def _post_to_worker(worker_url: str, target_url: str, secret: str, timeout: int = 15) -> dict:
    """Send a single fetch request to a worker and return the parsed JSON body."""
    headers_for_target = {
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    payload = json.dumps({"url": target_url, "headers": headers_for_target}).encode()
    req = urllib.request.Request(
        worker_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Worker-Secret": secret,
            # Cloudflare's Browser Integrity Check blocks Python-urllib/3.x;
            # a Chrome UA is required to reach the workers.dev endpoint.
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ═══════════════════════════════════════════════════════════════════════════════
# PART 1 — Raw worker reachability
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkerReachability:
    """
    Direct POST to each worker; no scraper machinery involved.
    Each worker must respond with JSON {status: 200, html: <non-empty>}.
    """

    def setup_method(self):
        self.worker_urls, self.secret = _load_swarm_config()

    def _check_worker(self, worker_url: str):
        print(f"\n[CF-SWARM] Testing worker: {worker_url}")
        try:
            body = _post_to_worker(worker_url, _TEST_URL, self.secret)
        except urllib.error.URLError as exc:
            pytest.fail(f"Worker unreachable: {worker_url}\n  {exc}")
        except Exception as exc:
            pytest.fail(f"Unexpected error contacting {worker_url}: {exc}")

        print(f"  Response keys: {list(body.keys())}")
        print(f"  status: {body.get('status')}")
        html = body.get("html") or ""
        print(f"  html length: {len(html)} chars")
        if body.get("final_url"):
            print(f"  final_url: {body['final_url']}")

        assert body.get("status") == 200, (
            f"Worker {worker_url} returned status={body.get('status')} "
            f"for {_TEST_URL}"
        )
        assert html, f"Worker {worker_url} returned empty html for {_TEST_URL}"
        print(f"  PASS — {len(html)} chars received")

    def test_worker_1_reachable(self):
        if len(self.worker_urls) < 1:
            pytest.skip("No workers configured")
        self._check_worker(self.worker_urls[0])

    def test_worker_2_reachable(self):
        if len(self.worker_urls) < 2:
            pytest.skip("Less than 2 workers configured")
        self._check_worker(self.worker_urls[1])

    def test_worker_3_reachable(self):
        if len(self.worker_urls) < 3:
            pytest.skip("Less than 3 workers configured")
        self._check_worker(self.worker_urls[2])

    def test_wrong_secret_rejected(self):
        """A request with a bad secret must be rejected (non-200 HTTP or error body)."""
        worker_url = self.worker_urls[0]
        print(f"\n[CF-SWARM] Testing auth rejection: {worker_url}")
        payload = json.dumps({"url": _TEST_URL, "headers": {}}).encode()
        req = urllib.request.Request(
            worker_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Worker-Secret": "wrong-secret-intentionally-bad",
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode())
            # If the worker returns HTTP 200 with the wrong secret, it must
            # signal rejection in the body (status != 200 or error key present).
            rejected = body.get("status") != 200 or body.get("error")
            assert rejected, (
                "Worker accepted a request with a wrong secret — "
                "authentication is not enforced!"
            )
            print(f"  PASS — body-level rejection: status={body.get('status')}, "
                  f"error={body.get('error')}")
        except urllib.error.HTTPError as exc:
            # HTTP 401/403 is the ideal rejection response.
            assert exc.code in (401, 403), (
                f"Expected 401/403 for bad secret, got HTTP {exc.code}"
            )
            print(f"  PASS — HTTP {exc.code} rejection")


# ═══════════════════════════════════════════════════════════════════════════════
# PART 2 — Round-robin rotation
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoundRobin:
    """
    Unit test for _next_worker() — no network calls.
    Injects workers into the module-level list and verifies rotation.
    """

    def setup_method(self):
        self.worker_urls, _ = _load_swarm_config()

    def test_round_robin_cycles_all_workers(self):
        import services.scraper_service as svc

        original_urls = svc._cf_worker_urls[:]
        original_idx = svc._cf_worker_idx

        try:
            fake_workers = [
                "https://worker-a.workers.dev",
                "https://worker-b.workers.dev",
                "https://worker-c.workers.dev",
            ]
            svc._cf_worker_urls = fake_workers
            svc._cf_worker_idx = 0

            seen = [svc._next_worker() for _ in range(len(fake_workers) * 2)]
            print(f"\n[ROUND-ROBIN] Rotation: {seen}")

            # Each worker should appear exactly twice in two full cycles.
            from collections import Counter
            counts = Counter(seen)
            for w in fake_workers:
                assert counts[w] == 2, (
                    f"Worker {w} appeared {counts[w]} times, expected 2"
                )
            print(f"  PASS — all workers rotated evenly: {dict(counts)}")
        finally:
            svc._cf_worker_urls = original_urls
            svc._cf_worker_idx = original_idx

    def test_next_worker_wraps_on_overflow(self):
        import services.scraper_service as svc

        original_urls = svc._cf_worker_urls[:]
        original_idx = svc._cf_worker_idx

        try:
            svc._cf_worker_urls = ["https://only-worker.workers.dev"]
            svc._cf_worker_idx = 10_000  # large index

            result = svc._next_worker()
            assert result == "https://only-worker.workers.dev", (
                f"Expected single worker, got {result}"
            )
            print(f"\n[ROUND-ROBIN] Overflow wrap PASS — got {result}")
        finally:
            svc._cf_worker_urls = original_urls
            svc._cf_worker_idx = original_idx

    def test_next_worker_returns_none_when_no_workers(self):
        import services.scraper_service as svc

        original_urls = svc._cf_worker_urls[:]
        original_idx = svc._cf_worker_idx

        try:
            svc._cf_worker_urls = []
            svc._cf_worker_idx = 0

            result = svc._next_worker()
            assert result is None, f"Expected None, got {result}"
            print("\n[ROUND-ROBIN] Empty list PASS — returned None")
        finally:
            svc._cf_worker_urls = original_urls
            svc._cf_worker_idx = original_idx


# ═══════════════════════════════════════════════════════════════════════════════
# PART 3 — End-to-end via _fetch_via_workers_sync
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndToEnd:
    """
    Calls _fetch_via_workers_sync with a real public product URL.
    Verifies that the swarm can fetch a page and return parseable markdown.
    """

    def setup_method(self):
        self.worker_urls, _ = _load_swarm_config()

    def test_swarm_fetches_real_product_page(self):
        from services.scraper_service import _fetch_via_workers_sync, _init_cf_workers

        _init_cf_workers()  # ensure module-level lists are populated

        print(f"\n[CF-SWARM E2E] Fetching: {_PRODUCT_URL}")
        result = _fetch_via_workers_sync(_PRODUCT_URL, "carturesti.ro")

        print(f"  blocked: {result.get('_blocked')}")
        print(f"  markdown length: {len(result.get('markdown') or '')} chars")
        print(f"  jsonld keys: {list((result.get('jsonld') or {}).keys())}")
        print(f"  has_buy_button: {result.get('has_buy_button')}")

        if result.get("_blocked"):
            pytest.skip(
                "All workers were blocked fetching the test URL — "
                "the workers may be rate-limited or the site is down. "
                "Check worker logs at dash.cloudflare.com."
            )

        markdown = result.get("markdown") or ""
        assert len(markdown) > 200, (
            f"Expected > 200 chars of markdown, got {len(markdown)}. "
            "Worker returned a page but content extraction failed."
        )
        print(f"  PASS — {len(markdown)} chars of markdown extracted")
        print(f"  Preview: {markdown[:200]!r}")

    def test_all_workers_healthy(self):
        """Quick smoke-test: every configured worker responds to a raw POST."""
        worker_urls, secret = _load_swarm_config()
        results = []
        for url in worker_urls:
            try:
                body = _post_to_worker(url, _TEST_URL, secret, timeout=12)
                ok = body.get("status") == 200 and bool(body.get("html"))
                html_len = len(body.get("html") or "")
                results.append((url, ok, html_len, None))
                print(f"\n[CF-SWARM HEALTH] {url}")
                print(f"  status={body.get('status')} html={html_len} chars  {'OK' if ok else 'FAIL'}")
            except Exception as exc:
                results.append((url, False, 0, str(exc)))
                print(f"\n[CF-SWARM HEALTH] {url}")
                print(f"  ERROR: {exc}")

        failed = [(url, err) for url, ok, _, err in results if not ok]
        if failed:
            lines = "\n".join(
                f"  {url}  error={err or 'status!=200 or empty html'}"
                for url, err in failed
            )
            pytest.fail(
                f"{len(failed)}/{len(worker_urls)} worker(s) unhealthy:\n{lines}"
            )
        print(f"\n  PASS — all {len(worker_urls)} workers healthy")
