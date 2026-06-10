import base64
import json
import logging
import re
import time
from typing import Optional

from google import genai
from google.genai import types
from google.genai import errors
from pydantic import BaseModel

from core.config import settings
from services.jsonld_service import build_facts_header
import asyncio

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=settings.gemini_api_key)

_FLASH = "gemini-2.5-flash"
_EMBED = "gemini-embedding-001"

_BACKOFF_ATTEMPTS = 5

# ── Groq circuit breaker ───────────────────────────────────────────────────
# Activated when Gemini returns 429 / ServerError after all retries.
# Uses Llama-3.3-70B for scoring (quality match) and Llama-3.1-8B for intent
# (speed). Falls back gracefully when GROQ_API_KEY is not set.

_groq_client = None
try:
    if settings.groq_api_key:
        from groq import Groq as _Groq
        _groq_client = _Groq(api_key=settings.groq_api_key)
        logger.info("[GROQ] circuit breaker configured (Llama 3.3-70B)")
except Exception as _groq_init_exc:
    logger.warning("[GROQ] init failed: %s", _groq_init_exc)

_GROQ_SCORE_MODEL = "llama-3.3-70b-versatile"
_GROQ_INTENT_MODEL = "llama-3.1-8b-instant"


def _with_backoff(fn, *args, **kwargs):
    """Call fn(*args, **kwargs) with exponential backoff on ServerError (1 s → 2 s → raise)."""
    delay = 1.0
    for attempt in range(_BACKOFF_ATTEMPTS):
        try:
            return fn(*args, **kwargs)
        except errors.ServerError as exc:
            if attempt == _BACKOFF_ATTEMPTS - 1:
                raise
            logger.warning(
                "[GEMINI] attempt %d/%d overloaded, retrying in %.0fs…",
                attempt + 1, _BACKOFF_ATTEMPTS, delay,
            )
            time.sleep(delay)
            delay *= 2





def _build_compact_scoring_prompt(
    scraped_results: list[dict],
    search_description: str,
    budget_max: "Optional[float]",
    budget_currency: "Optional[str]",
    community_picks: list[str] | None = None,
) -> str:
    """
    Compressed scoring prompt for the Groq circuit breaker (target <2k tokens).
    Uses the markdown signal compressor to include key specs/ratings/buy-signals
    while excluding navigation, SEO prose, and other noise.
    Omits full logistics context and return policy to stay within Groq's free-tier TPM.
    """
    url_manifest = "\n".join(
        f"  {i + 1}. {r['url']}" for i, r in enumerate(scraped_results)
    )
    budget_str = f"{budget_max} {budget_currency}" if budget_max else "not specified"
    budget_120 = f"{int(budget_max * 1.2)} {budget_currency}" if budget_max else "not specified"

    picks = [p for p in (community_picks or []) if p]
    picks_note = (
        f"Community picks (Reddit/forums): {', '.join(picks[:3])} — "
        f"boost quality_confidence by up to 10 pts if title matches.\n\n"
        if picks else ""
    )

    products_block = ""
    for i, r in enumerate(scraped_results, 1):
        jsonld = r.get("jsonld") or {}
        name = (jsonld.get("name") or r.get("title") or "Unknown")[:80]
        facts = build_facts_header(jsonld)
        # 150-char signal snippet — enough for Groq to distinguish product type and quality
        snippet = _compress_markdown(r.get("markdown") or "", max_chars=150)
        products_block += (
            f"\n## PRODUCT {i}\nTitle: {name}\nURL: {r['url']}\n"
            f"{facts}"
            f"{snippet}\n"
        )

    return (
        f'Score these products for: "{search_description}"\n'
        f"Budget ceiling: {budget_str} (hard limit: {budget_120})\n\n"
        f"{picks_note}"
        f"AUTHORISED URLs (copy verbatim):\n{url_manifest}\n"
        f"{products_block}\n"
        f"Rules: drop products over {budget_120} or with explicit out-of-stock signals. "
        f"value_score = 0.40×cost_efficiency + 0.35×quality_confidence + 0.15×logistics + 0.10×trust. "
        f"Return JSON only:\n"
        f'{{"ranked_products": [{{"rank": 1, "title": "...", "url": "...", '
        f'"price": 0.0, "currency": "...", "image_url": null, '
        f'"scores": {{"cost_efficiency": 0, "quality_confidence": 0, "logistics": 0, "trust": 0}}, '
        f'"value_score": 0.0, "reasoning": "1-2 sentences."}}]}}'
    )


def _groq_intent(system: str, messages) -> dict:
    """
    Groq fallback for classify_intent.
    Converts Gemini Content objects to OpenAI-style messages and calls Llama 3.1-8B.
    """
    if not _groq_client:
        return {}
    try:
        groq_msgs = [{"role": "system", "content": system}]
        for msg in messages:
            role = "user" if msg.role == "user" else "assistant"
            groq_msgs.append({"role": role, "content": msg.content or ""})
        resp = _groq_client.chat.completions.create(
            model=_GROQ_INTENT_MODEL,
            messages=groq_msgs,
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=4096,
        )
        raw = resp.choices[0].message.content or ""
        return json.loads(raw)
    except Exception as exc:
        logger.error("[GROQ] intent failed: %s", exc)
        return {}

# ── Markdown signal compressor ────────────────────────────────────────────────
# Keeps only lines that carry numeric or purchase-related signals.
# Discards navigation menus, cookie banners, SEO prose, and base64/URL blobs.
_SIGNAL_KW = frozenset({
    # Stock / purchase
    "stock", "stoc", "cart", "cos", "buy", "cumpara", "order", "comanda",
    "deliver", "livrare", "shipping", "expeditie", "disponibil", "available",
    "purchas", "checkout",
    # Quality / reviews
    "review", "rating", "stars", "stele", "nota", "parere", "bewertung", "avis",
    "opiniones", "recensione",
    # Common spec units and components
    "gb ", "tb ", "ghz", "mhz", " inch", "inci", " cm", " kg", " g ", " w ",
    "watt", " hz", " rpm", "mah", "mp ", "megapixel",
    "ram", "ssd", "hdd", "nvme", "display", "screen", "ecran", "amoled", "oled",
    "battery", "baterie", "nvidia", "amd", "intel", "ryzen", "snapdragon",
    "bluetooth", "wifi", "usb", "hdmi", "ethernet",
    # Return / warranty (trust signal)
    "garantie", "warranty", "guarantee", "retour", "return", "retur",
})


def _compress_markdown(md: str, max_chars: int = 600) -> str:
    """
    Extract signal-dense lines from raw markdown, discarding SEO/navigation noise.
    Used to reduce LLM payload from ~3000 chars/product to a focused snippet.
    """
    kept: list[str] = []
    total = 0
    for raw in md.splitlines():
        line = raw.strip()
        if not line or len(line) > 160:  # skip empty lines and full prose paragraphs
            continue
        ll = line.lower()
        if any(c.isdigit() for c in line) or any(kw in ll for kw in _SIGNAL_KW):
            kept.append(line)
            total += len(line) + 1
            if total >= max_chars:
                break
    return "\n".join(kept)[:max_chars]


# Dynamic logistics helpers

class LogisticsData(BaseModel):
    ships_to_user: bool
    shipping_cost_ron: Optional[float] = None
    estimated_days: Optional[str] = None
    free_shipping_threshold_ron: Optional[float] = None


# Per-domain cache: avoids re-fetching and re-extracting for the same store
_logistics_cache: dict[str, LogisticsData | None] = {}


def _extract_domain_simple(url: str) -> str:
    m = re.search(r"(?:https?://)?(?:www\.)?([^/]+)", url)
    return m.group(1).lower() if m else "unknown"


