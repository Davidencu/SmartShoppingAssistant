import base64
import json
import logging
from typing import Optional

from google import genai
from google.genai import types

from core.config import settings
from services.jsonld_service import build_facts_header

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=settings.gemini_api_key)

_FLASH = "gemini-2.5-flash"
_EMBED = "gemini-embedding-001"

# ─── Shopping System Prompt ────────────────────────────────────────────────────
# Injected into every Gemini call. Defines ShopperAI's identity, intent system,
# and the strict JSON contract it must honour. No fine-tuning needed.

_SYSTEM_PROMPT = """\
You are ShopperAI — an elite autonomous shopping concierge engineered for one mission: \
find the user the highest-value product at the best price, every time.

## Identity & Scope
- You ONLY discuss products, shopping, prices, e-commerce, comparisons, and purchasing decisions.
- For ANY off-topic request (coding, homework, trivia, general questions, small talk): \
respond as CHAT intent. Your reply must be exactly one sentence — a polite but firm \
decline — followed by one concrete shopping question to re-engage the user. \
Example: "I'm a shopping assistant and can't help with that, but I'd love to help you \
find a great product — what are you looking to buy today?"
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

## Local Domain Selection (SEARCH intent only)
Populate local_domains with 3–5 e-commerce domains that best serve the user's location
and product category. Rules:
- Choose domains that are popular and well-stocked IN the user's country.
- Match the domain to the category: prefer specialist retailers over generalists when relevant
  (e.g. decathlon.ro for sports equipment, emag.ro for electronics, elefant.ro for books).
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
  "is_refinement": false
}
"""

