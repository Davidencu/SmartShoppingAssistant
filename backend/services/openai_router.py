"""
Front-end router: gpt-4o-mini for zero-latency intent classification.

First gate in the pipeline — handles ALL intent classification, parameter
extraction, and search query generation. Adds `is_mainstream` detection
so commodity searches bypass the niche scraper and go directly to Gemini
Search Grounding for live enterprise-retailer prices.

Falls back to Gemini classify_intent on any OpenAI failure.
"""
import json
import logging
import time

from core.config import settings
from services.gemini_service import _SYSTEM_PROMPT as _GEMINI_PROMPT, _location_block

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"
_BACKOFF_ATTEMPTS = 3

_openai_client = None
try:
    if settings.openai_api_key:
        import openai as _openai_lib
        _openai_client = _openai_lib.OpenAI(api_key=settings.openai_api_key)
        logger.info("[OPENAI-ROUTER] client ready (%s)", _MODEL)
except Exception as exc:
    logger.warning("[OPENAI-ROUTER] init failed: %s", exc)


# Injected before ## REQUIRED OUTPUT FORMAT so the model learns the new field.
_MAINSTREAM_SECTION = """
## Mainstream Commodity Detection (SEARCH intent only)
Set `is_mainstream` to true when the product is a mass-market commodity primarily sold by
enterprise giants (Amazon, Walmart, eMag, MediaMarkt, Apple Store, Decathlon, Zalando,
Target, Best Buy) AND essentially interchangeable across all major retailers.
Examples of MAINSTREAM products (→ true):
  ✓ Latest iPhone / Samsung Galaxy / Pixel flagship smartphones
  ✓ PS5, Xbox Series X, Nintendo Switch gaming consoles
  ✓ Specific major-brand TV models: "LG OLED C3 55 inch", "Samsung Neo QLED 65"
  ✓ Major appliances: washing machine / fridge / dishwasher from Bosch/Samsung/LG/Whirlpool
  ✓ Mass-market footwear sold everywhere: Nike Air Max, Adidas Ultraboost, Converse
  ✓ Apple products (MacBook, iPad, AirPods) — sold through Apple Store and all chains
  ✓ Commodity accessories: standard HDMI cables, USB hubs, phone screen protectors
  ✓ Any product where the user names an exact model from a mass-distribution brand
Examples of NICHE products (→ false, use niche scraper):
  ✗ Specialty cycling / triathlon / climbing equipment
  ✗ Independent or boutique fashion brands
  ✗ Photography equipment from specialist retailers (camera shops, B&H, Adorama)
  ✗ Artisan, handmade, or limited-run goods
  ✗ Mid-market enthusiast electronics (custom PC parts, audiophile gear)
  ✗ Any request where the user explicitly wants independent or specialty stores
  ✗ Products from niche brands not sold on Amazon or major chains
For CHAT/CLARIFY intent: always false.
"""

# Shared ShopperAI prompt (from Gemini) + mainstream detection + is_mainstream field.
_SYSTEM_PROMPT = (
    _GEMINI_PROMPT
    .replace(
        "## REQUIRED OUTPUT FORMAT",
        _MAINSTREAM_SECTION + "\n## REQUIRED OUTPUT FORMAT",
    )
    .replace(
        '  "language_code": "ISO 639-1 code of the user\'s language (e.g. \'en\', \'ro\', \'de\', \'fr\', \'it\', \'es\', \'pl\', \'nl\', \'pt\')"',
        '  "language_code": "ISO 639-1 code of the user\'s language (e.g. \'en\', \'ro\', \'de\', \'fr\', \'it\', \'es\', \'pl\', \'nl\', \'pt\')",\n  "is_mainstream": false',
    )
)


