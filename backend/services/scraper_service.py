import asyncio
import logging

import trafilatura
from curl_cffi.requests import Session

from services.jsonld_service import extract_jsonld_facts

logger = logging.getLogger(__name__)

_TIMEOUT = 30
_MAX_CONCURRENT = 5
_IMPERSONATE = "chrome124"


def _fetch_one_sync(url: str) -> dict:
    """
    Fetch URL with curl_cffi (browser fingerprinting bypasses basic bot detection),
    extract main content with trafilatura, and pull JSON-LD from raw HTML.
    Runs synchronously — called from a thread pool via scrape_urls.
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
        return {"url": url, "markdown": "", "jsonld": {}}

    # JSON-LD is more reliably extracted from raw HTML before trafilatura strips tags
    jsonld = extract_jsonld_facts(html)

    markdown = (
        trafilatura.extract(html, include_tables=True, include_links=False) or ""
    )

    return {"url": url, "markdown": markdown, "jsonld": jsonld}


async def scrape_urls(urls: list[str]) -> list[dict]:
    """
    Scrape all URLs in parallel (up to _MAX_CONCURRENT simultaneously).
    Returns [{"url": "...", "markdown": "...", "jsonld": {...}}].
    """
    loop = asyncio.get_event_loop()
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

    async def _guarded(url: str) -> dict:
        async with semaphore:
            return await loop.run_in_executor(None, _fetch_one_sync, url)

    return await asyncio.gather(*[_guarded(u) for u in urls])