# ─── Scoring weights ───────────────────────────────────────────────────────────
# cost_efficiency + quality_confidence together represent quality-price ratio (75%).
SCORE_WEIGHTS = {
    "cost_efficiency": 0.40,
    "quality_confidence": 0.35,
    "logistics": 0.15,
    "trust": 0.10,
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

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


# ─── Public API ───────────────────────────────────────────────────────────────

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
    response = _client.models.generate_content(
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
    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, AttributeError, TypeError):
        logger.warning("Intent JSON parse failed — raw: %.200s", getattr(response, "text", ""))
        return {
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


def score_and_rank_products(
    scraped_results: list[dict],
    search_description: str,
    budget_max: Optional[float],
    budget_currency: Optional[str],
    city: str = "",
    country: str = "",
    is_global: bool = False,
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
        md = (r.get("markdown") or "")[:3000]
        facts_header = build_facts_header(r.get("jsonld") or {})
        products_block += (
            f"\n\n---\n"
            f"## PRODUCT {i}\n"
            f"Title: {r.get('title', 'Unknown')}\n"
            f"URL: {r['url']}\n\n"
            f"{facts_header}{md}"
        )

    budget_str = f"{budget_max} {budget_currency}" if budget_max else "not specified"
    budget_120_str = (
        f"{int(budget_max * 1.2)} {budget_currency}" if budget_max else "not specified"
    )
    location_str = ", ".join(filter(None, [city, country])) or "unknown"

    # ── Geo-context blocks — swapped out for global searches ──────────────────
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
            f"  100 — In stock + same-day or next-day delivery available\n"
            f"   70 — In stock + standard 2–5 day delivery\n"
            f"   40 — Delivery time unverified for {location_str}, stock status unclear\n"
            f"    0 — Confirmed out of stock or discontinued"
        )
        unverified_shipping_note = (
            f"5. If shipping time to {location_str} is unverified, assign logistics score 40 "
            f"and note \"Shipping time to {location_str} unverified\" in reasoning. Do NOT score 0."
        )

    prompt = f"""\
You are performing product value scoring for a shopping search. Your goal is to find the \
best quality-price ratio — not the most expensive option, and not the cheapest regardless of quality.

## AUTHORISED PRODUCT URLs — {len(scraped_results)} total
You MUST copy these URLs verbatim into your response. Never invent, shorten, or alter any URL.
{url_manifest}
{currency_block}
## STEP 1 — INVENTORY & PURCHASABILITY CHECK (run this BEFORE scoring)
The user's absolute maximum budget is {budget_str}.
For each product page, answer two binary questions before you touch any score:

  A. IS IT PURCHASABLE? — POSITIVE SIGNAL REQUIRED
     You MUST find at least ONE active transactional element anywhere on the page.
     Accepted signals (any language):
       "Add to cart" / "Add to Cart" / "Adaugă în coș" / "Adauga in cos"
       "Buy now" / "Buy Now" / "Cumpără" / "Cumpara acum"
       "Order now" / "Place order" / "Checkout" / "Purchase"
       "Bestellung aufgeben" / "In den Warenkorb" (German)
       "Ajouter au panier" / "Commander" (French)
       "Añadir al carrito" / "Comprar" (Spanish)
       "カートに追加" / "今すぐ購入" (Japanese)
       Any clearly equivalent button or link in any other language.

     → If NONE of these signals appear ANYWHERE on the page → ELIMINATE immediately.
       Pages that only show "In stock", "Available", product specs, reviews, or brand info
       WITHOUT an explicit buy/cart button are manufacturer spec sheets, blog posts, or
       category pages — they are NOT purchasable. Drop them.

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
  100 — Sold & shipped by official brand or major authorised retailer
   70 — Well-rated 3rd-party seller (≥95% positive feedback, many transactions)
   40 — Unknown 3rd-party seller with limited history
    0 — Suspicious listing, no seller info, or high-risk indicators

VALUE SCORE FORMULA:
value_score = (cost_efficiency × 0.40) + (quality_confidence × 0.35) + \
(logistics × 0.15) + (trust × 0.10)
Round value_score to 1 decimal place.

## Products to Analyse
{products_block}

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

    logger.info("[SCORING] sending %d products to Gemini for scoring", len(scraped_results))
    response = _client.models.generate_content(
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
        result = json.loads(raw)
        ranked = result.get("ranked_products", [])
        logger.info("[SCORING] parsed %d ranked_products", len(ranked))
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
        logger.error("[SCORING] JSON parse failed (%s) — full raw: %s", exc, raw)
        return []

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

    # Recompute value_score deterministically — never trust Gemini's arithmetic.
    for p in ranked:
        s = p.get("scores") or {}
        cost_eff  = max(0.0, min(100.0, float(s.get("cost_efficiency",  0) or 0)))
        quality   = max(0.0, min(100.0, float(s.get("quality_confidence", 0) or 0)))
        logistics = max(0.0, min(100.0, float(s.get("logistics",          0) or 0)))
        trust     = max(0.0, min(100.0, float(s.get("trust",              0) or 0)))
        # Store clamped values back so the rest of the pipeline sees clean numbers
        s["cost_efficiency"]   = cost_eff
        s["quality_confidence"] = quality
        s["logistics"]         = logistics
        s["trust"]             = trust
        p["scores"] = s
        p["value_score"] = round(
            cost_eff * SCORE_WEIGHTS["cost_efficiency"]
            + quality * SCORE_WEIGHTS["quality_confidence"]
            + logistics * SCORE_WEIGHTS["logistics"]
            + trust * SCORE_WEIGHTS["trust"],
            1,
        )

    # Re-sort by the corrected score (Gemini's order may have been based on wrong values)
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
        response = _client.models.generate_content(
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
        logger.warning("[EXPLAIN] Gemini call failed: %s", exc)

    # Deterministic fallback so we never return empty
    return (
        f"I searched both local and global shops but couldn't find a {category} "
        f"matching your criteria for {budget_str}. "
        f"This usually means the budget is below the market floor for this product type. "
        f"Would you like to raise your budget, adjust the specs, or try a broader category?"
    )


def generate_embedding(text: str) -> list[float]:
    """
    Generate a 768-dimensional text embedding for semantic cache lookup.
    Runs synchronously — call via run_in_threadpool from async handlers.
    """
    response = _client.models.embed_content(
        model=_EMBED,
        contents=text,
        config=types.EmbedContentConfig(
            task_type="SEMANTIC_SIMILARITY",
            output_dimensionality=768,
        ),
    )
    return response.embeddings[0].values
