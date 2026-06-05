"""
Live pipeline test — runs the full 3-phase pipeline end-to-end without HTTP.
Logs EVERYTHING: waterfall tier used, full JSON-LD, shipping data, markdown
previews, per-URL failure reasons, and per-product Gemini scores.

Run from backend/:
    python live_pipeline_test.py
"""
import asyncio
import logging
import sys
import textwrap
import time

# ── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s — %(message)s",
    stream=sys.stderr,
)
for name in (
    "services.scraper_service",
    "services.gemini_service",
    "services.tavily_service",
    "services.jsonld_service",
    "__main__",
):
    logging.getLogger(name).setLevel(logging.DEBUG)

logger = logging.getLogger("__main__")

# ── imports ───────────────────────────────────────────────────────────────────
from services import gemini_service, scraper_service, tavily_service
from services.jsonld_service import build_facts_header
from services.scraper_service import is_likely_product_url
from models.search import ChatMessage as Message

CITY    = "București"
COUNTRY = "Romania"

SEP  = "═" * 90
SEP2 = "─" * 90
SEP3 = "·" * 90

_OUT_OF_STOCK_SIGNALS = frozenset({
    "outofstock", "out of stock", "out-of-stock",
    "indisponibil", "stoc epuizat", "stoc 0",
    "rupture de stock", "nicht verfügbar", "agotado",
    "sold out", "unavailable",
})


# ── contender filter with rejection reasons ───────────────────────────────────
def _pick_contenders_verbose(scraped, budget_max, n=10):
    results = []
    for s in scraped:
        reasons = []
        md   = s.get("markdown") or ""
        jld  = s.get("jsonld") or {}
        avail = (jld.get("availability") or "").lower()
        md_head = md[:600].lower()

        if len(md) <= 200:
            reasons.append(f"THIN_CONTENT ({len(md)} chars ≤ 200)")

        if avail and any(sig in avail for sig in _OUT_OF_STOCK_SIGNALS):
            reasons.append(f"OUT_OF_STOCK (jsonld.availability={jld.get('availability')})")
        elif any(sig in md_head for sig in _OUT_OF_STOCK_SIGNALS):
            hit = next(sig for sig in _OUT_OF_STOCK_SIGNALS if sig in md_head)
            reasons.append(f"OUT_OF_STOCK (markdown signal: '{hit}')")

        if budget_max:
            price = jld.get("price")
            if price is not None:
                try:
                    if float(str(price).replace(",", ".")) > budget_max * 1.15:
                        reasons.append(
                            f"OVER_BUDGET (price={price} > {budget_max * 1.15:.0f})"
                        )
                except (TypeError, ValueError):
                    pass

        results.append((s, reasons))

    contenders = [s for s, r in results if not r]

    def _richness(s):
        score = len(s.get("markdown") or "")
        jld = s.get("jsonld") or {}
        if jld.get("price"):   score += 5_000
        if jld.get("rating"):  score += 2_000
        if jld.get("name"):    score += 1_000
        return score

    contenders.sort(key=_richness, reverse=True)
    return contenders[:n], results


# ── full URL dump ─────────────────────────────────────────────────────────────
def _dump_url(idx: int, s: dict, rejection_reasons: list[str]) -> None:
    jld = s.get("jsonld") or {}
    md  = s.get("markdown") or ""
    url = s.get("url", "?")
    blocked = s.get("_blocked", False)

    status = "✗ REJECTED" if rejection_reasons else ("⚠ BLOCKED" if blocked else "✓ PASS")
    print(f"\n  [{idx:02}] {status}  {url}")
    print(f"       Waterfall: {'BLOCKED (ghost layer used)' if blocked else 'OK'}")
    print(f"       Content  : {len(md):,} chars markdown")

    # Full JSON-LD dump
    if jld:
        print(f"       JSON-LD  :")
        for k, v in sorted(jld.items()):
            vstr = str(v)
            if len(vstr) > 100:
                vstr = vstr[:97] + "..."
            print(f"         {k:<20} = {vstr}")
    else:
        print(f"       JSON-LD  : (none extracted)")

    # Shipping info
    ship_cost = jld.get("shipping_cost")
    ship_curr = jld.get("shipping_currency", "")
    del_days  = jld.get("delivery_days")
    if ship_cost is not None or del_days:
        cost_str = "FREE" if ship_cost == 0 else (f"{ship_cost} {ship_curr}".strip() if ship_cost is not None else "?")
        print(f"       Shipping : {cost_str}  |  delivery: {del_days or '?'} days")

    # Policy links
    if s.get("shipping_policy_url"):
        print(f"       Ship URL : {s['shipping_policy_url']}")
    if s.get("return_policy_text"):
        preview = s["return_policy_text"][:120].replace("\n", " ")
        print(f"       Return   : {preview}…")

    # Markdown preview (first 400 chars, cleaned)
    if md:
        preview = " ".join(md[:400].split())
        print(f"       Preview  : {preview[:200]}")

    # Rejection reasons
    if rejection_reasons:
        for r in rejection_reasons:
            print(f"       ✗ REASON : {r}")


