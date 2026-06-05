-- Migration: scrape_cache + hostile_domains
-- scrape_cache: 24-hour TTL per-URL scrape result store used by scraper_service.py
-- hostile_domains: runtime learner — domains that require the residential proxy

CREATE TABLE IF NOT EXISTS scrape_cache (
    url                 TEXT PRIMARY KEY,
    markdown            TEXT,
    jsonld              JSONB,
    shipping_policy_url TEXT,
    return_policy_text  TEXT,
    scraped_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scrape_cache_scraped_at ON scrape_cache (scraped_at);

ALTER TABLE scrape_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON scrape_cache USING (true);

CREATE TABLE IF NOT EXISTS hostile_domains (
    domain     TEXT PRIMARY KEY,
    flagged_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE hostile_domains ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON hostile_domains USING (true);
