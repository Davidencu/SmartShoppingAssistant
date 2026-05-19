"""
Deterministic vendor logistics registry for Romanian (and common international) retailers.

Instead of asking Gemini to guess shipping fees and delivery windows from a scraped page
that never shows them, we inject hard-coded rules per domain so the model can score
logistics as a solved arithmetic problem rather than an unknown variable.

Add new vendors by inserting a key matching the domain (without www.).
"""
import re
import unicodedata

# ── Vendor registry ────────────────────────────────────────────────────────────

VENDOR_LOGISTICS_REGISTRY: dict[str, dict] = {
    "emag.ro": {
        "base_shipping_fee_ron": 15,
        "free_shipping_threshold_ron": 1500,
        "easybox_available": True,
        "delivery_days": "1–3",
        "same_day_cities": ["Bucuresti", "Ilfov"],
        "hub_cities": ["Bucuresti", "Ilfov", "Cluj-Napoca", "Timisoara", "Iasi",
                       "Craiova", "Brasov", "Constanta", "Galati", "Ploiesti"],
    },
    "altex.ro": {
        "base_shipping_fee_ron": 20,
        "free_shipping_threshold_ron": 200,
        "easybox_available": False,
        "delivery_days": "2–4",
        "same_day_cities": [],
        "hub_cities": ["Bucuresti", "Cluj-Napoca", "Timisoara", "Iasi", "Brasov",
                       "Constanta", "Craiova"],
    },
    "flanco.ro": {
        "base_shipping_fee_ron": 19,
        "free_shipping_threshold_ron": 299,
        "easybox_available": False,
        "delivery_days": "2–5",
        "same_day_cities": [],
        "hub_cities": ["Bucuresti", "Cluj-Napoca", "Timisoara", "Iasi", "Brasov",
                       "Craiova"],
    },
    "mediagalaxy.ro": {
        "base_shipping_fee_ron": 20,
        "free_shipping_threshold_ron": 200,
        "easybox_available": False,
        "delivery_days": "2–4",
        "same_day_cities": [],
        "hub_cities": ["Bucuresti", "Cluj-Napoca", "Timisoara", "Constanta", "Iasi"],
    },
    "media-galaxy.ro": {
        "base_shipping_fee_ron": 20,
        "free_shipping_threshold_ron": 200,
        "easybox_available": False,
        "delivery_days": "2–4",
        "same_day_cities": [],
        "hub_cities": ["Bucuresti", "Cluj-Napoca", "Timisoara", "Constanta", "Iasi"],
    },
    "pcgarage.ro": {
        "base_shipping_fee_ron": 15,
        "free_shipping_threshold_ron": 300,
        "easybox_available": True,
        "delivery_days": "1–3",
        "same_day_cities": ["Bucuresti"],
        "hub_cities": ["Bucuresti", "Cluj-Napoca", "Timisoara", "Iasi"],
    },
    "cel.ro": {
        "base_shipping_fee_ron": 15,
        "free_shipping_threshold_ron": 500,
        "easybox_available": True,
        "delivery_days": "1–3",
        "same_day_cities": ["Bucuresti"],
        "hub_cities": ["Bucuresti", "Cluj-Napoca", "Timisoara"],
    },
    "dedeman.ro": {
        "base_shipping_fee_ron": 25,
        "free_shipping_threshold_ron": 500,
        "easybox_available": False,
        "delivery_days": "2–5",
        "same_day_cities": [],
        "hub_cities": ["Bucuresti", "Cluj-Napoca", "Timisoara", "Iasi", "Bacau",
                       "Suceava", "Pitesti", "Sibiu", "Craiova"],
    },
    "evomag.ro": {
        "base_shipping_fee_ron": 15,
        "free_shipping_threshold_ron": 250,
        "easybox_available": True,
        "delivery_days": "1–3",
        "same_day_cities": ["Bucuresti"],
        "hub_cities": ["Bucuresti", "Cluj-Napoca", "Timisoara"],
    },
    "amazon.de": {
        "base_shipping_fee_ron": 35,
        "free_shipping_threshold_ron": None,
        "easybox_available": False,
        "delivery_days": "5–10",
        "same_day_cities": [],
        "hub_cities": [],
    },
    "amazon.com": {
        "base_shipping_fee_ron": 60,
        "free_shipping_threshold_ron": None,
        "easybox_available": False,
        "delivery_days": "7–14",
        "same_day_cities": [],
        "hub_cities": [],
    },
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _strip_diacritics(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def _city_match(user_city: str, city_list: list[str]) -> bool:
    """Case- and diacritic-insensitive partial city match."""
    needle = _strip_diacritics(user_city.lower())
    for city in city_list:
        haystack = _strip_diacritics(city.lower())
        if needle in haystack or haystack in needle:
            return True
    return False


def _extract_domain(url: str) -> str:
    m = re.search(r"(?:https?://)?(?:www\.)?([^/]+)", url)
    return m.group(1).lower() if m else ""


# ── Public API ─────────────────────────────────────────────────────────────────

def get_logistics_context(
    url: str,
    city: str,
    price: float | None = None,
    price_currency: str | None = None,
    budget_currency: str | None = None,
) -> str:
    """
    Return a deterministic logistics context block for a single product URL.
    Injected into each product block in the Gemini scoring prompt so the model
    scores logistics with hard facts instead of guessing.

    Returns an empty string for global searches or unknown vendors so the
    existing rubric fallback applies unchanged.
    """
    domain = _extract_domain(url)
    rules = VENDOR_LOGISTICS_REGISTRY.get(domain)
    if not rules:
        return ""

    city_display = city or "Romania"
    is_hub = _city_match(city, rules["hub_cities"]) if city else False
    is_same_day = _city_match(city, rules["same_day_cities"]) if city else False

    # ── Free-shipping eligibility ──────────────────────────────────────────
    threshold = rules["free_shipping_threshold_ron"]
    # Only compare when both price and threshold exist and currencies are RON-compatible
    currency_ok = (price_currency or budget_currency or "RON").upper() == "RON"
    free_shipping: bool | None = None
    shipping_note: str

    if threshold is None:
        shipping_note = f"Flat fee: {rules['base_shipping_fee_ron']} RON (international — no free-shipping tier)"
        free_shipping = False
    elif price is not None and currency_ok:
        free_shipping = price >= threshold
        if free_shipping:
            shipping_note = (
                f"FREE — order total ({price:.0f} RON) ≥ {threshold} RON threshold"
            )
        else:
            gap = threshold - price
            shipping_note = (
                f"{rules['base_shipping_fee_ron']} RON "
                f"(free shipping requires {threshold} RON; {gap:.0f} RON short)"
            )
    else:
        shipping_note = (
            f"Likely free if order ≥ {threshold} RON "
            f"(price unconfirmed — cannot verify eligibility)"
        )

    # ── Hub / delivery window ──────────────────────────────────────────────
    if is_same_day:
        delivery_note = f"Same-day delivery available in {city_display}"
        delivery_days = "same day"
    elif is_hub:
        delivery_note = f"{city_display} is a regional fulfilment hub → faster dispatch"
        delivery_days = rules["delivery_days"]
    else:
        delivery_note = f"Standard courier to {city_display} — no local hub"
        delivery_days = rules["delivery_days"]

    easybox_note = "Available" if rules["easybox_available"] else "Not available"

    # ── Score guidance ─────────────────────────────────────────────────────
    if free_shipping is True and is_same_day:
        score_band = "95–100"
        score_reason = "free shipping + same-day delivery"
    elif free_shipping is True and is_hub:
        score_band = "90–95"
        score_reason = "free shipping + local hub → fast delivery"
    elif free_shipping is True:
        score_band = "80–88"
        score_reason = "free shipping to destination"
    elif free_shipping is False and is_hub:
        score_band = "65–75"
        score_reason = "paid shipping but local hub reduces transit time"
    elif free_shipping is False:
        score_band = "55–65"
        score_reason = "paid shipping, standard transit"
    else:
        # price unknown — soft guidance, not hard
        score_band = "70–85" if is_hub else "55–70"
        score_reason = "estimated from hub proximity (price not confirmed)"

    return (
        f"### VENDOR LOGISTICS CONTEXT ({domain} → {city_display})\n"
        f"• Shipping cost: {shipping_note}\n"
        f"• Delivery window: {delivery_days} business days — {delivery_note}\n"
        f"• Locker / Easybox: {easybox_note}\n"
        f"→ LOGISTICS SCORE GUIDANCE: {score_band} ({score_reason})\n"
        f"   Use this guidance as your primary logistics score source.\n\n"
    )