def extract_dynamic_logistics(
    policy_url: str, user_country: str, user_city: str
) -> LogisticsData | None:
    """
    Logistics micro-agent: fetch a store's shipping policy page, then use
    Gemini Flash with response_schema to extract a strict LogisticsData object.
    Results are cached per domain. Runs synchronously (safe in threadpool).
    Returns None on failure so the caller falls back to the rubric.
    """
    if not policy_url:
        return None

    domain = _extract_domain_simple(policy_url)
    if domain in _logistics_cache:
        return _logistics_cache[domain]

    if len(_logistics_cache) > 500:
        _logistics_cache.clear()
        logger.debug("[LOGISTICS] cache evicted — size limit reached")

    # Fetch the policy page — we are already running in a threadpool
    from curl_cffi.requests import Session as _S
    from services.scraper_service import _extract_text_bs4

    policy_text: str | None = None
    try:
        with _S(impersonate="chrome124") as session:
            resp = session.get(policy_url, timeout=10)
            if resp.status_code == 200:
                policy_text = _extract_text_bs4(resp.text) or None
    except Exception as exc:
        logger.warning("[LOGISTICS] policy fetch failed for %s: %s", policy_url, exc)

    if not policy_text:
        _logistics_cache[domain] = None
        return None

    location = ", ".join(filter(None, [user_city, user_country])) or "unknown"
    prompt = (
        f"Read the following shipping policy and extract the logistics data for a user in {location}.\n"
        f"Convert non-RON prices to RON (1 EUR ≈ 5 RON, 1 USD ≈ 4.6 RON, 1 GBP ≈ 5.9 RON).\n"
        f"If the vendor does not ship to this location, set ships_to_user to false.\n\n"
        f"POLICY TEXT:\n{policy_text[:4000]}"
    )
    try:
        response = _with_backoff(
            _client.models.generate_content,
            model=_FLASH,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=LogisticsData,
                temperature=0.0,
                max_output_tokens=256,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        result = LogisticsData.model_validate_json(response.text)
        _logistics_cache[domain] = result
        logger.info(
            "[LOGISTICS] %s → ships=%s cost=%s days=%s",
            domain, result.ships_to_user, result.shipping_cost_ron, result.estimated_days,
        )
        return result
    except Exception as exc:
        logger.warning("[LOGISTICS] extraction failed for %s: %s", domain, exc)
        _logistics_cache[domain] = None
        return None


def clear_logistics_cache() -> dict:
    count = len(_logistics_cache)
    _logistics_cache.clear()
    return {"logistics_cache_entries_cleared": count}


def _score_band_from_logistics(data: LogisticsData) -> tuple[str, str]:
    if not data.ships_to_user:
        return "0–20", "does not ship to this location"
    m = re.search(r"(\d+)", data.estimated_days or "")
    days_min = int(m.group(1)) if m else None
    cost = data.shipping_cost_ron
    threshold = data.free_shipping_threshold_ron
    is_free = cost == 0.0
    has_threshold = threshold is not None
    if is_free and days_min is not None and days_min <= 2:
        return "90–100", "free shipping + express delivery"
    if is_free and days_min is not None and days_min <= 5:
        return "80–90", "free shipping + standard delivery"
    if is_free:
        return "75–85", "free shipping to destination"
    if has_threshold:
        return "65–75", "free above threshold; paid otherwise"
    if cost is not None and days_min is not None and days_min <= 3:
        return "65–75", f"paid shipping ({cost:.0f} RON), fast delivery"
    if cost is not None and days_min is not None and days_min <= 7:
        return "55–65", f"paid shipping ({cost:.0f} RON), moderate delivery"
    if cost is not None:
        return "45–60", f"paid shipping ({cost:.0f} RON), delivery window unspecified"
    return "55–70", "shipping data partially confirmed"


def _format_dynamic_logistics_ctx(
    domain: str, city: str, country: str, data: LogisticsData
) -> str:
    location = ", ".join(filter(None, [city, country])) or "destination"
    score_band, reason = _score_band_from_logistics(data)
    cost = f"{data.shipping_cost_ron:.0f} RON" if data.shipping_cost_ron is not None else "Not specified"
    days = data.estimated_days or "Not specified"
    threshold = f"{data.free_shipping_threshold_ron:.0f} RON" if data.free_shipping_threshold_ron is not None else "None"
    return (
        f"### VENDOR LOGISTICS CONTEXT ({domain} → {location})\n"
        f"• Ships to your location: {'Yes' if data.ships_to_user else 'No'}\n"
        f"• Shipping cost: {cost}\n"
        f"• Estimated delivery: {days}\n"
        f"• Free shipping threshold: {threshold}\n"
        f"→ LOGISTICS SCORE GUIDANCE: {score_band} ({reason})\n"
        f"   Use this guidance as your primary logistics score source.\n\n"
    )


# Shopping System Prompt
# Injected into every Gemini call. Defines ShopperAI's identity, intent system,
# and the strict JSON contract it must honour. No fine-tuning needed.

_SYSTEM_PROMPT = """\
You are ShopperAI — an elite autonomous shopping concierge engineered for one mission: \
find the user the highest-value product at the best price, every time.

## Language Rule
CRITICAL: Detect the language of the user's most recent message and reply in that exact \
language for ALL intents (CHAT, CLARIFY, SEARCH reply). If the user writes in Italian → \
reply in Italian. In German → German. In Romanian → Romanian. In French → French. \
NEVER default to English unless the user writes in English. The `localized_search_query` \
field must always use local e-commerce terminology in the regional language regardless of \
conversation language. Also output the detected language as an ISO 639-1 code in the \
`language_code` field (e.g. "it", "de", "ro", "fr", "es", "pl", "nl", "pt", "en").

## Identity & Scope
- You ONLY discuss products, shopping, prices, e-commerce, comparisons, and purchasing decisions.
- For ANY off-topic request (coding, homework, trivia, general questions, small talk): \
respond as CHAT intent. Your reply must be exactly one sentence — a polite but firm \
decline in the user's language — followed by one concrete shopping question to re-engage \
the user.
- Never say "I cannot do that". Redirect confidently to your core mission.
- You are data-driven, efficient, and direct. No filler, no unnecessary apologies.

## Intent Classification
Classify every user message into exactly ONE intent:

  CHAT    — Off-topic request, small talk, or capability question unrelated to shopping.
            Reply: one polite decline sentence + one concrete shopping re-engagement question.

  CLARIFY — The user wants a product but the request has missing, vague, or ambiguous
            parameters (see rules below). Ask the SINGLE most impactful clarifying question.
            Never ask two questions at once.

  SEARCH  — All 3 required parameters are present, specific, and unambiguous.
            Fire the search pipeline immediately — do NOT ask further questions.

## The 3 Required Search Parameters
1. category   — Must identify the product clearly enough to produce focused search results.
               A broad category is ACCEPTABLE when the preference already narrows it:
               ✓ "Laptop" + preference "ASUS 16GB RAM" — brand+spec is sufficient
               ✓ "Shoes" + preference "Nike running size 42" — brand+use case is sufficient
               ✓ "Mountain Bike", "Road Bike", "Gaming Laptop" — explicit subtype
               ✗ "Bike" + preference "high quality" — both vague; ask for bike subtype
               ✗ "Laptop" + preference "good" — category unclear without brand or spec
2. budget     — A specific numeric price ceiling with currency.
               ✓ "under 800 RON", "max 500 USD", "around 1500 RON" (treat "around" as ceiling)
3. preference — At least ONE concrete, actionable requirement.
               ✓ Brand: "ASUS", "Nike", "Trek", "Samsung"
               ✓ Spec: "16GB RAM", "aluminium frame", "waterproof", "size 42", "500W motor"
               ✓ Use case: "for adults", "for trail riding", "for office work", "for gaming"
               ✗ Pure quality adjectives ALONE — "high quality", "good", "best", "nice" \
do NOT count as a preference. Ask for a real spec, brand, or use case instead.

## Ambiguity Rules — when to trigger CLARIFY instead of SEARCH
Trigger CLARIFY (never SEARCH) when ANY of the following apply:
- category is broad AND preference is also vague (no brand, spec, or use case):
    "bike" + "high quality" → ask: mountain, road, BMX, kids, electric?
    "shoes" + "good" → ask: what type and use case?
    "phone" + "nice" → ask: Android or iPhone? Any brand preference?
- preference contains ONLY quality adjectives ("high quality", "good", "best", "nice", \
  "great") with no brand, spec, size, or use-case — ask for one concrete requirement.
- the request is ambiguous between an adult product and a children's product \
  (e.g., "bike for 800 RON" with no age/size context) — ask who it is for.
- budget is completely absent — ask for it; "around X" is acceptable, treat it as ceiling.

## Parameter Extraction Rules
- Extract from the ENTIRE conversation history, not just the latest message.
- Parameters persist across turns — never forget what the user already stated.
- "ASUS laptop" → category="Laptop", preference="ASUS brand"
- "budget around 1500 RON" → budget="around 1500 RON", budget_max=1500.0, budget_currency="RON"
- budget_max is always a float representing the numeric ceiling.
- budget_currency is always an ISO 4217 code (USD, EUR, RON, GBP, …).
- Priority order for asking: budget > category specificity > preference concreteness.

## Pronoun & Reference Resolution
You MUST resolve vague references by reading the full conversation history before classifying.
If the user's message contains pronouns or shorthand ("find cheaper ones", "the red one", \
"those", "a similar product", "same but different brand", "what about the second one"), \
identify what they refer to from the previous turns and carry those parameters forward.
NEVER ask the user to clarify a reference that is obvious from the conversation.
Examples:
- Previous turn showed ASUS laptops → "find cheaper ones" → category="Laptop", \
  preference carries ASUS context, update budget if user specified one, intent=SEARCH.
- Previous turn showed Nike shoes → "do you have those in size 43?" → category="Shoes", \
  preference="Nike + size 43", carry forward the budget, intent=SEARCH or CLARIFY.
- Previous turn showed headphones → "what about a wireless version?" → category="Headphones", \
  preference updates to "wireless", carry forward budget and brand, intent=SEARCH.

## Localized Search Query (SEARCH intent only)
Craft a `localized_search_query` — a short, clean product search string optimised for
e-commerce search engines in the user's country. This applies to EVERY country and language,
not just English or Romanian. Apply ALL of the following rules:

RULE 1 — TRANSLATE to local e-commerce terminology for the user's country.
  Use the exact words that local shoppers and retailers actually use in that language.
  Do NOT use a literal English translation or a literal translation of the user's words.
  Think: "what would a shopper in this country type into the local Amazon / eMAG / Otto / Fnac?"
  Examples across languages:
  • Romania:  "rucsac laptop"      (NOT "geantă de școală laptop" or "laptop bag")
  • Romania:  "telefon mobil"      (NOT "mobile phone" / "smartphone")
  • Germany:  "Laptop Rucksack"    (NOT "laptop bag" or "Schultasche für Laptop")
  • France:   "sac à dos ordinateur" (NOT "laptop school bag")
  • Spain:    "mochila portátil"   (NOT "bolsa escolar laptop")
  • Japan:    "ノートPC バックパック"  (NOT English or literal translation)
  • Poland:   "plecak na laptopa"  (NOT English or literal translation)
  If the user's location is unknown, use concise standard English terms.

RULE 2 — NO PRICE, NO BUDGET, NO PURCHASE INTENT WORDS in the query — in ANY language.
  Never include price numbers, currency codes, or words meaning "buy/under/cheap" in any
  language (e.g. "buy", "under", "sub", "kaufen", "acheter", "comprar", "cumpara", etc.).
  Budget filtering is handled entirely by the scoring engine — injecting prices into the
  Tavily query returns zero product listing pages for most niche items.

RULE 3 — SHORT AND SPECIFIC: 2–6 words maximum.
  Include only the product name in local terminology + the single most important spec or brand.
  Example (Romania): "ASUS laptop 16GB RAM" — not "ASUS laptop 16GB RAM gaming sub 2000 RON"
  Example (Germany): "ASUS Gaming Laptop 16GB" — not "ASUS Laptop kaufen unter 2000 EUR"

RULE 4 — USE A SPECIFIC MODEL NAME, never a generic category.
  A generic category term ("mountain bike", "TV", "laptop", "gaming chair") returns category
  grids and search result pages — never a buyable product page. An exact model name
  ("Rockrider ST 120 29", "LG OLED42C31LA", "ASUS TUF Gaming A15") returns the actual PDP.
  When `specific_models` is populated (see below), use the FIRST entry as the primary term
  in `localized_search_query`. Translate or localise spelling only if the model has an official
  regional variant name; otherwise keep the manufacturer's exact model identifier verbatim.
  ✓ specific_models[0] = "Rockrider ST 120 29" → query: "Rockrider ST 120 29"
  ✓ specific_models[0] = "ASUS TUF Gaming A15 2024" → query: "ASUS TUF Gaming A15 2024"
  ✗ "biciclete MTB" — generic, returns category pages
  ✗ "gaming laptop" — generic, returns category pages
  When `specific_models` is null (user named a specific model already), the user's own model
  name IS the specific term — use it directly in `localized_search_query`.

## Local Domain Selection (SEARCH intent only)
Populate local_domains with 3–5 e-commerce domains that best serve the user's location
and product category. Rules:
- CRITICAL: You MUST prioritise independent, mid-market, and niche specialist retailers
  (e.g., afisport.ro, pcgarage.ro, notino.ro, tradeinn.com, veloteca.ro).
- LIMIT massive enterprise aggregators: You may include a MAXIMUM of ONE giant enterprise
  domain (like emag.ro, amazon.com, walmart.com, decathlon) as a fallback.
  The rest of the array MUST be mid-market or independent specialists.
- Match the domain to the category (e.g., bike24.com for sports, elefant.ro for books).
- Only include domains where the user's budget currency is the standard checkout currency.
- If the user's location is unknown or no suitable local domains exist, set local_domains to null.
For CHAT/CLARIFY intent: always null.

## Refinement Detection (is_refinement flag)
Set `is_refinement` to true when the user is modifying, filtering, or rejecting the products
they were just shown — NOT starting an entirely new search. Triggers:
  ✓ "cheaper" / "find me cheaper ones" / "cheaper alternatives"
  ✓ "in black" / "different color" / "the red version"
  ✓ "different brand" / "not ASUS" / "from another manufacturer"
  ✓ "show me others" / "find alternatives" / "more options"
  ✓ "same but [any modification]" / "similar but [any change]"
  ✓ "I'm not satisfied because: [reason]" — explicit rejection of the products shown
  ✗ A completely new product category → is_refinement=false
  ✗ A question about one of the products → is_refinement=false (CHAT or CLARIFY)

## Exclusion & Price Floor (excluded_keywords + price_floor)
When the user complains that results were WRONG CATEGORY (accessories instead of the product
itself, toy instead of real item, spare parts instead of complete product):
  • Populate `excluded_keywords` with a JSON array of LOWERCASE terms that must NOT appear
    in product titles or category breadcrumbs. Think about synonyms in the user's language.
    Example — user wanted real bikes but got accessories:
      ["accessories", "accesorii", "accessorio", "accessoire", "zubehör",
       "spare part", "piesa", "toy", "jucarie", "kit", "cover", "case", "bag",
       "bell", "lock", "pump", "saddle", "handlebar", "helmet", "glove"]
    Example — user wanted a laptop but got sleeves/bags:
      ["bag", "sleeve", "case", "cover", "stand", "geanta", "husa", "suport"]
  • Leave `excluded_keywords` as an empty array [] when the user is only changing price
    or color — do NOT populate it for those refinements.
  • Set `price_floor` to the MINIMUM realistic price (in budget_currency) for the ACTUAL
    product in the target market. This catches retailers embedding cheap accessories or toys
    inside a product-category search. Use your world knowledge about market prices.
    Examples (Romania, RON): mountain bike→400, road bike→800, laptop→1500, smartphone→400,
    TV 40"→700, gaming chair→500, espresso machine→200, running shoe→150.
    Examples (Germany, EUR): mountain bike→200, laptop→400, smartphone→200, TV 40"→200.
    Set to null when the search is for inherently cheap items or when uncertain.

DYNAMIC BUDGET DROP — applies when the user asks for "cheaper" alternatives:
  The assistant message in the chat history lists the products that were shown, including
  their prices. You MUST use those prices to lower budget_max mathematically.
  Algorithm:
    1. Read the previous assistant message and identify the prices listed there.
    2. Find the lowest confirmed price among those products.
    3. Set the new budget_max to 80% of that lowest price, rounded down to a clean integer.
    4. If the user explicitly states a new budget ceiling ("under 1200 RON"), use that directly.
    5. If no prices appear in history, set intent=CLARIFY and ask for a budget ceiling.
  Example: assistant showed items at 1799, 1950, 1600 RON →
    lowest=1600 → new budget_max = int(1600 × 0.80) = 1280.
  For refinements, reuse the same localized_search_query (same product, same language);
  only budget_max and/or preference need to change.

## Global Search Override (search_globally flag)
Set `search_globally` to true when the user explicitly requests results from outside their \
local market — regardless of what local_domains would normally be selected. Examples:
  ✓ "find cheaper alternatives globally" → search_globally=true, local_domains=null
  ✓ "search worldwide / internationally" → search_globally=true, local_domains=null
  ✓ "I don't care where it ships from, find the cheapest" → search_globally=true
  ✓ "can you look outside [country]?" → search_globally=true
  ✗ "find cheaper ones" with no geographic qualifier → search_globally=false (resolve \
     the product reference but keep the user's normal locale)
When search_globally is true, always set local_domains to null — the global pipeline \
needs no domain restriction.
For CHAT/CLARIFY intent: always false.

## No-Preference Handling
If the user explicitly says they have no brand preference, no specific requirements, or limited
product knowledge (e.g. "I don't care about brand", "no preference", "I don't know much about X",
"surprise me", "just the best one"), treat this as preference = "best value for budget".
- If category AND budget are known: use SEARCH immediately with preference = "best value for budget".
- If category OR budget is still missing: use CLARIFY to ask only for the missing parameter.
- NEVER loop asking for preferences the user already said they don't have.

## Adaptive Requirement Gate — Complex & High-Stakes Items
For high-complexity categories, a brand or size alone is NOT enough — you MUST have at least
one specific USE CASE before firing a SEARCH. If the use case is absent, ask for it with CLARIFY.

HIGH-COMPLEXITY CATEGORIES (apply this gate):
  laptop, notebook, gaming pc, desktop, computer, ultrabook, macbook,
  smartphone, phone, iphone, android,
  camera, dslr, mirrorless,
  tv, television, monitor, display,
  washing machine, dryer, dishwasher, refrigerator, fridge, air conditioner,
  vacuum cleaner, robot vacuum,
  premium headphones, wireless headphones, noise-cancelling headphones,
  gaming console, playstation, xbox, nintendo,
  tablet, ipad, e-reader,
  smartwatch, fitness tracker.

APPLY the gate when ALL of the following are true:
  1. The category is in the high-complexity list above.
  2. The preference contains ONLY a brand or a size — no use case, no scenario, no activity.
  3. The user has NOT already described a use case in any earlier turn.

DO NOT APPLY the gate when ANY of the following is true:
  • The preference or category already implies a use case:
    "gaming laptop" → use case is gaming ✓
    "laptop for video editing" → use case is editing ✓
    "camera for travel" → use case is travel photography ✓
    "TV for bedroom" → use case is bedroom viewing ✓
    "running shoes" → use case is running ✓
  • The user said they have no preference → fall through to No-Preference Handling above.
  • The user is refining a previous search (is_refinement=true).

WHEN the gate triggers: set intent=CLARIFY and ask exactly ONE question — the single most
impactful use-case question for the category. Examples:
  Laptop + only brand  → "What will you mainly use it for — office work, gaming, or creative work?"
  Smartphone + only brand → "Is photography, gaming, or battery life most important to you?"
  Headphones + only brand → "Will you use them for commuting, gaming, or studio monitoring?"
  TV + only brand/size → "What's the main use — movies/streaming, gaming, or a bedroom setup?"

LOW-COMPLEXITY CATEGORIES (skip the gate — fire SEARCH as soon as 3 parameters are present):
  cables, accessories, bags, books, clothing, shoes, toys, kitchen tools,
  fitness accessories, office supplies, consumables, chargers, mice, keyboards,
  basic speakers, earbuds (under budget ceiling), simple appliances.

## Specific Model Names (SEARCH intent only)
When the user has NOT named a specific product model or SKU, use your world knowledge to
populate `specific_models` with 2–3 real, currently-sold models that best match the request.

Rules:
- Models must satisfy ALL stated constraints: category, budget ceiling, preference, use case.
- Use the exact commercial name a shopper would type into a retailer's search bar
  (e.g. "Rockrider ST 120 29", "ASUS TUF Gaming A15 2024", "Logitech MX Master 3S").
  Never use a generic category descriptor ("mountain bike 29er") — that is not a model name.
- Prefer bestsellers and highly-reviewed models that are actively stocked in the user's region.
- Omit any model whose typical market price clearly exceeds the user's budget ceiling.
- Set to null when the user already specified a brand + model or a full SKU — do not rephrase.
  → null: "Sony WH-1000XM5", "iPhone 16 Pro", "ASUS VivoBook 16 X1605"
  → populate: "wireless headphones under 1500 RON", "mountain bike for adults", \
"gaming laptop under 4000 RON", "office chair", "wireless mouse"
- Set to null for CHAT/CLARIFY intent.

## GPU Generation Disambiguation (applies to all gaming laptop/desktop searches)
When a user expresses a GPU floor using "RTX X000+", "RTX Xk or better", or "RTX X-series":

CONSUMER GAMING TIERS — always use these full model names in specific_models and localized_search_query:
  "RTX 2000+" / "RTX 20xx or newer" → RTX 2060 / RTX 2070 / RTX 2080
  "RTX 3000+" / "RTX 30xx or newer" → RTX 3060 / RTX 3070 / RTX 3080
  "RTX 4000+" / "RTX 40xx or newer" → RTX 4060 / RTX 4070 / RTX 4080
  "RTX 5000+" / "RTX 50xx or newer" → RTX 5060 / RTX 5070 / RTX 5080

PROFESSIONAL / WORKSTATION SERIES — NEVER use for consumer gaming searches:
  RTX 2000 Ada, RTX 4000 Ada, RTX 4500 Ada, RTX 6000 Ada — professional workstation cards
  RTX A2000, RTX A4000, RTX A5000, RTX A6000 — NVIDIA professional / datacenter series

CRITICAL: "RTX 2000+" means "gaming RTX 2060/2070/2080" — NOT "RTX 2000 Ada" and NOT "RTX A2000".
These workstation GPUs are entirely different product lines, cost 3-10× more, and are never
found in consumer gaming laptops. Never emit a bare "RTX 2000" in a search query — it
resolves to the workstation Ada GPU, not any consumer card.
Example — user: "gaming laptop RTX 2000+ 16GB RAM under 10000 RON":
  ✓ specific_models: ["ASUS TUF Gaming A15 RTX 2060", "Lenovo Legion 5 Gen 7 RTX 2070"]
  ✓ localized_search_query: "ASUS TUF Gaming A15 RTX 2060"
  ✗ specific_models: ["laptop RTX 2000 Ada 16GB"] — WRONG: workstation GPU
  ✗ localized_search_query: "laptop gaming RTX 2000 16GB RAM" — WRONG: maps to workstation series

## REQUIRED OUTPUT FORMAT
Respond with a single valid JSON object. No markdown fences. No prose outside the JSON.
The "local_domains" field must be either a JSON array of domain strings or JSON null — never \
any other value.
{
  "intent": "CHAT",
  "reply": "string for CHAT or CLARIFY intent; null for SEARCH",
  "collected_params": {
    "category": "string or null",
    "budget": "human-readable string or null",
    "budget_max": 0.0,
    "budget_currency": "ISO 4217 string or null",
    "preference": "string or null"
  },
  "search_query": null,
  "localized_search_query": "localized e-commerce search string or null",
  "local_domains": null,
  "search_globally": false,
  "is_refinement": false,
  "excluded_keywords": [],
  "price_floor": null,
  "specific_models": null,
  "language_code": "ISO 639-1 code of the user's language (e.g. 'en', 'ro', 'de', 'fr', 'it', 'es', 'pl', 'nl', 'pt')"
}
"""

# Scoring weights
# cost_efficiency + quality_confidence together represent quality-price ratio (75%).
SCORE_WEIGHTS = {
    "cost_efficiency": 0.40,
    "quality_confidence": 0.35,
    "logistics": 0.15,
    "trust": 0.10,
}


# Helpers

def _build_contents(messages) -> list[types.Content]:
    """Convert the full message list into Gemini Content objects."""
    contents: list[types.Content] = []
    for msg in messages:
        role = "user" if msg.role == "user" else "model"
        parts: list[types.Part] = []
        if msg.role == "user" and msg.image_base64:
            parts.append(
                types.Part(
                    inline_data=types.Blob(
                        mime_type="image/webp",
                        data=base64.b64decode(msg.image_base64),
                    )
                )
            )
        parts.append(types.Part(text=msg.content))
        contents.append(types.Content(role=role, parts=parts))
    return contents


# Public API

def _location_block(city: str, country: str) -> str:
    """Build the location section appended to the system prompt when location is known."""
    if not city and not country:
        return ""
    label = ", ".join(filter(None, [city, country]))
    return f"""

## User Location
The user is located in {label}.
- Prioritise e-commerce retailers that operate in this region (stock, local pricing, fast delivery).
- For localized_search_query: use the product terminology that shoppers in {country} actually type into local e-commerce sites — in the local language, following the Localized Search Query rules above.
- If the user has not specified a currency, assume the local currency for this region.
"""


def classify_intent(messages, city: str = "", country: str = "") -> dict:
    """
    Lightning-fast intent gate. Returns CHAT, CLARIFY, or SEARCH.
    Tavily and Jina stay asleep unless this returns SEARCH.
    Runs synchronously — call via run_in_threadpool from async handlers.
    """
    contents = _build_contents(messages)
    system = _SYSTEM_PROMPT + _location_block(city, country)

    _clarify_fallback = {
        "intent": "CLARIFY",
        "reply": "I'm here to help you find the best product! Could you tell me what you're looking for and your budget?",
        "collected_params": {
            "category": None,
            "budget": None,
            "budget_max": None,
            "budget_currency": None,
            "preference": None,
        },
        "search_query": None,
        "localized_search_query": None,
        "local_domains": None,
        "search_globally": False,
        "is_refinement": False,
    }

    raw_intent = ""
    try:
        response = _with_backoff(
            _client.models.generate_content,
            model=_FLASH,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0.1,
                max_output_tokens=4096,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        raw_intent = getattr(response, "text", None) or ""
        return json.loads(raw_intent)
    except errors.ServerError:
        logger.warning("[INTENT] Gemini overloaded — routing to Groq circuit breaker")
        groq_result = _groq_intent(system, messages)
        if groq_result:
            return groq_result
        _clarify_fallback["reply"] = (
            "The AI is temporarily experiencing high traffic. Please try your search again in a few seconds."
        )
        return _clarify_fallback
    except (json.JSONDecodeError, AttributeError, TypeError):
        logger.warning("[INTENT] JSON parse failed — raw: %.200s", raw_intent)
        return _clarify_fallback
    except Exception as exc:
        logger.warning("[INTENT] Gemini error — routing to Groq circuit breaker: %s", exc)
        groq_result = _groq_intent(system, messages)
        return groq_result if groq_result else _clarify_fallback


def score_and_rank_products(
    scraped_results: list[dict],
    search_description: str,
    budget_max: Optional[float],
    budget_currency: Optional[str],
    city: str = "",
    country: str = "",
    is_global: bool = False,
    user_language: str = "English",
    community_picks: list[str] | None = None,
) -> list[dict]:
    """
    Feed all scraped Markdown pages to Gemini and return up to 3 ranked by value score.
    Formula: value_score = 0.40×cost_efficiency + 0.35×quality + 0.15×logistics + 0.10×trust
    is_global=True: drops local-delivery constraints and adds currency-conversion authorization.
    Runs synchronously — call via run_in_threadpool from async handlers.
    """
    url_manifest = "\n".join(
        f"  {i + 1}. {r['url']}" for i, r in enumerate(scraped_results)
    )

    products_block = ""
    for i, r in enumerate(scraped_results, 1):
        # Compress markdown to signal-dense lines only — eliminates navigation,
        # SEO prose, cookie banners, and image arrays that bloat the prompt.
        md = _compress_markdown(r.get("markdown") or "", max_chars=600)
        jsonld = r.get("jsonld") or {}
        facts_header = build_facts_header(jsonld)

        logistics_ctx = ""
        return_note = ""
        if not is_global:
            policy_url = r.get("shipping_policy_url") or ""
            if policy_url:
                logistics = extract_dynamic_logistics(policy_url, country, city)
                if logistics:
                    logistics_ctx = _format_dynamic_logistics_ctx(
                        _extract_domain_simple(r["url"]), city, country, logistics
                    )
            return_text = (r.get("return_policy_text") or "")[:250]
            if return_text:
                return_note = f"### RETURN POLICY\n{return_text}\n\n"

        products_block += (
            f"\n\n---\n"
            f"## PRODUCT {i}\n"
            f"Title: {r.get('title', 'Unknown')}\n"
            f"URL: {r['url']}\n\n"
            f"{facts_header}{logistics_ctx}{return_note}{md}"
        )

    budget_str = f"{budget_max} {budget_currency}" if budget_max else "not specified"
    budget_120_str = (
        f"{int(budget_max * 1.2)} {budget_currency}" if budget_max else "not specified"
    )
    location_str = ", ".join(filter(None, [city, country])) or "unknown"

    # Geo-context blocks — swapped out for global searches
    if is_global:
        currency_block = f"""\
## CURRENCY CONVERSION (GLOBAL SEARCH MODE)
Products may be priced in USD, EUR, GBP, JPY, or other currencies.
The user's budget is {budget_str}. You are AUTHORIZED to use your knowledge of approximate
current exchange rates to decide whether a product is within budget.
Algorithm: convert the listed price to {budget_currency or "the user's currency"} using your
best current estimate, then apply the budget check.
CRITICAL: Do NOT eliminate a product solely because its price is in a foreign currency.
Convert first, then decide. Note the original price and your conversion in the reasoning.
If you cannot determine the exchange rate at all, assign cost_efficiency=40 and note
"Price in foreign currency — verify conversion before purchase".\n"""
        search_context_block = (
            f"User request: {search_description}\n"
            f"Budget ceiling: {budget_str} — paying LESS (in any currency) is ideal.\n"
            f"Search scope: GLOBAL — products from any country are welcome. "
            f"Do NOT penalise international shipping or non-local retailers."
        )
        logistics_rubric = (
            "LOGISTICS & CONVENIENCE (15% weight) — GLOBAL MODE\n"
            "Focus on international shipping availability, not same-day local delivery.\n"
            "  100 — Ships internationally with express (3–7 days) or Prime-like service\n"
            "   70 — Ships internationally; standard 10–20 day delivery available\n"
            "   40 — International shipping status unclear from the page\n"
            "    0 — Confirmed ships to home country only, or confirmed out of stock"
        )
        unverified_shipping_note = (
            "5. If international shipping availability is unclear, assign logistics score 40 "
            "and note \"International shipping unverified\". Do NOT score 0."
        )
    else:
        currency_block = ""
        search_context_block = (
            f"User request: {search_description}\n"
            f"Budget ceiling: {budget_str} — the user will not pay MORE than this; paying LESS is ideal.\n"
            f"User location: {location_str} — prefer retailers that serve this region; "
            f"give higher logistics scores to local or regional sellers."
        )
        logistics_rubric = (
            f"LOGISTICS & CONVENIENCE (15% weight)\n"
            f"Each product may include a '### VENDOR LOGISTICS CONTEXT' block above its page text.\n"
            f"When that block is present, its '→ LOGISTICS SCORE GUIDANCE' line gives you the\n"
            f"correct score band — use it directly. Do NOT override it with page-text guesses.\n"
            f"When no context block is present, FIRST apply your knowledge of the retailer's\n"
            f"typical delivery speed for {location_str} before falling back to the rubric below.\n"
            f"Examples of retailer knowledge you should use:\n"
            f"  - Amazon Prime (any country): 1–2 day delivery → score 90–100 if in stock\n"
            f"  - eMag.ro, Altex.ro, Flanco.ro in Romania: next-day or same-day → score 90\n"
            f"  - MediaMarkt, Saturn (DE/AT/CH/RO): 1–3 days → score 80\n"
            f"  - Zalando, ASOS, H&M (EU): 3–5 days standard → score 70\n"
            f"  - Walmart.com (US), Target.com (US): 2–5 days standard → score 70\n"
            f"  - AliExpress (global): 10–30 days → score 40\n"
            f"Only fall back to the rubric below if the retailer is completely unknown to you:\n"
            f"  100 — In stock + same-day or next-day delivery confirmed on page\n"
            f"   70 — In stock + standard 2–5 day delivery confirmed on page\n"
            f"   40 — Delivery time unverified and retailer unknown for {location_str}\n"
            f"    0 — Confirmed out of stock or discontinued"
        )
        unverified_shipping_note = (
            f"5. If a VENDOR LOGISTICS CONTEXT block is present for a product, follow its "
            f"'→ LOGISTICS SCORE GUIDANCE' line. "
            f"If no context block is present, use your knowledge of the retailer's typical "
            f"delivery for {location_str} to assign the correct score. "
            f"Only use score 40 if the retailer is completely unknown to you. "
            f"Do NOT score 0 for missing logistics data."
        )

    # Build optional community picks block — injected when research found consensus
    picks = [p for p in (community_picks or []) if p]
    community_block = ""
    if picks:
        picks_str = ", ".join(f'"{m}"' for m in picks[:4])
        community_block = (
            f"\n## COMMUNITY RESEARCH SIGNAL\n"
            f"Reddit, Twitter/X, and tech forums widely recommend these models for this use case: {picks_str}\n"
            f"If a product's title contains one of these names, you MAY increase its "
            f"quality_confidence by up to 10 points — only when other quality evidence "
            f"(rating, specs, reviews) also supports it. This is a soft signal, not a mandate.\n"
        )

    prompt = f"""\
You are performing product value scoring for a shopping search. Your goal is to find the \
best quality-price ratio — not the most expensive option, and not the cheapest regardless of quality.
{community_block}
## AUTHORISED PRODUCT URLs — {len(scraped_results)} total
You MUST copy these URLs verbatim into your response. Never invent, shorten, or alter any URL.
{url_manifest}
{currency_block}
## STEP 1 — INVENTORY & PURCHASABILITY CHECK (run this BEFORE scoring)
The user's absolute maximum budget is {budget_str}.
For each product page, answer two binary questions before you touch any score:

  A. IS IT PURCHASABLE? — POSITIVE SIGNAL REQUIRED
     A product passes this check if it has ANY ONE of these signals:

     TIER 1 — Machine-verified (strongest): The MACHINE-VERIFIED DATA block above the
     product text contains "CONFIRMED AVAILABILITY: In Stock". This alone is sufficient —
     do NOT require a buy button when JSON-LD availability is confirmed.

     TIER 2 — Page-text buy buttons (any language):
       "Add to cart" / "Add to Cart" / "Adaugă în coș" / "Adauga in cos"
       "Buy now" / "Buy Now" / "Cumpără" / "Cumpara acum"
       "Order now" / "Place order" / "Checkout" / "Purchase"
       "Bestellung aufgeben" / "In den Warenkorb" (German)
       "Ajouter au panier" / "Commander" (French)
       "Añadir al carrito" / "Comprar" (Spanish)
       "カートに追加" / "今すぐ購入" (Japanese)
       Any clearly equivalent button or link in any other language.

     → If NEITHER Tier 1 nor Tier 2 applies → ELIMINATE immediately.
       Pages that have no confirmed stock status AND no buy button are likely
       blog posts, brand pages, or category listings. Drop them.

     ALSO ELIMINATE if any explicit negative signal is present:
       • "Stoc epuizat" / "Out of stock" / "Ruptura de stoc" / "Epuizat"
       • "Indisponibil" / "Unavailable" / "Temporarily unavailable" / "Discontinued"

  B. IS IT WITHIN BUDGET?
     Hard limit: {budget_120_str} (120% of the stated budget ceiling).
     • If confirmed price EXCEEDS {budget_120_str} → ELIMINATE immediately.
     • If confirmed price is BETWEEN {budget_str} and {budget_120_str} (slightly over budget) \
→ KEEP the product, set cost_efficiency = 0, and include "Slightly over budget \
({{price}} {{currency}})" in the reasoning field.
     • If confirmed price is AT OR BELOW {budget_str} → proceed to full scoring normally.

  → Products that fail check A or the hard limit in check B are DROPPED from the list entirely. \
Do NOT score them, do NOT include them in ranked_products.
  → If ALL products fail these checks, return "ranked_products": [].

## CRITICAL RULES — READ FIRST
1. Return 0 to 3 products — only those that passed the inventory check above and have \
enough usable data to score confidently. Never invent products, titles, prices, or URLs.
2. Missing stock data alone is NOT grounds for elimination — only explicit out-of-stock \
signals trigger the inventory check. If stock status is simply absent, keep the product \
and assign logistics score 40.
3. Use score 40 as the floor for any dimension where data is absent from the page.
   Reserve score 0 ONLY for confirmed bad signals (price between 100–120% of budget ceiling, \
confirmed out of stock, confirmed suspicious listing).
4. A product priced BELOW budget is ALWAYS a positive signal — never a reason to penalise or \
exclude it. A product at half the budget with good quality scores near 100 for cost efficiency. \
The cheaper the price relative to budget, the higher the cost_efficiency score, AS LONG AS \
the product quality is acceptable.
{unverified_shipping_note}
6. If price is not visible on the page, assign cost_efficiency score 40 and note \
"Price not listed — verify before purchase" in reasoning. Do NOT score 0.
7. The "url" field in every ranked product MUST be taken verbatim from the AUTHORISED PRODUCT \
URLs list above. If a product's URL does not appear in that list, omit the product entirely \
rather than guessing or substituting a different URL.

## Search Context
{search_context_block}

## Scoring Rubric (0–100 per dimension)

COST EFFICIENCY & VALUE FOR MONEY (40% weight)
The primary question: how much real value does the user get for what they pay?
Being under budget is GOOD. Being significantly under budget with solid quality is EXCELLENT.
  100 — Outstanding quality-price ratio: well under budget (≤70% of ceiling) AND good quality signals
   80 — Great value: under budget with decent specs/reviews, OR significantly under budget
   60 — Fair value: near budget ceiling but justified by quality
   40 — At budget ceiling with average quality, OR price not found on the page
    0 — Price is confirmed above budget ceiling (but within the 120% hard limit — product still shown with this score)

PRODUCT QUALITY CONFIDENCE (35% weight)
How confident are we this product delivers good quality relative to its price?

FINDING QUALITY SIGNALS — scan the ENTIRE product text for any of these patterns:
  • Star/numeric ratings: "4.7/5", "4.7 din 5 stele", "4,7 de stele", "4.7 out of 5",
    "4.7 von 5 Sternen", "4,7 étoiles", "★★★★☆", "Nota: 4.7", "Rating: 4.7"
  • Review counts: "1 234 reviews", "1234 pareri", "1234 Bewertungen", "1 234 avis",
    "based on 1 234 ratings", "verified purchases"
  • Quality labels: "Bestseller", "Top Seller", "Amazon's Choice", "Recomandarea eMAG",
    "Editor's Choice", "Award", "Certified"
  • Spec signals: high-end components named explicitly (e.g. "Intel Core i7", "OLED",
    "Gorilla Glass"), professional/premium tier positioning in the description
  If the CONFIRMED RATING line appears in the machine-verified header above, that is
  the authoritative source — use it directly without re-parsing.

  100 — 4.5+ stars with 200+ reviews, OR "Bestseller"/"Top Seller" badge + strong specs
   80 — 4.0–4.5 stars with 50+ reviews, OR clear quality-tier specs (premium components)
   60 — 3.5–4.0 stars with any reviews, OR 4.0+ stars with fewer than 50 reviews
   40 — Rating text found but below 3.5 stars, OR no rating/review text found anywhere
    0 — Explicitly negative quality signal (e.g. "1.5 stars", "many complaints")

{logistics_rubric}

TRUST & RISK MITIGATION (10% weight)
If a RETURN POLICY section appears above the product text, use it to adjust this score.
A generous return window (30+ days, free returns) is a strong positive signal; "all sales final"
or no return info is a negative signal.
  100 — Official brand or major authorised retailer + generous return policy (30+ day free returns)
   80 — Major retailer or official brand; standard return window offered
   70 — Well-rated 3rd-party seller (≥95% positive feedback); returns accepted
   40 — Unknown seller; no return policy info found on the page
    0 — Suspicious listing, no seller info, "all sales final", or high-risk indicators

VALUE SCORE FORMULA:
value_score = (cost_efficiency × 0.40) + (quality_confidence × 0.35) + \
(logistics × 0.15) + (trust × 0.10)
Round value_score to 1 decimal place.

## Products to Analyse
{products_block}

LANGUAGE: Write the "reasoning" field in {user_language}. All text visible to the user \
must be in {user_language}.

Return ONLY a valid JSON object with 1 to 3 products ranked by value_score (best first). \
Only include products whose URL appears in the AUTHORISED PRODUCT URLs list above:
{{
  "ranked_products": [
    {{
      "rank": 1,
      "title": "exact product title from the page",
      "url": "verbatim URL from the AUTHORISED PRODUCT URLs list above",
      "price": 299.99,
      "currency": "USD",
      "image_url": "direct image URL or null",
      "scores": {{
        "cost_efficiency": 85,
        "quality_confidence": 72,
        "logistics": 90,
        "trust": 80
      }},
      "value_score": 82.4,
      "reasoning": "2–3 sentences focused on quality-price ratio. If the product is significantly \
under the {budget_str} budget, explicitly highlight this as a positive: e.g. 'Found at X {budget_currency or ''}, \
well below the budget ceiling — excellent value for the price.' Flag any missing data."
    }}
  ]
}}"""

    logger.info(
        "[SCORING] sending %d products to Gemini (~%d tokens)",
        len(scraped_results), len(prompt) // 4,
    )
    ranked: list[dict] = []
    raw = ""
    try:
        response = _with_backoff(
            _client.models.generate_content,
            model=_FLASH,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
                max_output_tokens=8192,
            ),
        )
        raw = getattr(response, "text", None) or ""
        logger.info("[SCORING] Gemini response: %d chars — first 400: %s", len(raw), raw[:400])
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Truncate to last complete item and close the JSON structure
            cut = raw.rfind("},")
            raw = (raw[:cut + 1] if cut != -1 else raw).rstrip(", \n") + "]}"
            parsed = json.loads(raw)
        ranked = parsed.get("ranked_products", [])
        logger.info("[SCORING] parsed %d ranked_products", len(ranked))
    except errors.ServerError as exc:
        logger.warning("[SCORING] Gemini overloaded: %s", exc)
        raise RuntimeError("The AI is currently busy — please try again in a moment.") from exc
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
        logger.warning("[SCORING] Gemini JSON parse failed (%s): %.200s", exc, raw)
        return []
    except Exception as exc:
        logger.warning("[SCORING] Gemini error: %s", exc)
        raise

    # Reject hallucinated URLs. Only products whose URL came from Tavily (and is a real http URL)
    # are allowed through. This prevents example.com or invented URLs reaching the frontend.
    valid_urls = {r["url"] for r in scraped_results}
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
            "[SCORING] dropped %d hallucinated URL(s) — %d valid product(s) remain",
            before - len(ranked),
            len(ranked),
        )

    # Normalize + recompute scores deterministically.
    # LLMs sometimes output 0–1 scale (e.g. 0.85) instead of 0–100 (e.g. 85).
    # Frontend renders Math.round(value) so 0.85 → "1" — visually wrong.
    _DIMS = ("cost_efficiency", "quality_confidence", "logistics", "trust")
    for p in ranked:
        s = p.get("scores") or {}
        raw_vals = {d: float(s.get(d, 0) or 0) for d in _DIMS}

        # Detect 0–1 scale: ALL four dimension scores are ≤ 1.0
        if all(v <= 1.0 for v in raw_vals.values()):
            raw_vals = {d: round(v * 100, 1) for d, v in raw_vals.items()}

        # Detect partial 0–1 scale: any score is strictly fractional (0 < v < 1)
        # while at least one other is clearly on 0–100 scale (> 1.0)
        elif any(0.0 < v < 1.0 for v in raw_vals.values()):
            raw_vals = {
                d: (round(v * 100, 1) if 0.0 < v < 1.0 else v)
                for d, v in raw_vals.items()
            }

        # Clamp to valid range and write back
        for d in _DIMS:
            s[d] = max(0.0, min(100.0, raw_vals[d]))
        p["scores"] = s

        # Always recompute value_score — never trust the LLM's arithmetic
        p["value_score"] = round(
            s["cost_efficiency"]   * SCORE_WEIGHTS["cost_efficiency"]
            + s["quality_confidence"] * SCORE_WEIGHTS["quality_confidence"]
            + s["logistics"]          * SCORE_WEIGHTS["logistics"]
            + s["trust"]              * SCORE_WEIGHTS["trust"],
            1,
        )

    # Re-sort by the corrected score (LLM's order may have been based on wrong values)
    ranked.sort(key=lambda p: p["value_score"], reverse=True)

    # Reassign rank numbers after re-sort
    for i, p in enumerate(ranked, 1):
        p["rank"] = i

    logger.info(
        "[SCORING] final scores: %s",
        [(p.get("title", "")[:30], p["value_score"]) for p in ranked[:3]],
    )
    return ranked[:3]


