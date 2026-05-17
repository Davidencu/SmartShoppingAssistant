import logging

from tavily import TavilyClient

from core.config import settings

logger = logging.getLogger(__name__)

_client = TavilyClient(api_key=settings.tavily_api_key)


def search_products(
    query: str,
    max_results: int = 10,
    include_domains: list[str] | None = None,
) -> list[dict]:
    """
    Find up to max_results product listing URLs via Tavily.
    Returns [{"url": "...", "title": "...", "content": "..."}].
    include_domains pins the search to specific sites (e.g. ["emag.ro", "decathlon.ro"]).
    Runs synchronously — call via run_in_threadpool from async handlers.
    """
    try:
        kwargs: dict = dict(
            query=query,
            search_depth="advanced",
            max_results=max_results,
            include_answer=False,
        )
        if include_domains:
            kwargs["include_domains"] = include_domains
        result = _client.search(**kwargs)
        return result.get("results", [])
    except Exception as exc:
        logger.error("Tavily search failed: %s", exc)
        return []
