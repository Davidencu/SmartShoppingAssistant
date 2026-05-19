# SmartShop AI — Autonomous Shopping Concierge

SmartShop is a full-stack AI-powered shopping assistant. Users describe what they want to buy in natural language; the system finds, scores, and ranks the three best products from live e-commerce pages. The architecture is designed as a zero-ledger, zero-PCI-DSS SaaS: the AI handles discovery, the user provides the card only at checkout, and card data never touches the database.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Tech Stack](#tech-stack)
3. [Authentication Flow](#authentication-flow)
4. [Search Pipeline](#search-pipeline)
5. [AI Scoring System](#ai-scoring-system)
6. [Semantic Cache](#semantic-cache)
7. [Multi-Layer Structured Data Extraction](#multi-layer-structured-data-extraction)
8. [Vendor Logistics Registry](#vendor-logistics-registry)
9. [Network Performance Under Load](#network-performance-under-load)
10. [Plan & Billing](#plan--billing)
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
│  │  Auth Pages  │   │  Chat Interface   │   │   History / Plan Pages │ │
│  │  (Passkey /  │   │  (messages +      │   │                        │ │
│  │   OTP email) │   │  product cards)   │   │                        │ │
│  └──────┬───────┘   └────────┬──────────┘   └────────────────────────┘ │
└─────────┼────────────────────┼─────────────────────────────────────────┘
          │ JWT (Bearer)        │ POST /search/chat
          ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Backend                                  │
│                                                                         │
│  ┌──────────────┐  ┌──────────────────┐  ┌────────┐  ┌─────────────┐  │
│  │ /auth router │  │ /search router   │  │ /plan  │  │ /webhooks   │  │
│  │  WebAuthn    │  │  Intent gate     │  │ router │  │ LemonSqueezy│  │
│  │  OTP email   │  │  Cache check     │  │        │  │ webhook     │  │
│  │  JWT issue   │  │  Pipeline        │  │        │  │             │  │
│  └──────┬───────┘  └────────┬─────────┘  └───┬────┘  └─────────────┘  │
│         │                   │                 │                         │
│         ▼                   ▼                 ▼                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      Services Layer                             │   │
│  │                                                                 │   │
│  │  gemini_service   tavily_service   scraper_service              │   │
│  │  (intent/score/   (product URL     (curl_cffi fetch +           │   │
│  │   embeddings)      discovery)       trafilatura extract)        │   │
│  │                                                                 │   │
│  │  jsonld_service   cache_service   supabase_service              │   │
│  │  (Schema.org      (pgvector        (admin client)               │   │
│  │   extraction)      semantic cache)                              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────┬──────────────────────────────────┘
                                       │
              ┌────────────────────────┼──────────────────────┐
              ▼                        ▼                       ▼
     ┌─────────────────┐    ┌──────────────────┐   ┌──────────────────┐
     │    Supabase      │    │   Gemini 2.5     │   │  Tavily Search   │
     │  (PostgreSQL +   │    │   Flash API      │   │  (advanced mode, │
     │   pgvector)      │    │  (intent, score, │   │  optional domain │
     │                  │    │   embeddings)    │   │  pinning)        │
     │  profiles        │    └──────────────────┘   └──────────────────┘
     │  passkeys        │
     │  search_cache    │
     │  chat_history    │
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
| AI — Embeddings | Gemini Embedding 001 (`gemini-embedding-001`, 768-dim) |
| Web Search | Tavily (advanced search depth, optional domain filtering) |
| Web Scraping | `curl_cffi` (browser fingerprinting) + `trafilatura` (content extraction) + `BeautifulSoup4` / `lxml` (structured data extraction) |
| Authentication | WebAuthn / Passkeys (FIDO2 biometric) + OTP email via Supabase |
| Billing | Lemon Squeezy (Merchant of Record — handles global VAT/taxes) |
| Future: Checkout | Stagehand (AI-driven browser automation via `page.act()`) |

---

## Authentication Flow

SmartShop uses a two-phase registration: email ownership is verified first (OTP), then a biometric passkey is enrolled. Login is entirely passwordless.

### Registration (5 steps)

```
1. User fills form (email, phone, full shipping address)
        │
        ▼
2. POST /auth/send-otp
   → Supabase sends a 6-digit OTP to the email
   → Shipping data is held in backend RAM (_registration_data)
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

Every `/search/chat` request passes through a five-stage pipeline. Each stage is independently failable with graceful degradation.

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
│ STAGE 3 — TAVILY PRODUCT DISCOVERY                 │
│                                                     │
│  Query = localized_search_query + " buy"           │
│  (" buy" injected in Python to surface product     │
│  listing pages rather than manufacturer brand sites)│
│                                                     │
│  Two-pass strategy:                                │
│  1. Local: search within local_domains (3-5 sites) │
│     — if < 3 results, fall through to global       │
│  2. Global: unrestricted Tavily search             │
│  Results merged and deduplicated, capped at 10.    │
│  Excluded URLs stripped before scraping.           │
└──────────────────────────┬──────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│ STAGE 4 — SCRAPING (4-layer extraction)            │
│                                                     │
│  Up to 5 URLs scraped concurrently via the         │
│  priority-queue scheduler.  Per URL:               │
│                                                     │
│  1. curl_cffi fetches HTML with Chrome fingerprint │
│     (bypasses basic bot-detection)                 │
│  2. extract_jsonld_facts — Schema.org JSON-LD,     │
│     HTML microdata, data-* attributes              │
│  3. extract_bs4_facts (BeautifulSoup4/lxml) —     │
│     Open Graph meta, itemprop content=,            │
│     aria-label ratings, data-price attributes,     │
│     og:site_name → seller context                  │
│     JSON-LD wins on conflict (authoritative)       │
│  4. trafilatura — main body text, strips           │
│     nav/footer/cookie banners/ads                  │
│                                                     │
│  Pages with < 200 chars of content are discarded.  │
└──────────────────────────┬──────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│ STAGE 5 — GEMINI VALUE SCORING                     │
│                                                     │
│  All scraped pages sent to Gemini in one prompt.   │
│  Gemini performs:                                  │
│  A. Purchasability check — requires at least one   │
│     "Add to cart" / "Cumpără" / equivalent signal  │
│  B. Budget hard limit check (120% of ceiling)      │
│  C. 4-dimension scoring (see Scoring section)      │
│                                                     │
│  value_score recomputed deterministically in Python.│
│  Products re-sorted by value_score.                │
│  Hallucinated URLs (not in Tavily manifest) dropped.│
│                                                     │
│  Results saved to cache in background task.        │
│  Chat turn saved to chat_history in background.    │
└─────────────────────────────────────────────────────┘
```

### Global Fallback

If local scoring returns zero products, the pipeline automatically retries with `is_global=True` and no domain restriction. The frontend shows a notice: *"I couldn't find this on local retailers — here are the best global options."*

### Dynamic Budget Drop

When `is_refinement=true` and the user asks for "cheaper", Gemini reads the previous assistant message (which contains a price-enriched product list) and sets `budget_max = floor(cheapest_previous_price × 0.80)`. The 80% floor is computed mathematically from actual shown prices, not guessed.

---

## AI Scoring System

Products are scored across four dimensions in a single Gemini call with structured JSON output.

| Dimension | Weight | What it measures |
|---|---|---|
| `cost_efficiency` | 40% | Real value for the price paid. Being well under budget is rewarded, not penalised. |
| `quality_confidence` | 35% | Confidence in product quality: ratings, review counts, spec signals, quality badges. |
| `logistics` | 15% | Delivery speed, in-stock status, regional availability. Scored deterministically from the Vendor Logistics Registry when the retailer is known; falls back to page-text inference for unknown vendors. |
| `trust` | 10% | Seller reputation — official brand vs. unknown third-party. |

**Score anchors (0–100 per dimension):**
- `40` = data absent from the page (unknown, not a bad signal)
- `0` = confirmed bad signal (out of stock, price above hard limit, suspicious seller)
- `100` = outstanding confirmed signal (4.5+ stars, 500+ reviews, same-day delivery confirmed)

**Formula recomputed in Python (Gemini's arithmetic is not trusted):**
```
value_score = cost_efficiency×0.40 + quality_confidence×0.35 + logistics×0.15 + trust×0.10
```

### Purchasability Gate

Before scoring, Gemini must find at least one transactional signal: "Add to cart", "Adaugă în coș", "Cumpără", "In den Warenkorb", "Ajouter au panier", "Añadir al carrito", "カートに追加", or any equivalent. Pages without one are eliminated — they are manufacturer spec sheets or blog posts, not purchasable products.

### Global vs. Local Scoring Mode

When `is_global=True`, three prompt blocks are swapped:
- **Currency block**: authorises exchange-rate conversions — foreign-currency products are not penalised
- **Search context**: drops local delivery constraints
- **Logistics rubric**: shifts to international shipping availability rather than same-day local delivery

---

## Semantic Cache

Prevents redundant API calls for effectively identical searches.

**Storage:** `search_cache` table in Supabase with a `pgvector(768)` column and IVFFlat index.

**Cache key:** 768-dimensional Gemini embedding (`gemini-embedding-001`, `SEMANTIC_SIMILARITY` task).

**Hit conditions (all must pass):**
1. Cosine similarity ≥ 0.92
2. Same product category (case-insensitive)
3. Cached `budget_max` ≤ requested `budget_max` (same currency)
4. Entry not expired (TTL: 6 hours)

**Bypass conditions:**
- `excluded_urls` non-empty — user rejected previous results
- `is_refinement=true` — budget or preference changed

---

## Multi-Layer Structured Data Extraction

Before Gemini sees a product page, two complementary extractors run against the raw HTML and their results are merged. JSON-LD always wins on conflict — it is machine-generated structured data; BeautifulSoup results are best-effort heuristics.

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

## Vendor Logistics Registry

Because product pages do not expose shipping fees or delivery windows to unauthenticated scrapers, Gemini was forced to score the `logistics` dimension from page prose alone — yielding 40% ("data absent") for almost every known retailer. The registry replaces that guess with deterministic pre-computed facts.

### How it works

`logistics_data.py` contains a hard-coded `VENDOR_LOGISTICS_REGISTRY` dict keyed by domain (no `www.`). Each entry specifies:

| Field | Example (emag.ro) | Meaning |
|---|---|---|
| `base_shipping_fee_ron` | `15` | Standard courier fee in RON |
| `free_shipping_threshold_ron` | `1500` | Order total above which shipping is free (`None` for international) |
| `easybox_available` | `True` | Whether a locker pick-up network exists |
| `delivery_days` | `"1–3"` | Typical business-day window |
| `same_day_cities` | `["Bucuresti", "Ilfov"]` | Cities eligible for same-day dispatch |
| `hub_cities` | `["Bucuresti", "Cluj-Napoca", …]` | Regional fulfilment hubs (faster dispatch) |

Before Gemini sees the scoring prompt, `get_logistics_context(url, city, price)` is called per product. It:

1. Extracts the domain from the product URL.
2. Looks up the registry (returns `""` — a no-op — for unknown vendors so the existing fallback applies unchanged).
3. Compares the confirmed price against the free-shipping threshold (RON only; foreign-currency products skip the comparison).
4. Checks the user's city against `same_day_cities` then `hub_cities` using diacritic-insensitive partial matching (e.g., `"Cluj"` matches `"Cluj-Napoca"`).
5. Returns a structured block ending with an explicit score band so Gemini treats logistics as arithmetic, not inference.

### Score bands injected

| Condition | Score band | Reason emitted |
|---|---|---|
| Free shipping + same-day delivery | 95–100 | free shipping + same-day delivery |
| Free shipping + hub city | 90–95 | free shipping + local hub → fast delivery |
| Free shipping, no hub | 80–88 | free shipping to destination |
| Paid shipping + hub city | 65–75 | paid shipping but local hub reduces transit time |
| Paid shipping, standard | 55–65 | paid shipping, standard transit |
| Price unconfirmed, hub city | 70–85 | estimated from hub proximity (price not confirmed) |
| Price unconfirmed, no hub | 55–70 | estimated from hub proximity (price not confirmed) |

### Example injected block

```
### VENDOR LOGISTICS CONTEXT (emag.ro → Craiova)
• Shipping cost: FREE — order total (1799 RON) ≥ 1500 RON threshold
• Delivery window: 1–3 business days — Craiova is a regional fulfilment hub → faster dispatch
• Locker / Easybox: Available
→ LOGISTICS SCORE GUIDANCE: 90–95 (free shipping + local hub → fast delivery)
   Use this guidance as your primary logistics score source.
```

### Covered vendors (10)

`emag.ro`, `altex.ro`, `flanco.ro`, `mediagalaxy.ro`, `media-galaxy.ro`, `pcgarage.ro`, `cel.ro`, `dedeman.ro`, `evomag.ro`, `amazon.de`, `amazon.com`

New vendors can be added by inserting a key matching the bare domain (without `www.`) into `VENDOR_LOGISTICS_REGISTRY`.

---

## Network Performance Under Load

When many users concurrently search for popular products (gaming laptops, phones), the naive approach — fetching and parsing every URL fresh for every request — wastes CPU, memory, and risks IP bans from e-commerce sites. Three complementary data structures in `scraper_service.py` and `jsonld_service.py` address this.

### 1. Bloom Filter — RAM-efficient URL deduplication

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

### 4. Priority Queue Scraper Scheduler — anti-ban without sacrificing speed

Instead of applying a fixed sleep between all scrapes (which slows down real users) or randomised jitter (which gives no ordering guarantees), a min-heap priority queue assigns each scrape task a weight:

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

## Plan & Billing

| | Free | Pro |
|---|---|---|
| Search & discover | Unlimited | Unlimited |
| Auto-checkout credits | 2 (lifetime) | Unlimited |

Billing is handled by **Lemon Squeezy** as Merchant of Record (handles global VAT and sales tax). On payment success, Lemon Squeezy fires a signed webhook to `POST /webhooks/lemonsqueezy` which upgrades `profiles.plan` to `"pro"`.

---

## Frontend

Built with Next.js 15 App Router, TailwindCSS, and TypeScript.

### Route Groups

**`(auth)`** — unauthenticated:

| Route | Purpose |
|---|---|
| `/login` | Email → passkey biometric authentication |
| `/register` | Email + shipping form → OTP verification |
| `/register/passkey` | WebAuthn passkey enrollment |
| `/verify` | Magic link fallback handler |
| `/plan` | Post-registration plan selection |

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
- "View Product" external link + "Buy Now" button (checkout automation — phase 2)

### Dark Mode

Full `dark:` Tailwind variant coverage. A `ThemeToggle` button in the navbar persists the user's preference in `localStorage`.

### History Page

Shows the last 50 chat turns. Each card shows: user prompt, intent badge (Search / Clarify / Chat), timestamp, and — for SEARCH turns — clickable product rows with rank, title, price, and value score.

---

## Database Schema

### `001_initial_schema.sql`

```sql
profiles      -- Shipping/contact PII for concierge auto-fill
  id UUID PK REFERENCES auth.users, email, phone,
  street_address, city, state, postal_code, country

passkeys      -- WebAuthn FIDO2 credentials
  user_id UUID FK, email, credential_id TEXT UNIQUE,
  public_key TEXT, sign_count INTEGER
```

### `002_plan_schema.sql`

```sql
ALTER TABLE profiles
  ADD COLUMN plan TEXT DEFAULT 'free' CHECK (plan IN ('free','pro')),
  ADD COLUMN checkout_credits INTEGER DEFAULT 2
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

Row Level Security enabled on all tables. Backend uses the service-role key exclusively — no client-side DB writes.

---

## Project Structure

```
SmartShoppingAssistant/
├── CLAUDE.md                          # Architecture rules and stack reference
├── README.md
│
├── backend/
│   ├── main.py                        # FastAPI app, CORS, router registration
│   ├── requirements.txt
│   ├── core/config.py                 # Pydantic settings (reads from .env)
│   ├── models/
│   │   ├── search.py                  # ChatMessage, Product, ChatResponse
│   │   ├── user.py                    # Auth request/response models
│   │   └── plan.py                    # PlanStatus, PlanCheckoutResponse
│   ├── routers/
│   │   ├── auth.py                    # WebAuthn, OTP, JWT
│   │   ├── search.py                  # /search/chat, /search/history
│   │   ├── plan.py                    # /plan/status, /plan/select, /plan/checkout
│   │   └── webhooks.py                # Lemon Squeezy payment webhook
│   ├── services/
│   │   ├── gemini_service.py          # Intent classification, scoring, embeddings
│   │   ├── tavily_service.py          # Product URL discovery
│   │   ├── scraper_service.py         # curl_cffi + trafilatura + LRU/Bloom caches
│   │   ├── jsonld_service.py          # Schema.org JSON-LD + BeautifulSoup4 extraction
│   │   ├── logistics_data.py          # Vendor logistics registry + score-band injection
│   │   ├── cache_service.py           # pgvector semantic cache
│   │   └── supabase_service.py        # Admin client singleton
│   └── tests/
│       ├── mock/
│       │   ├── test_search_mock.py        # 22 endpoint tests (all calls mocked)
│       │   ├── test_real_user_scenarios.py # 28 user scenario tests
│       │   ├── test_jsonld_service.py     # 20 JSON-LD / microdata unit tests
│       │   └── test_data_structures.py   # 23 unit tests: BloomFilter, _LRUCache,
│       │                                 #   Priority, ScraperScheduler, @lru_cache
│       └── live/
│           └── test_search_live.py        # 28 tests hitting real APIs
│
├── frontend/
│   ├── app/
│   │   ├── (auth)/login, register, verify, plan
│   │   └── (dashboard)/dashboard, history
│   ├── components/
│   │   ├── auth/  LoginForm, RegisterForm, PasskeyEnrollment
│   │   ├── chat/  ChatInterface, ChatInput, MessageBubble, ProductCard
│   │   ├── plan/  PlanSelection
│   │   └── ThemeToggle.tsx
│   └── lib/
│       ├── api.ts                     # Typed fetch wrappers for all endpoints
│       ├── webauthn.ts
│       ├── imageCompressor.ts         # Client-side WEBP compression
│       └── supabase/ client.ts, server.ts
│
└── supabase/migrations/
    ├── 001_initial_schema.sql
    ├── 002_plan_schema.sql
    └── 003_search_cache.sql
```

---

## Local Setup

### Prerequisites

- Python 3.12+, Node.js 20+
- Supabase project with the `vector` extension enabled
- API keys: Gemini, Tavily, Lemon Squeezy

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Apply supabase/migrations/ in order (001 → 002 → 003)
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
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_ANON_KEY=...
GEMINI_API_KEY=...
TAVILY_API_KEY=...
JWT_SECRET=...                # random 32+ char string
RP_ID=localhost               # must match browser origin domain
RP_NAME=SmartShop Assistant
FRONTEND_ORIGIN=http://localhost:3000
LEMONSQUEEZY_API_KEY=...
LEMONSQUEEZY_VARIANT_ID=...
LEMONSQUEEZY_WEBHOOK_SECRET=...
BROWSERBASE_API_KEY=...       # future: checkout automation
BROWSERBASE_PROJECT_ID=...
```

### Frontend (`.env.local`)

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
```

---

## Running Tests

### Mock tests (no API keys, fast)

```bash
cd backend
python -m pytest tests/mock/ -v
# 93 tests
```

Covers: endpoint logic, JSON-LD extraction edge cases, real user conversation scenarios, semantic cache bypass, excluded URL stripping, global fallback, no-results clarification, BloomFilter correctness and false-positive rate, `_LRUCache` eviction ordering, Priority min-heap ordering, `ScraperScheduler` future resolution, and `@lru_cache` hit/miss tracking on `extract_jsonld_facts`.

### Live tests (consumes real API credits)

```bash
cd backend
python -m pytest tests/live/ -m live -v
# 25 passed, 3 skipped by default
```

Full pipeline (most expensive):

```bash
RUN_FULL_PIPELINE_TESTS=1 python -m pytest tests/live/ -m live -v
```

### Frontend tests

```bash
cd frontend
npm test
```

---

## Architectural Rules

**No PCI-DSS** — Card numbers flow: browser → FastAPI RAM → Stagehand → immediate purge. Never written to any database, log, or cache. `autocomplete="cc-number"` triggers OS-level biometric autofill so the user never types card details manually.

**No internal ledger** — SmartShop does not hold funds or process payments. The $9.99/month subscription is delegated entirely to Lemon Squeezy as Merchant of Record.

**Concierge data is stored** — Shipping address, phone, and name live in `profiles`. Stagehand uses them to fill checkout forms automatically; the user only provides the card.

**Agentic checkout, no brittle locators** — All e-commerce automation uses Stagehand's `page.act()` natural language instructions, not hand-written CSS/XPath selectors. The agent is resilient to site redesigns.

**Scoring arithmetic in Python** — `value_score` is always recomputed deterministically in Python after receiving Gemini's dimension scores. Gemini's own `value_score` field in the JSON response is discarded to prevent floating-point drift and prompt-injection attacks from affecting rankings.
