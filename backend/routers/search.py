import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from models.search import ChatRequest, ChatResponse, IntentParams, Product, ProductScores
from routers.auth import get_current_user
from services import cache_service, gemini_service, scraper_service, tavily_service
from services.supabase_service import get_supabase_admin

router = APIRouter(prefix="/search", tags=["search"])
logger = logging.getLogger(__name__)

def _build_search_query(
    localized_query: str | None,
    params: IntentParams,
    local_domains: list[str] | None,
) -> tuple[str, list[str] | None]:
    """
    Return the Tavily search query and domain list.

    Uses Gemini's localized_search_query as the base (correct e-commerce terminology,
    no budget injection). Appends "buy" as a Python-level commercial intent signal so
    Google's index surfaces product listing pages instead of manufacturer brand pages
    with high domain authority but no checkout.
    Falls back to preference + category if Gemini produced no query.
    """
    base = localized_query.strip() if localized_query else (
        " ".join(filter(None, [params.preference, params.category])) or "product"
    )
    return f"{base} buy", local_domains or None


# ─── Pipeline Helper ──────────────────────────────────────────────────────────

async def _run_product_pipeline(
    query: str,
    params: IntentParams,
    city: str,
    country: str,
    local_domains: list[str] | None,
    excluded_urls: set[str] | None = None,
    is_global: bool = False,
) -> list[dict]:
    """
    Tavily → Jina → Gemini scoring pipeline.

    Raises HTTPException(503) for hard failures (no Tavily URLs, no Jina content).
    Returns an empty list when the inventory/scoring gate eliminates all candidates
    (soft failure — caller can retry globally).
    excluded_urls: URLs the user already saw and rejected — stripped before scraping.
    """
    tavily_results: list[dict] = []
    if local_domains:
        tavily_results = await run_in_threadpool(
            tavily_service.search_products, query, 10, local_domains
        )
        logger.info("[TAVILY] local (%s): %d results", ", ".join(local_domains), len(tavily_results))

    if len(tavily_results) < 3:
        global_results = await run_in_threadpool(
            tavily_service.search_products, query, 10
        )
        logger.info("[TAVILY] global: %d results", len(global_results))
        seen = {r["url"] for r in tavily_results}
        for r in global_results:
            if r["url"] not in seen:
                tavily_results.append(r)
                seen.add(r["url"])
        tavily_results = tavily_results[:10]

    # Strip any URL the user already saw and rejected
    if excluded_urls:
        before_excl = len(tavily_results)
        tavily_results = [r for r in tavily_results if r["url"] not in excluded_urls]
        dropped = before_excl - len(tavily_results)
        if dropped:
            logger.info("[TAVILY] dropped %d excluded URL(s) from results", dropped)

    logger.info("[TAVILY] %d total after merge", len(tavily_results))
    if not tavily_results:
        raise HTTPException(status_code=503, detail="Product search returned no results")

    urls = [r["url"] for r in tavily_results]
    scraped: list[dict] = await scraper_service.scrape_urls(urls)

    url_to_title = {r["url"]: r.get("title", "") for r in tavily_results}
    for s in scraped:
        s["title"] = url_to_title.get(s["url"], "")

    scraped_with_content = [s for s in scraped if len(s.get("markdown") or "") > 200]
    logger.info(
        "[SCRAPER] %d/%d pages have usable content (>200 chars)",
        len(scraped_with_content), len(scraped),
    )
    for s in scraped_with_content:
        logger.info("  ↳ %s  (%d chars)", s["url"], len(s.get("markdown", "")))

    if not scraped_with_content:
        raise HTTPException(status_code=503, detail="Failed to retrieve any product content")

    search_description = (
        f"{params.preference} {params.category}"
        + (f" under {params.budget}" if params.budget else "")
    )
    ranked = await run_in_threadpool(
        gemini_service.score_and_rank_products,
        scraped_with_content,
        search_description,
        params.budget_max,
        params.budget_currency,
        city,
        country,
        is_global,
    )
    logger.info("[SCORING] returned %d ranked products", len(ranked))

    valid_urls = {r["url"] for r in scraped_with_content}
    before = len(ranked)
    ranked = [
        p for p in ranked
        if (
            p.get("url", "").startswith("http")
            and "example.com" not in p.get("url", "")
            and p.get("url") in valid_urls
        )
    ]
    if len(ranked) < before:
        logger.warning(
            "[SCORING] dropped %d hallucinated URL(s), %d remain",
            before - len(ranked), len(ranked),
        )

    return ranked