def explain_no_results(
    category: str,
    preference: str,
    budget_max: Optional[float],
    budget_currency: Optional[str],
    city: str = "",
    country: str = "",
    user_language: str = "English",
) -> str:
    """
    Called when both local and global pipelines return zero scorable products.
    Returns a short, specific CLARIFY reply explaining why and suggesting adjustments.
    Runs synchronously — call via run_in_threadpool from async handlers.
    """
    budget_str = f"{int(budget_max)} {budget_currency}" if budget_max else "unspecified"
    location = ", ".join(filter(None, [city, country])) or "unknown"

    prompt = (
        f"You are ShopperAI. A product search returned zero results after checking "
        f"both local ({location}) and global shops.\n\n"
        f"IMPORTANT: Write your entire response in {user_language}.\n\n"
        f"Search details:\n"
        f"  Product: {category} — {preference}\n"
        f"  Budget: {budget_str}\n"
        f"  Location: {location}\n\n"
        f"Write a SHORT (2–3 sentences) helpful reply for the user. Include:\n"
        f"1. The most likely reason nothing was found "
        f"(e.g. budget below market floor, niche product, seasonal availability).\n"
        f"2. One or two concrete suggestions the user can act on "
        f"(raise budget, adjust specs, broaden category, etc.).\n\n"
        f"Tone: direct, friendly, no apologies. "
        f"Return ONLY the plain text message — no JSON, no markdown."
    )

    try:
        response = _with_backoff(
            _client.models.generate_content,
            model=_FLASH,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=1024,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        text = (getattr(response, "text", None) or "").strip()
        if text:
            return text
    except Exception as exc:
        logger.warning("[EXPLAIN] Gemini call failed after retries: %s", exc)

    # Deterministic fallback so we never return empty
    return (
        f"I searched both local and global shops but couldn't find a {category} "
        f"matching your criteria for {budget_str}. "
        f"This usually means the budget is below the market floor for this product type. "
        f"Would you like to raise your budget, adjust the specs, or try a broader category?"
    )


def research_community_picks(
    category: str,
    preference: str | None,
    budget: str | None,
    user_language: str = "English",
) -> dict:
    """
    Use Gemini with Google Search grounding to find product recommendations from
    Reddit, Twitter/X, and tech review communities before any e-commerce search.

    Returns:
        {
            "recommendations": ["Sony WH-1000XM5", "Bose QC45"],
            "insight": "One sentence in user_language summarising community consensus",
        }

    On failure or no consensus, returns {"recommendations": [], "insight": None}.
    Picks are passed to the scorer as a soft quality_confidence signal only —
    they are NOT injected into the Tavily query to avoid constraining results
    to expensive/out-of-budget models.
    Runs synchronously — call via run_in_threadpool from async handlers.
    """
    product_desc = " ".join(filter(None, [preference, category])).strip() or category
    budget_note = f" with a budget of {budget}" if budget else ""

    prompt = (
        f"You are a product research assistant. Do ONE focused Google search to find "
        f"the most frequently recommended specific models for: {product_desc}{budget_note}.\n\n"
        f"IMPORTANT: Write the 'insight' field in {user_language}.\n\n"
        f"Return ONLY a raw JSON object — no markdown, no explanation:\n"
        f'{{\n'
        f'  "recommendations": ["Brand Model1", "Brand Model2"],\n'
        f'  "insight": "One sentence in {user_language} summarising the community consensus"\n'
        f'}}\n\n'
        f"Rules:\n"
        f"- recommendations: 2–4 specific brand+model names (e.g. 'Sony WH-1000XM5', NOT 'Sony headphones')\n"
        f"- These are scoring hints only — do NOT worry about price matching\n"
        f"- insight: one concrete sentence about community consensus, in {user_language}\n"
        f"- If no clear consensus: {{\"recommendations\": [], \"insight\": null}}"
    )

    try:
        response = _with_backoff(
            _client.models.generate_content,
            model=_FLASH,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.2,
                max_output_tokens=1024,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        raw = (getattr(response, "text", None) or "").strip()
        if not raw:
            return {"recommendations": [], "insight": None, "query_boost": None}

        # Search-grounded responses typically embed JSON inside explanation text.
        # Use the LAST complete JSON object found (in case model echoes the example).
        matches = list(re.finditer(r"\{[^{}]*\"recommendations\"[^{}]*\}", raw, re.DOTALL))
        if not matches:
            # Fallback: try any JSON object
            matches = list(re.finditer(r"\{.*?\}", raw, re.DOTALL))
        for m in reversed(matches):  # last match is usually the answer, not the example
            try:
                data = json.loads(m.group())
                recs = [str(r) for r in (data.get("recommendations") or []) if r]
                insight = data.get("insight") or None
                if recs:
                    logger.info("[RESEARCH] community picks: %s", recs)
                    return {"recommendations": recs, "insight": insight}
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception as exc:
        logger.warning("[RESEARCH] community research failed: %s", exc)

    return {"recommendations": [], "insight": None}


def read_heavy_url_with_grounding(
    url: str,
    budget_max: Optional[float],
    budget_currency: Optional[str],
    category: str,
    user_language: str = "English",
) -> list[dict]:
    """
    Phase 4 Lane B: Gemini Flash + Google Search Grounding reads a category page or
    enterprise URL and returns up to 3 specific in-stock products as structured cards.

    Called for every heavy URL (enterprise giant, category page, unknown domain).
    Runs synchronously — call via run_in_threadpool.

    Returns list of dicts: [{name, price, currency, url, in_stock, image_url}].
    Empty list on any failure or when no matching products are found.
    """
    budget_str = f"{budget_max} {budget_currency}" if budget_max else "any price"
    parsed_domain = url.split("/")[2] if "//" in url else url.split("/")[0]

    prompt = (
        f"You are a product research assistant with access to Google Search.\n"
        f"A user wants to buy a **{category}** with a budget of {budget_str}.\n\n"
        f"Target retailer: {parsed_domain}\n"
        f"Hint URL (may be a category or search page — treat it as retailer context only, "
        f"do NOT return this URL as a result): {url}\n\n"
        f"Task: Use Google Search to find up to 3 specific **{category}** products "
        f"sold by {parsed_domain} that are currently in stock and priced at or under {budget_str}.\n\n"
        f"Each result URL MUST be a product detail page (PDP) — a page for one single product.\n"
        f"✓ Good PDP examples: amazon.com/dp/B0BVWGKM6V, emag.ro/produs-name/pd/ABCDEF, "
        f"mediamarkt.de/product/-name-1234567.html, bestbuy.com/site/product/1234567.p\n"
        f"✗ Bad URLs (never return these): amazon.com/s?k=..., emag.ro/laptopuri/c, "
        f"any URL with /search, /category, /c/, /s?, /filter, or /browse in the path\n\n"
        f"Return ONLY a raw JSON array (no markdown fences, no explanation):\n"
        f'[\n  {{"name": "exact product name", "price": 0.0, '
        f'"currency": "{budget_currency or "RON"}", '
        f'"url": "direct product detail page URL", "in_stock": true, "image_url": null}}\n]\n\n'
        f"Rules:\n"
        f"- Each url must be the page for exactly one product, not a list or category\n"
        f"- Return [] if no matching in-stock products are found within budget\n"
        f"- Do NOT include any product priced above {budget_str}"
    )

    try:
        response = _with_backoff(
            _client.models.generate_content,
            model=_FLASH,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.1,
                max_output_tokens=2048,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        raw = (getattr(response, "text", None) or "").strip()
        if not raw:
            return []

        # Extract the last JSON array in the response (model may echo the example first)
        matches = list(re.finditer(r"\[[\s\S]*?\]", raw))
        for m in reversed(matches):
            try:
                products = json.loads(m.group())
                if not isinstance(products, list):
                    continue
                from services.scraper_service import is_likely_product_url, _CAT_PATH_RE, _CAT_PARAM_RE
                valid: list[dict] = []
                for p in products:
                    if not isinstance(p, dict):
                        continue
                    url_val = str(p.get("url") or "")
                    if not url_val.startswith("http"):
                        continue
                    # Hard-reject obvious category/search/listing URLs first.
                    # _CAT_PATH_RE and _CAT_PARAM_RE catch /search, /category, ?q=, etc.
                    if _CAT_PATH_RE.search(url_val) or _CAT_PARAM_RE.search(url_val):
                        logger.info("[LANE-B] grounding returned category URL, skipping: %s", url_val)
                        continue
                    # Also reject bare domain roots and directory-style paths (trailing slash,
                    # no numeric or slug identifier after the last real segment) — these are
                    # retailer homepages or category hierarchies that slip through RULE 3.
                    from urllib.parse import urlparse as _up
                    _parsed = _up(url_val)
                    _path = _parsed.path.rstrip("/")
                    _segs = [s for s in _path.split("/") if s]
                    if not _segs:
                        logger.info("[LANE-B] grounding returned domain root, skipping: %s", url_val)
                        continue
                    if not is_likely_product_url(url_val):
                        logger.info("[LANE-B] grounding returned category URL, skipping: %s", url_val)
                        continue
                    valid.append({
                        "name": str(p.get("name") or "Unknown")[:200],
                        "price": float(p.get("price") or 0),
                        "currency": str(p.get("currency") or budget_currency or "RON"),
                        "url": url_val,
                        "in_stock": bool(p.get("in_stock", True)),
                        "image_url": p.get("image_url"),
                    })
                if valid:
                    logger.info("[LANE-B] grounding found %d product(s) for %s", len(valid), url)
                    return valid
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception as exc:
        logger.warning("[LANE-B] grounding failed for %s: %s", url, exc)

    return []


def generate_embedding(text: str) -> list[float]:
    """
    Generate a 768-dimensional text embedding for semantic cache lookup.
    Runs synchronously — call via run_in_threadpool from async handlers.
    """
    try:
        response = _with_backoff(
            _client.models.embed_content,
            model=_EMBED,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="SEMANTIC_SIMILARITY",
                output_dimensionality=768,
            ),
        )
        return response.embeddings[0].values
    except errors.ServerError as exc:
        logger.error("[EMBED] Gemini overloaded after %d attempts: %s", _BACKOFF_ATTEMPTS, exc)
        return []
    except Exception as exc:
        logger.error("[EMBED] Unexpected embedding error: %s", exc)
        return []
