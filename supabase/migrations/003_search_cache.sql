-- 003_search_cache.sql
-- Semantic search cache with pgvector + chat history
-- Run after 002_plan_schema.sql. pgvector must be enabled in the Supabase project.

CREATE EXTENSION IF NOT EXISTS vector;

-- ─── Search Cache ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.search_cache (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text      TEXT        NOT NULL,
    query_embedding extensions.vector(768) NOT NULL,
    category        TEXT        NOT NULL,
    budget_max      DECIMAL,
    budget_currency TEXT        NOT NULL DEFAULT 'USD',
    preference      TEXT,
    results_json    JSONB       NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '6 hours')
);

-- IVFFlat index for fast approximate nearest-neighbor search (cosine distance)
CREATE INDEX IF NOT EXISTS search_cache_embedding_idx
    ON public.search_cache USING ivfflat (query_embedding extensions.vector_cosine_ops)
    WITH (lists = 100);

-- Composite index for metadata filtering (category + expiry)
CREATE INDEX IF NOT EXISTS search_cache_meta_idx
    ON public.search_cache (category, expires_at);

-- ─── Chat History ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.chat_history (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    prompt         TEXT        NOT NULL,
    image_included BOOLEAN     NOT NULL DEFAULT FALSE,
    intent         TEXT        NOT NULL CHECK (intent IN ('CHAT', 'CLARIFY', 'SEARCH')),
    response_json  JSONB       NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS chat_history_user_idx
    ON public.chat_history (user_id, created_at DESC);

-- ─── RLS ──────────────────────────────────────────────────────────────────────
ALTER TABLE public.search_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_history ENABLE ROW LEVEL SECURITY;

-- ─── Semantic cache lookup RPC ────────────────────────────────────────────────
-- Combines pgvector cosine similarity with hard metadata filters.
-- category must match (case-insensitive), budget_max must be within range,
-- and the entry must not be expired. Only returns rows above the similarity threshold.
CREATE OR REPLACE FUNCTION public.find_similar_search(
    query_vec         extensions.vector(768),
    p_category        TEXT,
    p_budget_max      DECIMAL      DEFAULT NULL,
    p_budget_currency TEXT         DEFAULT NULL,
    p_threshold       FLOAT        DEFAULT 0.92
)
RETURNS TABLE (
    id           UUID,
    results_json JSONB,
    similarity   FLOAT
)
LANGUAGE sql STABLE SET search_path = public, extensions
AS $$
    SELECT
        sc.id,
        sc.results_json,
        1 - (sc.query_embedding <=> query_vec) AS similarity
    FROM public.search_cache sc
    WHERE
        sc.expires_at > NOW()
        AND LOWER(sc.category) = LOWER(p_category)
        AND (
            p_budget_max IS NULL
            OR p_budget_currency IS NULL
            OR sc.budget_currency != p_budget_currency
            OR sc.budget_max <= p_budget_max
        )
        AND 1 - (sc.query_embedding <=> query_vec) > p_threshold
    ORDER BY sc.query_embedding <=> query_vec
    LIMIT 1;
$$;
