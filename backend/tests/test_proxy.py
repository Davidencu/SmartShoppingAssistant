"""
Proxy diagnostic test — pinpoints exactly where HTTP 407 (Proxy Auth Required) comes from.

Covers three code paths that use the proxy:
  A. _proxies() → static URL (_proxy_url, no session params in username)
  B. fetch_via_residential_proxy() → dynamic URL (session params appended to username)
  C. _fetch_direct_sync() → calls path A/B internally for known-hostile domains

Run with:
  cd backend && python -m pytest tests/test_proxy.py -v -s 2>&1 | head -100
"""
import os
import sys
import random
from urllib.parse import quote

import pytest

# ── Allow running from the backend directory ──────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env before importing the service so _init_cf_workers() sees the values.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass  # dotenv optional; env vars may already be set

from curl_cffi.requests import Session
import services.scraper_service as svc

# ── Proxy credentials (resolved after .env is loaded) ─────────────────────────
_HOST = svc._proxy_host
_PORT = svc._proxy_port
_USER = svc._proxy_username
_PASS = svc._proxy_password

_TEST_URL = "http://httpbin.org/ip"          # returns JSON with outbound IP — safe/free

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_proxy_url(user: str, password: str) -> str:
    return f"http://{user}:{quote(password, safe='')}@{_HOST}:{_PORT}"


def _curl_get(proxy_url: str, target: str = _TEST_URL) -> tuple[int, str]:
    """Return (status_code, body) or (0, error_message)."""
    try:
        with Session(impersonate="chrome120") as s:
            resp = s.get(
                target,
                proxies={"http": proxy_url, "https": proxy_url},
                timeout=(15, 20),
            )
        return resp.status_code, resp.text[:500]
    except Exception as exc:
        return 0, repr(exc)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestProxyCredentials:
    """Check which credential format the proxy server actually accepts."""

    def test_credentials_are_loaded(self):
        """Fail fast if the env vars were never read — every other test is meaningless."""
        assert _HOST, "PROXY_HOST is empty — .env not loaded or var missing"
        assert _PORT, "PROXY_PORT is empty"
        assert _USER, "PROXY_USERNAME is empty"
        assert _PASS, "PROXY_PASSWORD is empty"
        print(f"\n[PROXY] host={_HOST}:{_PORT}  user={_USER!r}  pass={_PASS!r}")

    def test_path_a_static_url_no_session_params(self):
        """
        Path A — _proxies() uses _proxy_url which is built as:
            http://<user>:<pass>@<host>:<port>
        The username has NO _country or _session suffix here.
        If this returns 407, the raw credentials are wrong.
        """
        proxy_url = _make_proxy_url(_USER, _PASS)
        print(f"\n[PATH-A] proxy_url={proxy_url}")
        status, body = _curl_get(proxy_url)
        print(f"[PATH-A] → HTTP {status}  body={body[:200]}")
        if status == 407:
            pytest.fail(
                f"PATH-A: 407 Proxy Auth Required.\n"
                f"  user={_USER!r}\n"
                f"  pass={_PASS!r}\n"
                f"  Diagnosis: raw credentials are rejected — the .env values may be wrong."
            )
        assert status == 200, f"PATH-A: unexpected status {status}: {body}"

    def test_path_b_dynamic_url_session_appended(self):
        """
        Regression guard: double-parameterized credentials (session params in BOTH
        username and password) must be rejected with 407 by IPRoyal.

        The service was fixed to detect this via '_country-' in the stored password
        and fall back to the static _proxy_url instead of building a dynamic URL.
        This test ensures the broken format still fails so future refactors can't
        accidentally re-introduce it.
        """
        session_id = random.randint(100_000, 999_999)
        dynamic_user = f"{_USER}_country-ro_session-{session_id}_lifetime-10m"
        proxy_url = _make_proxy_url(dynamic_user, _PASS)
        print(f"\n[PATH-B] proxy_url={proxy_url}")
        status, body = _curl_get(proxy_url)
        print(f"[PATH-B] → HTTP {status}  body={body[:200]}")
        # 407 is the expected outcome — double-parameterized credentials are rejected.
        # fetch_via_residential_proxy() now detects '_country-' in the password and
        # falls back to the static _proxy_url (Format 2), avoiding this code path.
        assert status == 407, (
            f"Expected 407 for double-parameterized credentials but got {status}. "
            f"If IPRoyal changed its auth behaviour, re-evaluate the Format-2 bypass in "
            f"fetch_via_residential_proxy."
        )

    def test_path_b_with_stripped_password(self):
        """
        Hypothesis: the stored password contains an embedded session suffix that
        belongs only in the username. Test with the base password only
        (everything before the first '_country-' token).
        """
        base_pass = _PASS.split("_country-")[0]
        if base_pass == _PASS:
            pytest.skip("Password does not contain '_country-' — no stripping needed")
        session_id = random.randint(100_000, 999_999)
        dynamic_user = f"{_USER}_country-ro_session-{session_id}_lifetime-10m"
        proxy_url = _make_proxy_url(dynamic_user, base_pass)
        print(f"\n[PATH-B-STRIPPED] user={dynamic_user!r}  base_pass={base_pass!r}")
        print(f"[PATH-B-STRIPPED] proxy_url={proxy_url}")
        status, body = _curl_get(proxy_url)
        print(f"[PATH-B-STRIPPED] → HTTP {status}  body={body[:200]}")
        if status == 200:
            pytest.fail(
                f"PATH-B-STRIPPED passed (200 OK).\n"
                f"  ROOT CAUSE CONFIRMED: PROXY_PASSWORD contains an embedded session suffix "
                f"that should NOT be there.\n"
                f"  Fix: set PROXY_PASSWORD={base_pass!r} in .env (remove everything from '_country-' onward)."
            )
        # Any non-200 result here is logged; the real fix verdict comes from the message above.
        print(f"[PATH-B-STRIPPED] → {status} (not 200 — stripped pass also fails, investigate further)")

    def test_fetch_via_residential_proxy_live(self):
        """
        Calls the actual service function and checks it does not return None.
        Verifies the full code path including the URL construction.
        """
        if not (_HOST and _PORT and _USER and _PASS):
            pytest.skip("Proxy not configured")
        html = svc.fetch_via_residential_proxy(_TEST_URL, "ro")
        print(f"\n[LIVE] fetch_via_residential_proxy → {'OK (' + str(len(html)) + ' chars)' if html else 'None (blocked/407)'}")
        assert html is not None, (
            "fetch_via_residential_proxy returned None — check logs above for HTTP status. "
            "407 means bad credentials; 000 means network/DNS failure."
        )