# ── main pipeline ─────────────────────────────────────────────────────────────
async def run_pipeline(
    user_messages: list[dict],
    test_name: str,
    city: str = CITY,
    country: str = COUNTRY,
):
    print(f"\n{SEP}")
    print(f"  TEST : {test_name}")
    print(f"  USER : {user_messages[-1]['content'][:100]}")
    print(f"  LOC  : {city}, {country}")
    print(SEP)

    messages = [Message(role=m["role"], content=m["content"]) for m in user_messages]

    # ── Intent ────────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    intent_data = gemini_service.classify_intent(messages, city, country)
    elapsed = time.perf_counter() - t0

    print(f"\n[INTENT]  ({elapsed:.2f}s)")
    print(f"  intent              : {intent_data.get('intent')}")
    print(f"  reply               : {intent_data.get('reply')}")
    cp = intent_data.get("collected_params") or {}
    print(f"  category            : {cp.get('category')}")
    print(f"  budget              : {cp.get('budget')}  max={cp.get('budget_max')}  {cp.get('budget_currency')}")
    print(f"  preference          : {cp.get('preference')}")
    print(f"  localized_query     : {intent_data.get('localized_search_query')}")
    print(f"  local_domains       : {intent_data.get('local_domains')}")
    print(f"  search_globally     : {intent_data.get('search_globally')}")
    print(f"  is_refinement       : {intent_data.get('is_refinement')}")

    if intent_data.get("intent") in ("CHAT", "CLARIFY"):
        print("\n  → Pipeline halted at CLARIFY/CHAT intent.")
        return

    localized    = intent_data.get("localized_search_query") or (
        " ".join(filter(None, [cp.get("preference"), cp.get("category")])) or "product"
    )
    search_query  = f"{localized} buy"
    local_domains = intent_data.get("local_domains") or None
    budget_max    = cp.get("budget_max")
    budget_currency = cp.get("budget_currency")
    search_globally = bool(intent_data.get("search_globally", False))

    # ── Phase 1: Tavily ───────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"[PHASE 1] Tavily Radar   query={search_query!r}")
    print(SEP2)
    t0 = time.perf_counter()

    tavily_results = []
    if local_domains:
        tavily_results = tavily_service.search_products(search_query, 20, local_domains)
        print(f"  Local ({', '.join(local_domains)}): {len(tavily_results)} URLs")

    if len(tavily_results) < 5:
        global_r = tavily_service.search_products(search_query, 15)
        print(f"  Global supplement   : {len(global_r)} URLs")
        seen = {r["url"] for r in tavily_results}
        for r in global_r:
            if r["url"] not in seen:
                tavily_results.append(r)
                seen.add(r["url"])

    print(f"  Total               : {len(tavily_results)} URLs  ({time.perf_counter()-t0:.2f}s)")
    for i, r in enumerate(tavily_results, 1):
        score = r.get("score", "?")
        print(f"    {i:2}. [{score}]  {r['url'][:85]}")

    # Drop category/listing pages before scraping
    before_shape = len(tavily_results)
    tavily_results = [r for r in tavily_results if is_likely_product_url(r["url"])]
    dropped_cat = before_shape - len(tavily_results)
    if dropped_cat:
        print(f"  Shape filter     : dropped {dropped_cat} category/listing URL(s)")

    url_to_title = {r["url"]: r.get("title", "") for r in tavily_results}
    urls = [r["url"] for r in tavily_results]

    # ── Phase 2: Scrape ───────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("[PHASE 2] Scraping — Per-URL Full Detail")
    print(SEP2)
    t0 = time.perf_counter()

    scraped = await scraper_service.scrape_urls(urls)
    for s in scraped:
        s["title"] = url_to_title.get(s["url"], "")

    elapsed = time.perf_counter() - t0
    print(f"\n  Scraped {len(scraped)} pages in {elapsed:.2f}s")

    contenders, all_results = _pick_contenders_verbose(scraped, budget_max)

    # Per-URL full dump
    for i, (s, reasons) in enumerate(all_results, 1):
        _dump_url(i, s, reasons)

    # Summary table
    print(f"\n{SEP3}")
    print(f"  SUMMARY: {len(contenders)}/{len(scraped)} pages passed contender filter")
    print(f"  {'#':>2}  {'chars':>7}  {'price':>12}  {'curr':>5}  {'rating':>15}  {'avail':>12}  {'ship':>10}  url")
    print(f"  {'-'*2}  {'-'*7}  {'-'*12}  {'-'*5}  {'-'*15}  {'-'*12}  {'-'*10}  {'-'*45}")
    for i, s in enumerate(contenders, 1):
        jld   = s.get("jsonld") or {}
        md    = s.get("markdown") or ""
        price = jld.get("price", "—")
        curr  = jld.get("currency", "—")
        rat   = jld.get("rating", "—")
        avail = jld.get("availability", "—")
        sc    = jld.get("shipping_cost")
        ship  = "FREE" if sc == 0 else (str(sc) if sc is not None else "—")
        print(f"  {i:2}  {len(md):>7,}  {str(price):>12}  {str(curr):>5}  "
              f"{str(rat)[:15]:>15}  {str(avail)[:12]:>12}  {ship:>10}  {s['url'][:45]}")
    print(SEP3)

    if not contenders:
        print("\n  ✗ No contenders — pipeline stopped.")
        return

    # ── Phase 3: Gemini scoring ───────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("[PHASE 3] Gemini / Groq Scoring")
    print(SEP2)
    search_desc = (
        f"{cp.get('preference') or ''} {cp.get('category') or ''}"
        + (f" under {budget_max} {budget_currency}" if budget_max else "")
    ).strip()

    t0 = time.perf_counter()
    ranked = gemini_service.score_and_rank_products(
        contenders,
        search_desc,
        budget_max,
        budget_currency,
        city,
        country,
        is_global=search_globally,
    )
    elapsed = time.perf_counter() - t0
    print(f"\n  Scored {len(ranked)} products in {elapsed:.2f}s\n")

    if not ranked:
        print("  ✗ Scorer returned nothing — check Gemini/Groq logs above.")
        return

    for p in ranked:
        s = p.get("scores") or {}
        print(f"  {'─'*88}")
        print(f"  RANK #{p.get('rank')}  value_score = {p.get('value_score', 0):.1f}/100")
        print(f"    Title     : {p.get('title','?')[:85]}")
        print(f"    URL       : {p.get('url','?')[:85]}")
        print(f"    Price     : {p.get('price')} {p.get('currency','')}")
        print(f"    Image     : {p.get('image_url') or '(none)'}")
        print(f"    Scores    :")
        print(f"      cost_efficiency    = {s.get('cost_efficiency'):>6}  ×0.40")
        print(f"      quality_confidence = {s.get('quality_confidence'):>6}  ×0.35")
        print(f"      logistics          = {s.get('logistics'):>6}  ×0.15")
        print(f"      trust              = {s.get('trust'):>6}  ×0.10")
        reasoning = p.get("reasoning", "")
        wrapped = textwrap.wrap(reasoning, width=80)
        for j, line in enumerate(wrapped):
            prefix = "    Reasoning : " if j == 0 else "               "
            print(f"{prefix}{line}")
        print()

    print(f"\n  → FINAL TOP 3:")
    for p in ranked[:3]:
        print(f"    #{p.get('rank')}  {p.get('value_score',0):.1f}pt  {p.get('price')} {p.get('currency','')}  {p.get('url','?')[:70]}")

    return ranked


