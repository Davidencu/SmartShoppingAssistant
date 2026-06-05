import logging

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


async def render_urls(urls: list[str]) -> list[dict]:
    """
    Send URLs to the Stagehand Node.js microservice for full JS rendering.
    Returns [{url, html}] — html is empty string on individual failure.
    Called by scraper_service as a Tier-2 fallback.
    """
    if not urls:
        return []
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{settings.stagehand_service_url}/render",
                json={"urls": urls},
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
    except Exception as exc:
        logger.warning("[STAGEHAND] render_urls failed: %s", exc)
        return [{"url": u, "html": "", "error": str(exc)} for u in urls]
