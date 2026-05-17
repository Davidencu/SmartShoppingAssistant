import logging
from typing import Optional

from services.supabase_service import get_supabase_admin

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
