import logging
from typing import Optional

from services.supabase_service import get_supabase_admin
from services.jsonld_service import extract_bs4_facts, extract_jsonld_facts

logger = logging.getLogger(__name__)

_SIMILARITY_THRESHOLD = 0.92


def lookup_cache(
    embedding: list[float],
    category: str,
    budget_max: Optional[float] = None,
    budget_currency: Optional[str] = None,
) -> Optional[list[dict]]:
    """
    Query the semantic cache using pgvector cosine similarity + metadata filters.
    Returns the cached products list on a hit, or None on a miss.
    Runs synchronously — call via run_in_threadpool from async handlers.
    """
    supabase = get_supabase_admin()
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
    try:
        result = supabase.rpc(
            "find_similar_search",
            {
                "query_vec": vec_str,
                "p_category": category,
                "p_budget_max": budget_max,
                "p_budget_currency": budget_currency,
                "p_threshold": _SIMILARITY_THRESHOLD,
            },
        ).execute()
        if result.data:
            return result.data[0]["results_json"]
    except Exception as exc:
        logger.warning("Cache lookup error: %s", exc)
    return None


def save_cache(
    query_text: str,
    embedding: list[float],
    category: str,
    budget_max: Optional[float],
    budget_currency: Optional[str],
    preference: Optional[str],
    results_json: list[dict],
) -> None:
    """
    Persist a fresh search result to the semantic cache (6-hour TTL set by DB default).
    Runs synchronously — safe to call from a FastAPI BackgroundTask.
    """
    supabase = get_supabase_admin()
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
    try:
        supabase.table("search_cache").insert(
            {
                "query_text": query_text,
                "query_embedding": vec_str,
                "category": category,
                "budget_max": budget_max,
                "budget_currency": budget_currency or "USD",
                "preference": preference,
                "results_json": results_json,
            }
        ).execute()
    except Exception as exc:
        logger.warning("Cache save error: %s", exc)


def clear_all_caches() -> dict:
    """
    Wipe every cache layer:
      1. Supabase search_cache table  — all persisted product results
      2. In-process LRU scrape cache  — scraped page markdown / JSON-LD
      3. Bloom filter                 — URL-seen tracker
      4. functools lru_cache          — parsed JSON-LD and BS4 facts
    Returns a summary dict.
    """
    from services.scraper_service import clear_memory_cache
    from services.gemini_service import clear_logistics_cache

    summary: dict = {}

    # 1. Supabase — delete every row from search_cache
    try:
        supabase = get_supabase_admin()
        # Supabase requires a filter; neq("id", 0) matches every row safely
        supabase.table("search_cache").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        summary["supabase_search_cache"] = "cleared"
        logger.info("[CACHE] Supabase search_cache wiped")
    except Exception as exc:
        summary["supabase_search_cache"] = f"error: {exc}"
        logger.error("[CACHE] Supabase clear failed: %s", exc)

    # 2 & 3. In-process LRU + Bloom filter + policy cache
    summary.update(clear_memory_cache())

    # 4. Logistics extraction cache
    summary.update(clear_logistics_cache())

    # 5. functools lru_cache for HTML parse results
    extract_jsonld_facts.cache_clear()
    extract_bs4_facts.cache_clear()
    summary["jsonld_lru_cache"] = "cleared"
    summary["bs4_lru_cache"] = "cleared"

    logger.info("[CACHE] all caches cleared: %s", summary)
    return summary
