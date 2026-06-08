# SmartShop AI — Autonomous Shopping Concierge

**Tell SmartShop what you want to buy and your budget. It searches the web, reads the product pages, checks the shipping policies, and hands you the three best options — ranked by real value, not sponsored placement.**

SmartShop is a full-stack AI shopping assistant built around a simple idea: the AI does all the tedious work (searching, comparing prices, checking shipping, reading return policies) so the user just picks their favourite. The system is designed as a zero-ledger, zero-PCI-DSS SaaS — card details are never stored anywhere and the AI handles everything up to the moment of purchase.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Tech Stack](#tech-stack)
3. [Authentication Flow](#authentication-flow)
4. [Search Pipeline](#search-pipeline)
5. [Stealth Scraping Architecture](#stealth-scraping-architecture)
6. [AI Scoring System](#ai-scoring-system)
7. [Semantic Cache](#semantic-cache)
8. [Multi-Layer Structured Data Extraction](#multi-layer-structured-data-extraction)
9. [Autonomous Logistics Discovery](#autonomous-logistics-discovery)
10. [Network Performance Under Load](#network-performance-under-load)
11. [Frontend](#frontend)
12. [Database Schema](#database-schema)
13. [Project Structure](#project-structure)
14. [Local Setup](#local-setup)
15. [Environment Variables](#environment-variables)
16. [Running Tests](#running-tests)
17. [Architectural Rules](#architectural-rules)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         BROWSER (Next.js)                               │
│                                                                         │
│  ┌──────────────┐   ┌───────────────────┐   ┌────────────────────────┐ │
│  │  Auth Pages  │   │  Chat Interface   │   │   History Page         │ │
│  │  (Passkey /  │   │  (messages +      │   │                        │ │
│  │   OTP email) │   │  product cards)   │   │                        │ │
│  └──────┬───────┘   └────────┬──────────┘   └────────────────────────┘ │
└─────────┼────────────────────┼─────────────────────────────────────────┘
          │ JWT (Bearer)        │ POST /search/chat (SSE stream)
          ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Backend                                  │
│                                                                         │
│  ┌──────────────┐  ┌──────────────────┐  ┌─────────────┐              │
│  │ /auth router │  │ /search router   │  │             │              │
│  │  WebAuthn    │  │  Intent gate     │  │             │              │
│  │  OTP email   │  │  Cache check     │  │             │              │
│  │  JWT issue   │  │  Niche-first     │  │             │              │
│  └──────┬───────┘  │  pipeline (SSE)  │  └─────────────┘              │
│         │          └────────┬─────────┘                                │
│         │                   │                                          │
│         ▼                   ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      Services Layer                             │   │
│  │                                                                 │   │
│  │  gemini_service   tavily_service   scraper_service              │   │
│  │  (intent/score/   (product URL     (CF swarm → direct/lazy     │   │
│  │   embeddings +     discovery)       residential proxy →         │   │
│  │   research agent + Groq fallback)   ghost layer + Bloom/LRU)   │   │
│  │                                                                 │   │
│  │  retailers_service     jsonld_service      cache_service        │   │
│  │  (DB-backed domain     (Schema.org         (pgvector            │   │
│  │   registry, 5-min TTL   extraction)         semantic cache)     │   │
│  │   niche/mainstream                                              │   │
│  │   tiers, proxy flags)  logistics_data      supabase_service     │   │
│  │                        (deterministic       (admin client        │   │
│  │                         shipping registry)   singleton)         │   │
│  └──────────────────────────┬──────────────────────────────────────┘   │
└─────────────────────────────┼───────────────────────────────────────────┘
                              │
          ┌───────────────────┼──────────────────────┬─────────────────┐
          ▼                   ▼                       ▼                 ▼
 ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌─────────┐
 │    Supabase      │  │   Gemini 2.5     │  │  Tavily Search   │  │  Groq   │
 │  (PostgreSQL +   │  │   Flash API      │  │  (advanced mode, │  │ (Llama  │
 │   pgvector)      │  │  (intent, score, │  │  optional domain │  │ 3.3-70B │
 │                  │  │   embeddings,    │  │  pinning)        │  │ fallback│
 │  profiles        │  │   research agent)│  └──────────────────┘  └─────────┘
 │  passkeys        │  └──────────────────┘
 │  search_cache    │
 │  chat_history    │
 │  supported_      │
 │  retailers       │
 │  scrape_cache    │
 │  hostile_domains │
 └──────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 15 (App Router), TailwindCSS, TypeScript |
| Backend | FastAPI (Python 3.14), Uvicorn |
| Database | Supabase (PostgreSQL + pgvector) |
| AI — Intent & Scoring | Gemini 2.5 Flash (`gemini-2.5-flash`) |
| AI — Fallback | Groq (`llama-3.3-70b-versatile` scoring, `llama-3.1-8b-instant` intent) |
| AI — Embeddings | Gemini Embedding 001 (`gemini-embedding-001`, 768-dim) |
| Web Search | Tavily (advanced search depth, optional domain filtering) |
| Web Scraping | `curl_cffi` (6-profile Chrome/Edge stealth rotation) + lazy residential proxy (IPRoyal — direct-first, escalate on failure) + Cloudflare Worker Swarm + `BeautifulSoup4` / `lxml` (JSON-LD + `__NEXT_DATA__` extraction) |
| Authentication | WebAuthn / Passkeys (FIDO2 biometric) + OTP email via Supabase |

---

## Authentication Flow

SmartShop uses a two-phase registration: email ownership is verified first (OTP), then a biometric passkey is enrolled. Login is entirely passwordless.

### Registration (5 steps)

```
1. User fills form (email, phone, city, state [optional], country)
        │
        ▼
2. POST /auth/send-otp
   → Supabase sends a 6-digit OTP to the email
   → Location data is held in backend RAM (_registration_data)
        │
        ▼
3. User submits OTP → POST /auth/verify-otp
   → Supabase creates the user account in auth.users
   → Backend writes the profile row to public.profiles
   → Backend generates WebAuthn registration options (challenge)
        │
        ▼
4. Browser calls navigator.credentials.create()
   → OS triggers Face ID / Touch ID / Windows Hello
   → Passkey is created on device and in iCloud/Google Password Manager
        │
        ▼
5. POST /auth/passkey/register
   → Backend verifies the WebAuthn response (py-webauthn library)
   → Credential stored in public.passkeys (credential_id + public_key)
   → JWT (24h, HS256) returned to browser
   → Stored in localStorage as "smartshop_token"
```

### Login (3 steps)

```
1. User types email → POST /auth/check-email (exists check)
        │
        ▼
2. POST /auth/passkey/challenge
   → Backend fetches credential_id from DB, generates assertion options
        │
        ▼
3. Browser calls navigator.credentials.get()
   → OS biometric prompt (Face ID / fingerprint)
   → POST /auth/passkey/verify
   → Backend verifies signature, updates sign_count (replay-attack prevention)
   → JWT returned
```

### Session Management

- JWT stored in `localStorage` under key `smartshop_token`
- `DashboardLayout` checks for token on every navigation; redirects to `/login` if absent or 401
- Token expiry: 24 hours
- Sign-out: removes the token from `localStorage` and redirects

---

## Search Pipeline

Every search message passes through a five-stage pipeline. If any stage fails or finds nothing useful, the system degrades gracefully — retrying globally, explaining why nothing was found, or returning a partial result — rather than showing an error page.

Results are streamed to the frontend via **Server-Sent Events (SSE)** — the niche-tier search, research agent insight, and final scored products each arrive as separate JSON events, so the UI updates progressively rather than waiting for the full pipeline.

```
User message
      │
      ▼
┌─────────────────────────────────────────────────────┐
│ STAGE 1 — INTENT CLASSIFICATION (Gemini, ~0.3s)    │
│                                                     │
│  Gemini reads the full conversation history and     │
│  outputs a JSON object containing:                  │
│  • intent: CHAT | CLARIFY | SEARCH                  │
│  • localized_search_query — e.g. "rucsac laptop"   │
│    (NOT English — uses local e-commerce terminology)│
│  • local_domains — 3-5 regional e-commerce sites   │
│  • is_refinement — true when user refines ("cheaper")
│  • search_globally — true for explicit global asks  │
│  • collected_params — category, budget, preference  │
│                                                     │
│  CHAT/CLARIFY → return immediately, no scraping    │
└──────────────────────────┬──────────────────────────┘
                           │ SEARCH intent only
                           ▼
┌─────────────────────────────────────────────────────┐
│ STAGE 2 — SEMANTIC CACHE CHECK (pgvector)          │
│                                                     │
│  Generate 768-dim embedding of the search query.   │
│  Query pgvector with cosine similarity ≥ 0.92.     │
│  Cache hit → return immediately (from_cache=true)  │
│                                                     │
│  Cache is BYPASSED when:                           │
│  • excluded_urls non-empty (user rejected items)   │
│  • is_refinement=true (budget/pref changed)         │
└──────────────────────────┬──────────────────────────┘
                           │ Cache miss
                           ▼
┌─────────────────────────────────────────────────────┐
│ STAGE 3 — RESEARCH AGENT (Gemini, ~1s, parallel)  │
│                                                     │
│  research_community_picks() queries Gemini with     │
│  Google Search grounding to surface expert picks,  │
│  community recommendations, and niche stores the   │
│  Tavily pass might miss. The insight is streamed   │
│  to the frontend immediately (masks Tavily latency)│
│  and the URLs it surfaces are injected into the    │
│  contender set alongside the Tavily results.        │
└──────────────────────────┬──────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│ STAGE 4 — TAVILY PRODUCT DISCOVERY (~1s)           │
│                                                     │
│  Query = localized_search_query + " buy"           │
│  (" buy" injected in Python to surface product     │
│  listing pages rather than manufacturer brand sites)│
│                                                     │
│  Four-pass niche-first strategy:                   │
│  1. Niche local: specialty stores for the user's   │
│     country (tier='niche' from supported_retailers)│
│  2. Mainstream local: large platforms (tier=       │
│     'mainstream') if niche returns < 3 products    │
│  3. Niche global: specialty stores worldwide       │
│  4. Mainstream global: unrestricted fallback        │
│  Results merged, deduplicated, ~25 total URLs.     │
│  Excluded URLs stripped before scraping.           │
│                                                     │
│  ► URL SHAPE FILTER applied here — category,       │
│    listing, blog, and brand-store URLs dropped      │
│    before any scrape slot is wasted on them.        │
└──────────────────────────┬──────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│ STAGE 5 — SCRAPE + SCORE (~4-6s)                   │
│                                                     │
│  ┌─ PHASE 2: Hybrid Waterfall + Filter (~1-2s) ───┐ │
│  │  Blast all filtered URLs in parallel.          │ │
│  │  Per URL: CF Worker → direct (residential      │ │
│  │  proxy) → ghost layer (Google Cache/Archive).  │ │
│  │  JSON-LD + BS4 + __NEXT_DATA__ extraction.     │ │
│  │  Discard: out-of-stock, over-budget, <200      │ │
│  │  chars of content.                             │ │
│  │  Output: top 10 "contender" URLs ranked        │ │
│  │  by data richness (has price/rating/name).     │ │
│  └───────────────────────┬────────────────────────┘ │
│                          │                          │
│  ┌─ PHASE 3: Gemini Judge (~2-3s) ───────────────┐ │
│  │  All 10 contender pages sent to Gemini in one │ │
│  │  prompt. Gemini performs:                     │ │
│  │  A. Purchasability check (JSON-LD Tier 1 or   │ │
│  │     buy-button text — see AI Scoring section) │ │
│  │  B. Budget hard limit check (120% ceiling)    │ │
│  │  C. 40-point scoring across 4 dimensions      │ │
│  │  Output: top 3 ranked products with reasoning.│ │
│  │  value_score recomputed deterministically in  │ │
│  │  Python; hallucinated URLs dropped.           │ │
│  │  Groq (Llama 3.3-70B) activated automatically │ │
│  │  when Gemini returns 429/ServerError.         │ │
│  └───────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│ STAGE 6 — CACHE & PERSIST (background tasks)       │
│                                                     │
│  Results saved to pgvector search_cache (6h TTL).  │
│  Chat turn saved to chat_history.                  │
│  Both writes are fire-and-forget background tasks  │
│  — user receives the response without waiting.     │
└─────────────────────────────────────────────────────┘
```

### Niche-First Pipeline

The pipeline tries specialty/mid-market stores (tier=`'niche'`) before large mainstream platforms. Niche stores typically have better scrapability (fewer anti-bot defences), richer JSON-LD data, and carry products that aggregators like Amazon/eMAG don't stock. If niche stores turn up fewer than 3 scorable products, the pipeline transparently falls back to mainstream — a status message is streamed so the user knows the search widened.

Retailer tier and proxy-required flags are sourced from the `supported_retailers` Supabase table (managed by `retailers_service.py` with a 5-minute in-memory TTL cache), replacing the previous hardcoded `_HARD_DOMAINS` frozenset and Gemini-guessed domain lists.

### Global Fallback

If no local retailer has the product in stock or within budget, the pipeline automatically widens the search to the entire web with no country restriction. The user sees a friendly note explaining what happened: *"I couldn't find this on local retailers — here are the best global options."* No dead ends.

### Dynamic Budget Drop

When the user says "find me something cheaper", SmartShop doesn't just search for the same thing with a vague "lower budget" instruction. It reads the prices of the products it just showed, takes the cheapest one, and sets the new ceiling at 80% of that price — computed from the actual numbers, not guessed. For example: if the three products shown cost 1799, 1950, and 1600 RON, the new budget becomes 1280 RON (80% of 1600).

---

## Stealth Scraping Architecture

Enterprise firewalls (Cloudflare, Akamai, Imperva) inspect every inbound HTTP request across three axes: **TLS fingerprint**, **request headers**, and **behavioural patterns**. A naive scraper fails all three. SmartShop addresses each one explicitly, and adds a three-phase waterfall so that even the hardest sites (Amazon, Walmart) are reachable.

### Global Hybrid Pipeline Waterfall

Every URL goes through three phases in order. The result of the first successful phase is returned — remaining phases are skipped.

```
URL to scrape
      │
      ▼
┌──────────────────────────────────────────────────────────────────┐
│ PHASE 1a — Cloudflare Worker Swarm (all domains)                 │
│                                                                  │
│  Request proxied through Cloudflare edge PoPs.                   │
│  Worker IPs are not in cloud/datacenter block-lists that         │
│  Amazon and Walmart screen against.                              │
│  Workers tried in round-robin; soft-block per-worker checked.    │
│  ✓ Success → return parsed result                                │
│  ✗ All workers 403 → fall through                                │
└──────────────────────────┬───────────────────────────────────────┘
                           │ Phase 1a blocked
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│ PHASE 1b — Direct curl_cffi with Lazy Residential Proxy          │
│                                                                  │
│  Two-attempt waterfall per URL:                                  │
│  Attempt 1 — Free direct connection (no proxy).                  │
│    Skip for hard domains (from supported_retailers where         │
│    requires_proxy=TRUE) or any domain already learned to         │
│    require a proxy (hostile_domains table / session cache).      │
│  Attempt 2 — Residential proxy escalation (IPRoyal,              │
│    geo.iproyal.com:12321). Activated on 429, 403/503, or a       │
│    soft-block from attempt 1. The domain is persisted to the     │
│    hostile_domains Supabase table so future server restarts      │
│    skip the wasted direct hop immediately.                        │
│  ✓ Either attempt succeeds → return parsed result                │
│  ✗ Proxy also blocked → fall through                             │
└──────────────────────────┬───────────────────────────────────────┘
                           │ Phase 1b blocked
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│ PHASE 2 — Ghost Layer (Google Cache → Internet Archive)          │
│                                                                  │
│  Google has already crawled the page. Static snapshot still      │
│  contains full JSON-LD structured data — price, availability,    │
│  rating — even without live JS execution.                        │
│  Falls back to Internet Archive if Google cache misses.          │
│  Free, no API key. Used only after both live phases fail.        │
└──────────────────────────────────────────────────────────────────┘
```

### URL Shape Filter — Dropping Category Pages Before Scraping

Tavily sometimes returns category/listing/search pages instead of product detail pages (PDPs). Scraping these wastes a slot and yields no useful product data. The `is_likely_product_url()` filter runs on every URL **before** any scrape slot is allocated.

```python
# Segments that indicate a category or listing page
_CAT_PATH_RE = re.compile(r"/(?:c|cat|category|collections|browse|sale|promo|
    search|filter|brand|blog|sitemap|account|cart|checkout|
    cpl|magazine|zgbs|gp|new-releases|...)(?:/|$|\?)", re.IGNORECASE)

# Query parameters that indicate faceted navigation
_CAT_PARAM_RE = re.compile(r"[?&](?:category|brand|sort|filter|page|q|
    query|search|collection)=", re.IGNORECASE)

# SKU / product-ID patterns in the path
_SKU_RE = re.compile(r"[-/](?:[A-Z]{1,4}-?\d{4,}|\d{6,}|[a-z]{2,8}-\d{3,})(?:/|$|\?)")
```

A URL is allowed through when it has a SKU, depth ≥ 2 + long slug, **or** a depth-1 slug with a numeric product ID embedded (e.g. `bb-shop.ro/ceas-de-mana-morgan-43070.html` — flat-URL stores used by many Romanian and Eastern European retailers).

```
URL passes shape filter when:
  has_sku      — explicit SKU/ASIN in path          e.g. /dp/B08TBF4S42
  OR
  (has_depth AND has_slug)                           e.g. /laptops/asus-vivobook-16
  OR
  has_id_slug  — depth-1 with 3+ digit product ID   e.g. /ceas-de-mana-boss-70934.html
```

### SPA Soft-Block Detection

A site may return HTTP 200 with an empty React shell (< 5 KB, no structured data) when its WAF blocks the scraper without revealing the rejection. `is_valid_product_page()` catches these before they enter the contender pipeline:

| Page size | Condition | Decision |
|---|---|---|
| < 5 KB | — | **Blocked** — definitively empty shell |
| 5–15 KB | No JSON-LD, `__NEXT_DATA__`, or Vue state | **Blocked** — no product data markers |
| 5–15 KB | Has any of the above | **Pass** — SPA with SSR data |
| > 15 KB | — | **Pass** — enough raw content for BS4 |

Soft-blocked pages from the CF Worker Swarm try the next worker before escalating to the ghost layer.

### 1. TLS Fingerprint Rotation — 6 browser profiles

`curl_cffi` impersonates real browsers at the cryptographic level, producing the exact TLS ClientHello fingerprint (JA3 hash) of each browser version rather than Python's default. Six profiles are maintained:

| Profile | Browser version | JA3 distinction |
|---|---|---|
| `chrome131` | Chrome Dec 2024 | Newest — highest reputation |
| `chrome124` | Chrome Apr 2024 | Common production version |
| `chrome120` | Chrome Dec 2023 | High global market share |
| `chrome116` | Chrome Aug 2023 | Widely deployed in enterprises |
| `chrome110` | Chrome Feb 2023 | Older enterprise builds |
| `edge101` | Edge Apr 2022 | Chromium engine, distinct profile |

**Selection is deterministic per domain** (MD5 hash of domain → index). This is a deliberate design choice: randomly cycling fingerprints *per request* is a bot signal — a human's browser does not switch from Chrome 124 to Edge 101 between two page loads. Locking a fingerprint to a domain builds session trust with the firewall, while the spread across 6 profiles means no single JA3 hash touches every retailer on the platform.

Curated per-domain overrides bypass the hash for known sites where empirical testing shows a specific fingerprint works best. Safari profiles (`safari17_0`) slip through Amazon/Walmart WAFs — their bot-detection is tuned to Chrome fingerprints.

### 2. Residential Proxy Integration — Lazy / Reactive

The residential proxy (IPRoyal, `geo.iproyal.com:12321`) is used **reactively** — the scraper tries a free direct connection first and only escalates to the proxy when the direct attempt fails. This eliminates unnecessary proxy bandwidth and cost for the majority of requests that succeed on direct.

**Two-attempt waterfall inside `_fetch_direct_sync`:**

```
Attempt 1 — Free direct connection (curl_cffi, no proxy)
  ├─ HTTP 200 + valid content  →  return immediately (proxy never touched)
  ├─ HTTP 429                  →  escalate to proxy (rate-limited)
  ├─ HTTP 403 / 503            →  escalate to proxy (WAF rejection)
  └─ Soft-block (< 5 KB or no │
       structured data markers)→  escalate to proxy

Attempt 2 — Residential proxy escalation
  ├─ HTTP 200 + valid content  →  return result
  └─ Still blocked             →  mark _blocked=True, fall to ghost layer
```

**Learner pattern — `hostile_domains` (Supabase table)**

The first time a domain fails the direct attempt, it is added to an in-memory set **and** persisted to the `hostile_domains` Supabase table. All subsequent fetches for that domain — across server restarts — skip attempt 1 entirely and go straight to the proxy.

**Hard-coded hostile domains — `requires_proxy=TRUE` in `supported_retailers`**

Amazon (all regional TLDs), Walmart, and similar sites are flagged `requires_proxy=TRUE` in the `supported_retailers` table — empirical testing confirmed that datacenter IPs (including CF Workers) are blocked at the network edge regardless of TLS fingerprint.

**Return-policy fetches** apply the same rule: the proxy is used only when the domain is flagged in `supported_retailers` or `hostile_domains`.

The proxy is optional. When `PROXY_HOST` / `PROXY_PORT` / `PROXY_USERNAME` / `PROXY_PASSWORD` are absent, escalations that would use the proxy instead mark the result as blocked immediately.

### 3. Locale Header Spoofing — 21 country mappings

Akamai in particular cross-checks `Accept-Language` against the target domain's TLD and the originating IP's ASN. An AWS Virginia IP sending `Accept-Language: en-US` to `emag.ro` is a high-confidence bot signal. The scraper resolves the locale from the URL's TLD:

```
emag.ro      →  ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7
amazon.de    →  de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7
fnac.fr      →  fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7
amazon.co.uk →  en-GB,en;q=0.9,en-US;q=0.8
```

21 TLDs are mapped: ro, de, fr, es, it, pl, nl, pt, hu, cz, se, no, dk, uk, au, ca, jp, kr, br, mx, in. All others fall back to `en-US,en;q=0.9`.

### 4. Same-Origin Referer

Every request sends the site's own origin as the `Referer` header. For `https://www.emag.ro/laptop-asus/pd/...`, the referer is `https://www.emag.ro/`. A static `https://www.google.com/` referer is a WAF trap: Google Search never links directly to page 3 of a site's internal pagination, so any scraper that sends Google as the referer for a deep URL is immediately flagged.

### 5. Retry Strategy — separated by failure type

The 403 and 429 status codes require fundamentally different responses:

| Status | Meaning | Action |
|---|---|---|
| **429** | Rate-limited — too many requests | Keep same profile (fingerprint cycling at machine-speed from the same IP is an instant permanent ban signal). Sleep `2.0–4.0s` random jitter, then retry once. |
| **403 / 503** | WAF/fingerprint rejection | Sleep `2.0–3.5s` first (switching at 0ms confirms a cycling script), then retry once with the next profile in the rotation. Domain-specific overrides (e.g. `safari17_0`) that are not in the main rotation list fall back to `chrome131` as the alternate profile. |

The jitter range prevents the server from seeing a predictable cadence even across retries. No more than one retry is attempted per URL — the goal is to pass a single checkpoint, not to hammer a blocked endpoint.

### 6. Buy-Button Text Preservation

`<form>` elements used to be fully stripped from the extracted page text (along with scripts and nav bars). This silently removed "Add to Cart" / "Adaugă în coș" / "Cumpără" buttons — the very signals Gemini uses to confirm a page is purchasable. The extractor now replaces each form with the concatenated text of its buttons and input labels rather than discarding them entirely.

```python
for form in soup.find_all("form"):
    buttons = " ".join(b.get_text(" ", strip=True) for b in form.find_all(["button", "input"]))
    form.replace_with(soup.new_string(buttons))
```

---

## AI Scoring System

Every product is scored across four dimensions in one Gemini call. The scores are combined into a single **value score** (0–100) that tells you how good a deal each product actually is — not just how cheap or how expensive.

| Dimension | Weight | What it measures |
|---|---|---|
| `cost_efficiency` | 40% | Real value for the price paid. Being well under budget is rewarded, not penalised. |
| `quality_confidence` | 35% | Confidence in product quality: ratings, review counts, spec signals, quality badges. |
| `logistics` | 15% | Shipping cost, delivery speed, and availability to the user's location. Sourced from `logistics_data.py` registry for known retailers; dynamic extraction for unknown ones. |
| `trust` | 10% | Seller reputation and return policy. Official brand stores with generous return windows score higher than unknown third-party sellers. |

**Score anchors (0–100 per dimension):**
- `40` = information not found on the page — treated as "unknown", not a failure
- `0` = confirmed bad news (out of stock, price above the hard limit, suspicious seller)
- `100` = outstanding confirmed signal (4.5+ stars, 500+ reviews, same-day delivery confirmed)

**The final score is computed in Python code, not by the AI** (AI arithmetic is unreliable):
```
value_score = cost_efficiency×0.40 + quality_confidence×0.35 + logistics×0.15 + trust×0.10
```

### Purchasability Gate — Two-Tier Signal

Before scoring, Gemini must find at least one purchasability signal from either tier:

**Tier 1 — Machine-verified (JSON-LD availability):** The `MACHINE-VERIFIED DATA` block contains `CONFIRMED AVAILABILITY: In Stock`. This alone is sufficient — no buy-button text is required when the site's own structured data confirms stock.

**Tier 2 — Page-text buy buttons:** Any transactional phrase visible in the extracted text: "Add to cart", "Adaugă în coș", "Cumpără", "In den Warenkorb", "Ajouter au panier", "Añadir al carrito", "カートに追加", or any equivalent in any language.

Pages where neither tier applies are eliminated — they are manufacturer spec sheets, blog posts, or out-of-stock placeholders.

### Groq Circuit Breaker

When Gemini returns `429 Too Many Requests` or `ServerError` after all retries, the scoring and intent calls automatically fall over to Groq:

| Task | Groq model | Notes |
|---|---|---|
| Scoring | `llama-3.3-70b-versatile` | Receives a compact prompt (~6k tokens vs ~21k for Gemini) |
| Intent classification | `llama-3.1-8b-instant` | Same JSON output schema as Gemini |

**Compact scoring prompt (`_build_compact_scoring_prompt`):** Groq's free tier is capped at 12k tokens per minute. The compact prompt sends only the JSON-LD `facts_header` + product title per product — omitting full markdown, logistics context, and return policy text. For 10 products this is ~6k tokens vs ~21k for the full Gemini prompt. The scored output format is identical so the same parsing code handles both.

The Groq client is optional. If `GROQ_API_KEY` is absent or the import fails, Groq is silently disabled and the circuit breaker is a no-op.

### Global vs. Local Scoring Mode

When `is_global=True`, three prompt blocks are swapped:
- **Currency block**: authorises exchange-rate conversions — foreign-currency products are not penalised
- **Search context**: drops local delivery constraints
- **Logistics rubric**: shifts to international shipping availability rather than same-day local delivery

---

## Semantic Cache

If two users search for "ASUS gaming laptop under 3000 RON" within six hours of each other, the second search skips the entire pipeline and returns the cached result in milliseconds. The cache is smart enough to recognise that "ASUS gaming laptop 3000 RON" and "ASUS gaming laptop max 3000 lei" are the same query, even though the wording differs.

**How a cache hit is decided (all four conditions must pass):**
1. The meaning of the search query is ≥ 92% similar (measured by AI embeddings — a 768-number fingerprint of the query's meaning)
2. Same product category
3. Cached budget ceiling is within the new budget
4. Result is less than 6 hours old

**The cache is automatically skipped when:**
- The user rejected the previous results (the "Not satisfied?" button was clicked)
- The user asked for "cheaper" or changed their preferences — same query but different intent

---

## Multi-Layer Structured Data Extraction

> **Why this matters:** An AI reading a product page like a human would has to guess the price from phrases like "1.799,00 lei" buried in paragraphs of marketing text. Instead, SmartShop extracts the price, rating, availability, and seller name from the structured data that the website already embeds for search engines — giving Gemini clean numbers to work with rather than prose to interpret.

Before Gemini sees a product page, two complementary extractors run against the raw HTML and their results are merged. When both find a price, the more authoritative source wins.

### Layer 1 — `extract_jsonld_facts` (Schema.org JSON-LD + microdata)

Targets structured data embedded by the site's own backend — the most authoritative source available without a logged-in session.

| Source | What it extracts |
|---|---|
| `<script type="application/ld+json">` | price, currency, availability, rating, review count, brand, product name |
| HTML microdata (`itemprop=`) | ratingValue, reviewCount (regex-based, covers sites that omit JSON-LD ratings) |
| `data-rating`, `data-score`, `data-review-count` | fallback rating from custom data attributes |

Handles Romanian price format (`"1 799,00"` → `1799.0`), availability URLs (`schema.org/InStock` → `"In Stock"`), `offers` as a list or nested dict, and `aggregateRating` from any nesting depth.

### Layer 2 — `extract_bs4_facts` (BeautifulSoup4 / lxml)

Targets the three common data sources that JSON-LD regularly misses on Romanian and international e-commerce sites.

| Source | What it extracts | Score rescued |
|---|---|---|
| Open Graph / Product `<meta>` tags | `og:price:amount`, `product:price:currency`, `og:availability`, `product:rating:value`, `product:rating:count` | `cost_efficiency`, `logistics`, `quality` |
| `og:site_name` / `application-name` | Retailer name (eMAG, Altex, Amazon…) | `trust` |
| `itemprop` content= attribute | `price`, `priceCurrency`, `availability`, `ratingValue`, `reviewCount` — read from the `content=` attribute, not display text | all dimensions |
| `aria-label` star ratings | `"4.7 out of 5 stars"`, `"4.7 din 5 stele"`, `"4.7 von 5 Sternen"`, `"rated 4.7"` — multi-language regex | `quality` |
| `data-price`, `data-gtm-price`, `data-product-price`, … | GTM / GA tracking payload prices (present even when JS renders the display price) | `cost_efficiency` |

Both extractors are wrapped in `@functools.lru_cache(maxsize=256)` — for popular products requested by multiple concurrent users, parsing runs once and all subsequent callers get the cached dict in O(1).

**Merge rule:** `{**bs4_facts, **jsonld_facts}` — JSON-LD overwrites BS4 on any key conflict.

**Example injected header (merged result):**
```
### MACHINE-VERIFIED DATA (Schema.org JSON-LD — authoritative)
• CONFIRMED NAME: ASUS VivoBook 16 X1605ZA
• CONFIRMED BRAND: ASUS
• CONFIRMED PRICE: 1799.0 RON
• CONFIRMED AVAILABILITY: In Stock
• CONFIRMED RATING: 4.6/5 (312 reviews)
• CONFIRMED SELLER: eMAG
```

Gemini is instructed to use these values directly for budget checks and scoring without re-parsing from prose text.

---

## Autonomous Logistics Discovery

> **The core challenge:** A product page never tells you the shipping cost — that information only appears once you're logged in at checkout. SmartShop solves this in two complementary ways: a deterministic registry for known retailers, and a dynamic two-hop extraction for unknown stores.

### Primary — `logistics_data.py` Deterministic Registry

For retailers in the registry (major Romanian, EU, and global stores), shipping fees, free-shipping thresholds, delivery windows, and easybox availability are hard-coded as structured facts. This gives the scoring prompt exact arithmetic to work with — no LLM guessing required.

```python
"emag.ro": {
    "base_shipping_fee_ron": 15,
    "free_shipping_threshold_ron": 1500,
    "easybox_available": True,
    "delivery_days": "1–3",
    ...
}
```

### Fallback — Dynamic Two-Hop for Unknown Stores

For retailers not in the registry, the system performs two extra steps automatically:

**Hop 1 — The Footer Sniper**

The raw HTML is scanned for links whose address or visible text contains words like `shipping`, `delivery`, `livrare` (Romanian), `versand` (German), `livraison` (French), and so on. Both the URL slug and the clickable text are checked, so a link labelled "Livrare și Retur" is found just as reliably as one at `/pages/shipping-policy`. If a shipping policy link is found, its URL is saved. If a returns/refunds link is found too, that page is fetched immediately and its text is stored for the trust scorer.

**Hop 2 — The Logistics Micro-Agent**

Before the main scoring call, Gemini Flash is given the shipping policy text and the user's city and country. It fills out a strict data form — no free-form text allowed:

```python
class LogisticsData(BaseModel):
    ships_to_user: bool              # Does this store ship here at all?
    shipping_cost_ron: float | None  # Cost in RON (foreign currencies auto-converted)
    estimated_days: str | None       # e.g. "3-5 business days"
    free_shipping_threshold_ron: float | None  # e.g. 200.0 means "free above 200 RON"
```

The prompt includes approximate conversion rates (1 EUR ≈ 5 RON, 1 USD ≈ 4.6 RON, 1 GBP ≈ 5.9 RON) so a German boutique charging €8 shipping is correctly reported as ~40 RON for a user in Romania.

### Score bands derived from the extracted data

| Condition | Score | What it means for the user |
|---|---|---|
| Ships here + free shipping + ≤ 2 days | 90–100 | Best case — fast and free |
| Ships here + free shipping + ≤ 5 days | 80–90 | Free shipping, standard window |
| Ships here + free shipping (window unknown) | 75–85 | Free shipping confirmed |
| Ships here + free above a threshold | 65–75 | Free if you spend enough |
| Ships here + paid + fast (≤ 3 days) | 65–75 | Worth paying for the speed |
| Ships here + paid + moderate (≤ 7 days) | 55–65 | Standard paid shipping |
| Does not ship to the user's country | 0–20 | Critical penalty — product excluded or ranked last |

### Performance — domain-level caching

Logistics data runs **once per domain per server session**, not once per product. If a search returns three products from emag.ro, the shipping policy is fetched on the first product and the result is reused for the other two instantly. The `_logistics_cache` dict (keyed by domain) and the scraper's `_policy_cache` both persist in memory for the lifetime of the server process, surviving across multiple user searches.

---

## Network Performance Under Load

When many users simultaneously search for popular products — gaming laptops, iPhones, running shoes — the simplest approach would be to scrape the same pages over and over for every request. That wastes server resources, slows everyone down, and risks getting the server's IP address blocked by e-commerce sites for making too many requests too quickly.

Four complementary mechanisms prevent this.

### 1. Bloom Filter — remembering 100,000 URLs in 120 KB

**In plain terms:** the server needs to remember which product pages it has already scraped so it doesn't fetch them again. Storing 100,000 full URLs as text would use 5–10 MB of RAM. A Bloom filter stores the same information in 120 KB — about the size of a small image — by recording a compact mathematical fingerprint of each URL instead of the URL itself.

A Bloom filter is a probabilistic bit-array that answers "have we scraped this URL before?" using a fraction of the RAM a regular Python `set` would need.

```
BloomFilter(capacity=100_000, error_rate=0.01)

Memory:   ~120 KB  (bytearray of ~960 k bits)
vs. set:  ~5–10 MB for 100k URL strings

False negatives: impossible — if a URL was added, it is always found.
False positives: ~1% at capacity — at most 1 in 100 unseen URLs is
                 mistakenly treated as already scraped. Harmless: the
                 LRU cache miss that follows sends it to the queue anyway.
```

**How it works — Kirsch-Mitzenmacher double-hashing:**

Two cheap digests (MD5 + SHA-1) are computed once per URL. All `k` hash positions are derived from them via `(h1 + i·h2) % m`, avoiding `k` separate hash calls regardless of how many hash functions are configured.

```python
def _positions(self, item: str) -> list[int]:
    h1 = int.from_bytes(md5(item.encode()).digest(), "little")
    h2 = int.from_bytes(sha1(item.encode()).digest(), "little")
    return [(h1 + i * h2) % self._size for i in range(self._hash_count)]
```

Optimal parameters are computed from `capacity` and `error_rate` at construction time using the standard Bloom filter formulae:

```
m (bit-array size) = ⌈-n · ln(p) / (ln 2)²⌉
k (hash functions) = ⌈(m/n) · ln 2⌉
```

### 2. Two-Level Scrape Cache — Bloom + LRU

The Bloom filter alone only says "probably scraped". The `_LRUCache` (backed by `collections.OrderedDict`) holds the actual scrape results for recently seen pages so repeated requests return immediately without any network I/O.

```
Request arrives for URL
        │
        ▼
  URL in BloomFilter?  ──No──► enqueue in priority queue (full scrape)
        │ Yes
        ▼
  URL in _LRUCache?    ──No──► enqueue (Bloom false-positive, rare)
        │ Yes
        ▼
  Return cached result instantly  (0 network calls, 0 CPU)
```

`_LRUCache` uses `OrderedDict` with `move_to_end` on every access (O(1)) and `popitem(last=False)` to evict the least-recently-used entry when at capacity (2 000 pages, ~20–100 KB each → at most ~200 MB upper bound).

```python
def get(self, key: str) -> Optional[dict]:
    if key not in self._store:
        return None
    self._store.move_to_end(key)       # mark as recently used
    return self._store[key]

def put(self, key: str, value: dict) -> None:
    if key in self._store:
        self._store.move_to_end(key)
        self._store[key] = value       # update value in-place
    else:
        if len(self._store) >= self._maxsize:
            self._store.popitem(last=False)   # evict LRU entry
        self._store[key] = value
```

Scrape results are also persisted to the `scrape_cache` Supabase table (24-hour TTL), so a cold-started server benefits from URLs already scraped by prior sessions rather than starting from zero.

### 3. `@lru_cache` on HTML Parsing — CPU deduplication

Parsing raw HTML with regex, `json.loads`, and BeautifulSoup is CPU-intensive. When 50 users simultaneously search for the same iPhone model, they will all receive the same HTML from the product page. Without caching, both extractors run 50 times for identical input.

`@functools.lru_cache(maxsize=256)` turns repeated calls with the same HTML string into O(1) dict lookups:

```python
@functools.lru_cache(maxsize=_JSONLD_CACHE_SIZE)   # 256 unique HTML pages
def extract_jsonld_facts(text: str) -> dict:
    ...

@functools.lru_cache(maxsize=_JSONLD_CACHE_SIZE)   # same budget, same benefit
def extract_bs4_facts(html: str) -> dict:
    ...
```

Both caches are cleared together by `cache_service.clear_all_caches()` via their respective `.cache_clear()` calls.

At 256 entries × ~50 KB average HTML ≈ 13 MB upper bound on retained strings.

> **Immutability contract**: the cached dict must not be mutated by callers. Downstream code that needs to modify extracted facts must copy the dict first.

### 4. Priority Queue Scraper Scheduler — polite to servers, fast for users

**In plain terms:** if SmartShop scrapes pages at full speed for background tasks, e-commerce sites will eventually block its IP address. But slowing everything down to avoid bans would make real user searches feel sluggish. The priority queue solves this by giving live user searches immediate processing while making background tasks wait a few seconds between each request — polite enough to avoid bans, fast enough for real-time use.

Instead of applying a fixed sleep between all scrapes (which slows everyone down equally), a min-heap priority queue assigns each scrape task a weight:

| Priority | Value | Delay after scrape | Use case |
|---|---|---|---|
| P1 — User request | 1 | **0 s** | Live search — immediate |
| P2 — Retry | 2 | 0.5 s | Failed URL being retried |
| P3 — Prefetch | 3 | 1.0 s | Speculative cache warm-up |
| P4 — Cache refresh | 4 | 2.0 s | Refreshing near-expiry results |
| P5 — Background | 5 | **3.0 s** | Background stock-data refresh |

Items are stored as `(priority, seq, url, future)` tuples. The monotonic `seq` counter acts as a tiebreaker within the same priority level, ensuring FIFO ordering and preventing Python from ever needing to compare `asyncio.Future` objects (which are not orderable and would raise `TypeError`).

```
asyncio.PriorityQueue (min-heap)

  (P1, 1, "user-url-A", future_A)   ← dequeued first
  (P1, 2, "user-url-B", future_B)   ← dequeued second
  (P5, 3, "background-url", future) ← dequeued last, 3 s delay after
```

Five async workers drain the queue concurrently. A P5 worker sleeping for 3 s does not block P1 items — the other four workers remain available. Workers start lazily on the first `submit()` call so no background tasks run while the server is idle.

```
                    ┌──────────────────────────────────┐
  submit(url, P1) ──►                                  │
  submit(url, P5) ──►   asyncio.PriorityQueue          ├──► worker 1 (P1, instant)
  submit(url, P1) ──►                                  ├──► worker 2 (P1, instant)
                    │   items ordered by (priority,seq)├──► worker 3 (idle)
                    │                                  ├──► worker 4 (idle)
                    └──────────────────────────────────┘──► worker 5 (P5, 3s delay)
```

**Net effect:** real users never wait for background tasks; e-commerce servers are not hammered by low-priority scrapes; no IP ban risk from burst behaviour.

---

## Frontend

Built with Next.js 15 App Router, TailwindCSS, and TypeScript.

### Route Groups

**`(auth)`** — unauthenticated:

| Route | Purpose |
|---|---|
| `/login` | Email → passkey biometric authentication |
| `/register` | Email + location form → OTP verification |
| `/register/passkey` | WebAuthn passkey enrollment |
| `/verify` | Magic link fallback handler |

**`(dashboard)`** — JWT-protected:

| Route | Purpose |
|---|---|
| `/dashboard` | Main chat interface |
| `/history` | Last 50 search turns, newest first |

### Chat Interface

- Full conversation history in component state; sent to backend on every message
- **Typing indicator** — three bouncing dots while awaiting API
- **Image upload** — attached photo compressed to WEBP client-side before base64 encoding
- **"Not satisfied?" button** — appears below the last product set; prefills input with rejection context and passes `excluded_urls` to the next request so the pipeline skips those pages
- **Price-enriched API messages** — assistant messages containing products are serialised as a price summary (`"Here are the top 3 products I found: 1. ASUS VivoBook — 1799 RON; ..."`) before being sent to the backend, enabling Gemini's Dynamic Budget Drop on refinement requests

### Product Cards

- Full product title (no truncation)
- Value score badge (green ≥80, yellow ≥60, red <60)
- Price
- Four score bars: Cost Efficiency, Quality, Logistics, Trust — colour coded
- **Expandable reasoning** — truncated to 3 lines by default; `ChevronDown / ChevronUp` toggles the full Gemini reasoning text per card independently via `useState`
- "View Product" external link (user completes purchase manually on the retailer's site)

### Dark Mode

Full `dark:` Tailwind variant coverage. A `ThemeToggle` button in the navbar persists the user's preference in `localStorage`.

### History Page

Shows the last 50 chat turns. Each card shows: user prompt, intent badge (Search / Clarify / Chat), timestamp, and — for SEARCH turns — clickable product rows with rank, title, price, and value score.

---

## Database Schema

### `001_initial_schema.sql`

```sql
profiles      -- Location data for context-aware search
  id UUID PK REFERENCES auth.users, email, phone,
  city, state TEXT (optional), country

passkeys      -- WebAuthn FIDO2 credentials
  user_id UUID FK, email, credential_id TEXT UNIQUE,
  public_key TEXT, sign_count INTEGER
```

### `003_search_cache.sql`

```sql
search_cache      -- Semantic cache with pgvector (6h TTL)
  query_text, query_embedding vector(768),
  category, budget_max, budget_currency,
  preference, results_json JSONB, expires_at

chat_history      -- Per-user search/chat log
  user_id FK, prompt, image_included BOOLEAN,
  intent TEXT CHECK (IN 'CHAT','CLARIFY','SEARCH'),
  response_json JSONB, created_at

-- PostgreSQL RPC using IVFFlat cosine distance + metadata filters
FUNCTION find_similar_search(query_vec, p_category, p_budget_max, ...)
```

### `004_simplify_profiles.sql`

```sql
-- street_address and postal_code removed: full address is not collected.
-- City + country are sufficient for logistics scoring and search localisation.
ALTER TABLE profiles
  DROP COLUMN IF EXISTS street_address,
  DROP COLUMN IF EXISTS postal_code;
-- state column is kept (collected as optional field in the registration form)
```

### `005_supported_retailers.sql`

```sql
supported_retailers   -- DB-backed retailer registry (replaces hardcoded domain lists)
  domain TEXT UNIQUE,
  target_country TEXT,   -- ISO 3166-1 alpha-2 or 'GLOBAL'
  requires_proxy BOOLEAN,
  tier TEXT CHECK (IN 'niche', 'mainstream'),
  is_active BOOLEAN

-- Seeded with 100+ retailers across 20+ countries.
-- Loaded by retailers_service.py with a 5-minute in-process TTL cache.
```

### `006_scrape_cache.sql`

```sql
scrape_cache      -- Persistent 24-hour per-URL scrape result store
  url TEXT PK,
  markdown TEXT,
  jsonld JSONB,
  shipping_policy_url TEXT,
  return_policy_text TEXT,
  scraped_at TIMESTAMPTZ

hostile_domains   -- Persisted proxy-learner set (survives server restarts)
  domain TEXT PK,
  flagged_at TIMESTAMPTZ
```

### `007_drop_plan_columns.sql`

```sql
-- Billing/plan system removed from the product.
ALTER TABLE public.profiles
  DROP COLUMN IF EXISTS plan,
  DROP COLUMN IF EXISTS checkout_credits;
```

### `008_retailer_tiers.sql`

```sql
-- Adds tier column to supported_retailers and reclassifies specialty stores.
ALTER TABLE supported_retailers
  ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'mainstream'
  CONSTRAINT valid_tier CHECK (tier IN ('niche', 'mainstream'));
```

Row Level Security enabled on all tables. Backend uses the service-role key exclusively — no client-side DB writes.

---

## Project Structure

```
SmartShoppingAssistant/
├── CLAUDE.md                          # Architecture rules and stack reference
├── README.md
│
├── backend/
│   ├── main.py                        # FastAPI app, CORS, router registration,
│   │                                  #   retailers_service.preload() on startup
│   ├── requirements.txt
│   ├── live_pipeline_test.py          # Verbose end-to-end test harness (5 scenarios,
│   │                                  #   no mocks — hits real Tavily/Gemini/scraper)
│   ├── core/config.py                 # Pydantic settings (reads from .env)
│   ├── models/
│   │   ├── search.py                  # ChatMessage, Product, ChatResponse
│   │   └── user.py                    # Auth request/response models (OTPRequest:
│   │                                  #   email, phone, city, state?, country)
│   ├── routers/
│   │   ├── auth.py                    # WebAuthn, OTP, JWT
│   │   └── search.py                  # /search/chat — SSE streaming pipeline:
│   │                                  #   niche-first strategy, research agent,
│   │                                  #   is_likely_product_url shape filter
│   ├── services/
│   │   ├── gemini_service.py          # Intent classification, scoring, embeddings,
│   │   │                              #   research_community_picks (Google Search
│   │   │                              #   grounded), extract_dynamic_logistics,
│   │   │                              #   Groq circuit breaker (Llama 3.3-70B scoring
│   │   │                              #   / Llama 3.1-8B intent), compact prompt builder
│   │   ├── tavily_service.py          # Product URL discovery
│   │   ├── scraper_service.py         # Global Hybrid Pipeline waterfall:
│   │   │                              #   CF Worker Swarm → direct curl_cffi
│   │   │                              #   (lazy residential proxy escalation) →
│   │   │                              #   ghost layer (Google Cache / Archive).
│   │   │                              #   hostile_domains DB learner set.
│   │   │                              #   is_likely_product_url() shape filter.
│   │   │                              #   is_valid_product_page() soft-block detector.
│   │   │                              #   6-profile TLS rotation, TLD locale headers,
│   │   │                              #   same-origin referer, jitter retry.
│   │   │                              #   LRU/Bloom in-memory caches + scrape_cache DB
│   │   │                              #   + priority queue scheduler.
│   │   ├── retailers_service.py       # supported_retailers DB wrapper:
│   │   │                              #   niche/mainstream domains per country,
│   │   │                              #   proxy-required set, 5-min TTL cache
│   │   ├── logistics_data.py          # Deterministic shipping registry for known
│   │   │                              #   retailers (fees, thresholds, delivery windows)
│   │   ├── jsonld_service.py          # Schema.org JSON-LD + BeautifulSoup4 extraction
│   │   ├── cache_service.py           # pgvector semantic cache + cache-clear
│   │   └── supabase_service.py        # Admin client singleton
│   └── tests/
│       ├── conftest.py                # client, mock_supabase, auth_token fixtures
│       ├── test_user_model.py         # OTPRequest validation unit tests
│       ├── test_scraper_service.py    # _parse_html, scrape_urls scheduler
│       ├── test_auth.py               # Auth endpoint tests
│       ├── test_registration_flow.py  # Registration flow integration tests
│       └── test_login_flow.py         # Login flow tests
│       ├── mock/
│       │   ├── test_search_mock.py    # Search endpoint tests (all external calls mocked)
│       │   ├── test_real_user_scenarios.py # Conversation scenario tests
│       │   ├── test_research_agent.py # research_community_picks, _compress_markdown,
│       │   │                          #   _pick_contenders, SSE pipeline integration
│       │   ├── test_jsonld_service.py # JSON-LD / microdata unit tests
│       │   └── test_data_structures.py # BloomFilter, _LRUCache, ScraperScheduler
│       └── live/
│           ├── test_search_live.py    # Live API tests (Gemini, Tavily, scraper)
│           ├── test_research_agent_live.py # research_community_picks live tests
│           └── test_shopping_scenarios.py  # Full pipeline: bike, watch, backpack
│                                           # (RUN_SHOPPING_SCENARIO_TESTS=1)
│
├── frontend/
│   ├── app/
│   │   ├── (auth)/login, register, verify
│   │   └── (dashboard)/dashboard, history
│   ├── components/
│   │   ├── auth/  LoginForm, RegisterForm (city, state?, country — no street/postal)
│   │   ├── chat/  ChatInterface, ChatInput, MessageBubble, ProductCard
│   │   └── ThemeToggle.tsx
│   └── lib/
│       ├── api.ts                     # Typed fetch wrappers for all endpoints
│       ├── webauthn.ts
│       ├── imageCompressor.ts         # Client-side WEBP compression
│       └── supabase/ client.ts, server.ts
│
└── supabase/migrations/
    ├── 001_initial_schema.sql
    ├── 003_search_cache.sql
    ├── 004_simplify_profiles.sql      # Drops street_address, postal_code
    ├── 005_supported_retailers.sql    # Retailer registry table + seed data
    ├── 006_scrape_cache.sql           # scrape_cache + hostile_domains tables
    ├── 007_drop_plan_columns.sql      # Removes plan/checkout_credits columns
    └── 008_retailer_tiers.sql         # Adds niche/mainstream tier column
```

---

## Local Setup

### Prerequisites

- Python 3.12+, Node.js 20+
- Supabase project with the `vector` extension enabled
- API keys: Gemini, Tavily
- Optional: Groq API key (circuit breaker), IPRoyal residential proxy credentials, Cloudflare Worker URLs

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Apply supabase/migrations/ in order (001 → 003 → 004 → 005 → 006 → 007 → 008)
# Use: npx supabase db push (requires supabase CLI linked to your project)
cp .env.example .env   # fill in all values
uvicorn main:app --reload   # http://localhost:8000
```

### Frontend

```bash
cd frontend
npm install
# .env.local: NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev   # http://localhost:3000
```

---

## Environment Variables

### Backend (`.env`)

```env
# ── Core services ──────────────────────────────────────────────────────────
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_ANON_KEY=...
GEMINI_API_KEY=...
TAVILY_API_KEY=...
JWT_SECRET=...                  # random 32+ char string
RP_ID=localhost                 # must match browser origin domain
FRONTEND_ORIGIN=http://localhost:3000

# ── Groq circuit breaker (optional) ───────────────────────────────────────
# When set, activates Llama 3.3-70B as a fallback when Gemini returns 429.
GROQ_API_KEY=...

# ── Cloudflare Worker Swarm (optional) ────────────────────────────────────
# Comma-separated URLs of deployed CF Workers used as Phase 1a proxies.
CF_WORKER_URLS=https://smartshop-proxy-1.your-subdomain.workers.dev,...
CF_WORKER_SECRET=...            # shared secret sent as X-Worker-Secret header

# ── Residential proxy (optional) ─────────────────────────────────────────
# When set, all curl_cffi sessions are routed through this proxy.
# Bypasses datacenter IP blocks on Amazon, Walmart, and similar retailers.
PROXY_HOST=geo.iproyal.com
PROXY_PORT=12321
PROXY_USERNAME=...
PROXY_PASSWORD=...
```

### Frontend (`.env.local`)

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
```

---

## Running Tests

### Unit tests (no API keys, ~2s)

```bash
cd backend
python -m pytest tests/ --ignore=tests/live -q
```

Covers: endpoint logic, OTPRequest model validation, JSON-LD extraction edge cases, real user conversation scenarios, semantic cache bypass, excluded URL stripping, global fallback, no-results clarification, BloomFilter correctness and false-positive rate, `_LRUCache` eviction ordering, `ScraperScheduler` future resolution, `scrape_urls` scheduler behaviour, `_parse_html` extraction, `_pick_contenders` filtering logic, `_compress_markdown` signal-line extractor, and `research_community_picks` SSE pipeline integration.

### Live tests (consumes real API credits)

```bash
cd backend
python -m pytest tests/live/test_search_live.py -m live -v
# ~28 tests: intent classification, embeddings, Tavily, scraper
```

Research agent live tests:

```bash
python -m pytest tests/live/test_research_agent_live.py -v
```

Full shopping scenario pipeline (most expensive — hits Tavily + Gemini + scraper):

```bash
RUN_SHOPPING_SCENARIO_TESTS=1 python -m pytest tests/live/test_shopping_scenarios.py -v -s
# 3 scenarios: sports bike <800 RON, digital watch <500 RON (gender refinement),
#              black resistant backpack <100 RON (Romanian local sites)
```

### Verbose pipeline test harness

```bash
cd backend
python live_pipeline_test.py
```

Runs 5 real end-to-end scenarios (gaming laptop 2500–3000 RON, mountain bike < 1000 RON, women's watch < 500 RON with gender refinement, Amazon wireless headset $80, notebook/laptop intent-gate) with detailed per-URL waterfall logs: which phase succeeded, chars extracted, JSON-LD facts, contender filter reasons, shape filter drop count, lazy proxy learner decisions (`[LEARNER]` lines), and final Gemini scores. No mocks — consumes real Tavily and Gemini credits.

### Frontend tests

```bash
cd frontend
npm test
```

---

## Architectural Rules

**No PCI-DSS** — Card numbers are never stored anywhere. The current flow sends the user directly to the retailer's product page to complete the purchase manually.

**Scoring arithmetic in Python** — `value_score` is always recomputed deterministically in Python after receiving Gemini's dimension scores. Gemini's own `value_score` field in the JSON response is discarded to prevent floating-point drift and prompt-injection attacks from affecting rankings.

**Tests must not touch live services** — Unit and mock tests patch all external calls (Gemini, Tavily, Supabase, scraper). The full unit suite runs in under 2 seconds with no network I/O.

**Retailer registry over hardcoded lists** — Domain lists (proxy-required, country domains, tiers) live in the `supported_retailers` Supabase table. `retailers_service.py` loads them with a 5-minute TTL. Adding a new retailer is a DB insert, not a code change.