# ── helpers ───────────────────────────────────────────────────────────────────
def _msg(role, content):
    return {"role": role, "content": content}


def _assistant_summary(ranked):
    if not ranked:
        return "I couldn't find any matching products."
    lines = ["Here are the top options I found:"]
    for p in ranked:
        lines.append(
            f"{p.get('rank')}. {p.get('title','?')} — "
            f"{p.get('price')} {p.get('currency','')} — {p.get('url','?')}"
        )
    return "\n".join(lines)


# ── test suite ────────────────────────────────────────────────────────────────
async def main():
    total_t0 = time.perf_counter()

    await run_pipeline(
        [_msg("user", "I want a mountain bike under 1000 RON")],
        "Mountain bike < 1000 RON (local RO)",
    )

    ranked_watches = await run_pipeline(
        [_msg("user", "I want a high quality watch under 500 RON")],
        "Watch < 500 RON — initial",
    )

    await run_pipeline(
        [
            _msg("user", "I want a high quality watch under 500 RON"),
            _msg("assistant", _assistant_summary(ranked_watches or [])),
            _msg("user", "I'm not satisfied, the watch is for a woman — show me women's watches"),
        ],
        "Watch — refinement to women's",
    )

    await run_pipeline(
        [_msg("user",
              "I'm looking for a gaming laptop with a budget between 2500 and 3000 RON. "
              "Check eMAG and Altex first.")],
        "Gaming laptop 2500–3000 RON (local first)",
    )

    await run_pipeline(
        [_msg("user",
              "I want to buy a wireless gaming headset from Amazon, budget 80 USD")],
        "Wireless headset Amazon 80 USD",
        city="",
        country="",
    )

    print(f"\n{SEP}")
    print(f"  All tests done — total: {time.perf_counter()-total_t0:.0f}s")
    print(SEP)


if __name__ == "__main__":
    asyncio.run(main())