def classify_intent_and_route(messages, city: str = "", country: str = "") -> dict:
    """
    gpt-4o-mini front-end router: full intent classification + mainstream detection.

    Returns the same dict shape as gemini_service.classify_intent plus:
      - `is_mainstream` (bool) — True for commodity products, triggers grounding bypass.

    Falls back to Gemini classify_intent if OpenAI is unavailable or fails.
    Runs synchronously — call via run_in_threadpool from async handlers.
    """
    if not _openai_client:
        logger.warning("[OPENAI-ROUTER] no client configured — using Gemini fallback")
        return _gemini_fallback(messages, city, country)

    system = _SYSTEM_PROMPT + _location_block(city, country)
    oai_msgs: list[dict] = [{"role": "system", "content": system}]
    for msg in messages:
        role = "user" if msg.role == "user" else "assistant"
        content = msg.content or ""
        if msg.role == "user" and getattr(msg, "image_base64", None):
            oai_msgs.append({
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/webp;base64,{msg.image_base64}"}},
                    {"type": "text", "text": content},
                ],
            })
        else:
            oai_msgs.append({"role": role, "content": content})

    delay = 1.0
    for attempt in range(_BACKOFF_ATTEMPTS):
        try:
            import openai as _openai_lib
            resp = _openai_client.chat.completions.create(
                model=_MODEL,
                messages=oai_msgs,
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=4096,
            )
            raw = resp.choices[0].message.content or ""
            result = json.loads(raw)
            result.setdefault("is_mainstream", False)
            logger.info(
                "[OPENAI-ROUTER] intent=%s is_mainstream=%s query=%r",
                result.get("intent"),
                result.get("is_mainstream"),
                result.get("localized_search_query"),
            )
            return result
        except (_openai_lib.RateLimitError, _openai_lib.InternalServerError) as exc:
            if attempt == _BACKOFF_ATTEMPTS - 1:
                logger.error(
                    "[OPENAI-ROUTER] overloaded after %d attempts — Gemini fallback: %s",
                    _BACKOFF_ATTEMPTS, exc,
                )
                break
            logger.warning(
                "[OPENAI-ROUTER] attempt %d/%d overloaded, retrying in %.0fs…",
                attempt + 1, _BACKOFF_ATTEMPTS, delay,
            )
            time.sleep(delay)
            delay *= 2
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            logger.warning("[OPENAI-ROUTER] JSON parse failed: %s", exc)
            break
        except Exception as exc:
            logger.warning("[OPENAI-ROUTER] unexpected error: %s", exc)
            break

    return _gemini_fallback(messages, city, country)


def _gemini_fallback(messages, city: str, country: str) -> dict:
    """Circuit-breaker fallback to Gemini when OpenAI is unavailable."""
    logger.warning("[OPENAI-ROUTER] activating Gemini classify_intent fallback")
    from services import gemini_service
    result = gemini_service.classify_intent(messages, city, country)
    result.setdefault("is_mainstream", False)
    return result


def sanity_check_products(
    ranked: list[dict],
    user_category: str,
    user_preference: str | None = None,
) -> list[dict]:
    """
    OpenAI sanity check: verify each Gemini-ranked product actually matches
    what the user asked for. Catches hallucinated categories (user asked for
    bikes, Gemini returned cars) and product-category page titles returned as
    if they were individual products.

    Checks ONLY product type correctness — never scores, prices, or quality.
    Fails open (returns all products unchanged) if OpenAI is unavailable.
    Runs synchronously — call via run_in_threadpool from async handlers.
    """
    if not ranked or not _openai_client:
        return ranked

    query_desc = " ".join(filter(None, [user_preference, user_category])).strip() or user_category
    products_payload = [
        {"index": i + 1, "title": p.get("title") or p.get("url", "")}
        for i, p in enumerate(ranked)
    ]

    prompt = (
        f"A user searched for: \"{query_desc}\"\n\n"
        f"An AI returned these products:\n"
        f"{json.dumps(products_payload, ensure_ascii=False)}\n\n"
        f"For each product, check ONLY whether it is the correct TYPE of product "
        f"the user asked for.\n"
        f"- \"approved\" = the title matches the expected product category "
        f"(e.g. user asked for bikes → result is a bike)\n"
        f"- \"denied\" = the title is clearly a different product type "
        f"(e.g. user asked for bikes but result is a car, helmet, or accessory), "
        f"OR the title looks like a product category page rather than a specific product\n\n"
        f"Rules:\n"
        f"- Do NOT consider price, quality, brand, or scores — only product type.\n"
        f"- If you are unsure, approve it.\n"
        f"- A specific model name from the right category is always approved.\n\n"
        f"Return ONLY valid JSON, no explanation:\n"
        f"{{\"verdicts\": [{{\"index\": 1, \"verdict\": \"approved\"}}]}}"
    )

    try:
        resp = _openai_client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=256,
        )
        raw = resp.choices[0].message.content or ""
        data = json.loads(raw)
        verdicts: dict[int, str] = {
            v["index"]: v.get("verdict", "approved")
            for v in (data.get("verdicts") or [])
            if isinstance(v, dict) and "index" in v
        }
        approved = [p for i, p in enumerate(ranked, 1) if verdicts.get(i, "approved") == "approved"]
        denied_count = len(ranked) - len(approved)
        if denied_count:
            logger.warning(
                "[SANITY] OpenAI denied %d/%d product(s) for query %r — titles: %s",
                denied_count, len(ranked), query_desc,
                [ranked[i - 1].get("title", "") for i, v in verdicts.items() if v == "denied"],
            )
        else:
            logger.info("[SANITY] all %d product(s) approved for query %r", len(ranked), query_desc)
        return approved
    except Exception as exc:
        logger.warning("[SANITY] OpenAI sanity check failed, returning all products: %s", exc)
        return ranked