# ─── Background Tasks ──────────────────────────────────────────────────────────

def _save_chat_history(
    user_id: str,
    prompt: str,
    image_included: bool,
    intent: str,
    response_data: dict,
) -> None:
    """Persist chat turn to Supabase asynchronously after the response is sent."""
    supabase = get_supabase_admin()
    try:
        supabase.table("chat_history").insert(
            {
                "user_id": user_id,
                "prompt": prompt,
                "image_included": image_included,
                "intent": intent,
                "response_json": response_data,
            }
        ).execute()
    except Exception as exc:
        logger.warning("chat_history write failed: %s", exc)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/admin/clear-cache")
async def clear_cache(current_user: dict = Depends(get_current_user)):
    """Wipe all cache layers (Supabase search_cache + in-process LRU/Bloom/lru_cache)."""
    summary = await run_in_threadpool(cache_service.clear_all_caches)
    return {"cleared": True, "summary": summary}


@router.get("/history")
async def get_history(current_user: dict = Depends(get_current_user)):
    """Return the last 50 chat turns for the authenticated user, newest first."""
    user_id = current_user["user_id"]
    supabase = get_supabase_admin()
    try:
        result = (
            supabase.table("chat_history")
            .select("id, prompt, intent, response_json, image_included, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        return {"entries": result.data or []}
    except Exception as exc:
        logger.warning("chat_history fetch failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not load history")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    if not req.messages:
        raise HTTPException(status_code=422, detail="messages array cannot be empty")

    user_id = current_user["user_id"]
    last_message = req.messages[-1]
    image_included = bool(last_message.image_base64)

    # Fetch city/country from the user's profile in Supabase
    supabase = get_supabase_admin()
    profile_result = supabase.table("profiles").select("city, country").eq("id", user_id).single().execute()
    profile = profile_result.data or {}
    city: str = profile.get("city") or ""
    country: str = profile.get("country") or ""

    # ── Step 1: Intent gate ── cheap, fast Gemini call ──────────────────────
    intent_data = await run_in_threadpool(
        gemini_service.classify_intent, req.messages, city, country
    )

    intent: str = intent_data.get("intent", "CHAT")
    reply: str | None = intent_data.get("reply")
    raw_params: dict = intent_data.get("collected_params") or {}
    search_globally: bool = bool(intent_data.get("search_globally", False))
    is_refinement: bool = bool(intent_data.get("is_refinement", False))
    # When the user explicitly requests global search, drop domain restrictions entirely
    gemini_domains: list[str] | None = None if search_globally else (intent_data.get("local_domains") or None)
    # Prefer the new localized field; fall back to legacy search_query if absent
    gemini_localized_query: str | None = (
        intent_data.get("localized_search_query") or intent_data.get("search_query") or None
    )

    collected_params = IntentParams(
        category=raw_params.get("category"),
        budget=raw_params.get("budget"),
        budget_max=raw_params.get("budget_max"),
        budget_currency=raw_params.get("budget_currency"),
        preference=raw_params.get("preference"),
    )

    # ── Step 2: CHAT / CLARIFY — return immediately, Tavily/Jina stay asleep ─
    if intent in ("CHAT", "CLARIFY"):
        response = ChatResponse(
            intent=intent,
            reply=reply or "How can I help you find the perfect product?",
            collected_params=collected_params,
        )
        background_tasks.add_task(
            _save_chat_history,
            user_id,
            last_message.content,
            image_included,
            intent,
            response.model_dump(),
        )
        return response

    # ── Step 3: SEARCH pipeline ───────────────────────────────────────────────

    excluded_urls: set[str] = set(req.excluded_urls) if req.excluded_urls else set()

    deterministic_query, local_domains = _build_search_query(gemini_localized_query, collected_params, gemini_domains)
    logger.info(
        "[SEARCH] query=%r  domains=%r  city=%r  country=%r  excluded=%d  global=%s  refinement=%s",
        deterministic_query, local_domains, city, country, len(excluded_urls), search_globally, is_refinement,
    )

    # Step 3a: Generate embedding → semantic cache check
    # Skip cache when: user explicitly excluded URLs, OR this is a refinement (e.g. "cheaper").
    # A refinement changes budget_max or preference — the embedding is nearly identical to the
    # previous query, so a cache hit would return the exact same products the user just rejected.
    embedding: list[float] = await run_in_threadpool(
        gemini_service.generate_embedding, deterministic_query
    )
    cached = None
    if not excluded_urls and not is_refinement:
        cached = await run_in_threadpool(
            cache_service.lookup_cache,
            embedding,
            collected_params.category or "",
            collected_params.budget_max,
            collected_params.budget_currency,
        )

    if cached:
        products = [Product(**p) for p in cached]
        response = ChatResponse(
            intent="SEARCH",
            products=products,
            collected_params=collected_params,
            from_cache=True,
        )
        background_tasks.add_task(
            _save_chat_history,
            user_id,
            last_message.content,
            image_included,
            "SEARCH",
            response.model_dump(),
        )
        return response

    # Step 3b–3d: Run pipeline (local domains first)
    fallback_message: str | None = None
    ranked = await _run_product_pipeline(
        deterministic_query, collected_params, city, country, local_domains,
        excluded_urls or None, is_global=search_globally,
    )

    # Soft failure: local search found pages but inventory gate eliminated all of them.
    # Retry globally — and switch to the global scoring context so the evaluator does not
    # apply local delivery constraints or reject foreign currency prices.
    if not ranked and local_domains:
        logger.info("[SEARCH] local scoring returned empty — retrying without domain filter")
        ranked = await _run_product_pipeline(
            deterministic_query, collected_params, city, country, None,
            excluded_urls or None, is_global=True,
        )
        if ranked:
            fallback_message = (
                "I couldn't find this product on local retailers — all results were "
                "out of stock or didn't meet your criteria. "
                "Here are the best options I found from global shops:"
            )

    if not ranked:
        clarify_reply = await run_in_threadpool(
            gemini_service.explain_no_results,
            collected_params.category or "product",
            collected_params.preference or "",
            collected_params.budget_max,
            collected_params.budget_currency,
            city,
            country,
        )
        no_results_response = ChatResponse(
            intent="CLARIFY",
            reply=clarify_reply,
            collected_params=collected_params,
        )
        background_tasks.add_task(
            _save_chat_history,
            user_id,
            last_message.content,
            image_included,
            "CLARIFY",
            no_results_response.model_dump(),
        )
        return no_results_response

    products: list[Product] = []
    for p in ranked:
        s = p.get("scores") or {}
        products.append(
            Product(
                rank=p.get("rank", len(products) + 1),
                title=p.get("title", ""),
                url=p.get("url", ""),
                price=p.get("price"),
                currency=p.get("currency"),
                image_url=p.get("image_url"),
                scores=ProductScores(
                    cost_efficiency=float(s.get("cost_efficiency", 0)),
                    quality_confidence=float(s.get("quality_confidence", 0)),
                    logistics=float(s.get("logistics", 0)),
                    trust=float(s.get("trust", 0)),
                ),
                value_score=float(p.get("value_score", 0)),
                reasoning=p.get("reasoning", ""),
            )
        )

    # Step 3e: Cache the results in the background
    products_json = [p.model_dump() for p in products]
    background_tasks.add_task(
        cache_service.save_cache,
        deterministic_query,
        embedding,
        collected_params.category or "",
        collected_params.budget_max,
        collected_params.budget_currency,
        collected_params.preference,
        products_json,
    )

    response = ChatResponse(
        intent="SEARCH",
        products=products,
        collected_params=collected_params,
        from_cache=False,
        fallback_message=fallback_message,
    )
    background_tasks.add_task(
        _save_chat_history,
        user_id,
        last_message.content,
        image_included,
        "SEARCH",
        response.model_dump(),
    )
    return response
