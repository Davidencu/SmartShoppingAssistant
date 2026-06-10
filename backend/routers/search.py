import asyncio
import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from models.search import ChatRequest, ChatResponse, IntentParams, Product, ProductScores
from routers.auth import get_current_user
from services import cache_service, gemini_service, openai_router, retailers_service, scraper_service, tavily_service
from services.supabase_service import get_supabase_admin

router = APIRouter(prefix="/search", tags=["search"])
logger = logging.getLogger(__name__)


# ── Store display names ───────────────────────────────────────────────────────
# Maps bare domain → human-readable store name shown in the UI status messages.
# Domains not listed here fall back to the raw domain string, so the app works
# for any retailer on Earth without needing to register it here first.
# Add entries freely — the only effect is on the status message text.
_STORE_NAMES: dict[str, str] = {
    # ── Romania ──────────────────────────────────────────────────────────────
    "emag.ro":              "eMAG",
    "altex.ro":             "Altex",
    "pcgarage.ro":          "PC Garage",
    "flanco.ro":            "Flanco",
    "cel.ro":               "CEL",
    "elefant.ro":           "Elefant",
    "dedeman.ro":           "Dedeman",
    "carrefour.ro":         "Carrefour",
    "mediagalaxy.ro":       "Media Galaxy",
    "auchan.ro":            "Auchan",
    "decathlon.ro":         "Decathlon",
    "sportguru.ro":         "Sport Guru",
    "hervis.ro":            "Hervis",
    "watchshop.ro":         "Watch Shop",
    "bb-shop.ro":           "B&B Shop",
    "zara.com":             "Zara",
    # ── Amazon (all regions) ─────────────────────────────────────────────────
    "amazon.com":           "Amazon",
    "amazon.de":            "Amazon DE",
    "amazon.co.uk":         "Amazon UK",
    "amazon.fr":            "Amazon FR",
    "amazon.it":            "Amazon IT",
    "amazon.es":            "Amazon ES",
    "amazon.pl":            "Amazon PL",
    "amazon.nl":            "Amazon NL",
    "amazon.ca":            "Amazon CA",
    "amazon.com.au":        "Amazon AU",
    "amazon.in":            "Amazon IN",
    "amazon.co.jp":         "Amazon JP",
    # ── eBay ─────────────────────────────────────────────────────────────────
    "ebay.com":             "eBay",
    "ebay.co.uk":           "eBay UK",
    "ebay.de":              "eBay DE",
    "ebay.fr":              "eBay FR",
    "ebay.it":              "eBay IT",
    "ebay.es":              "eBay ES",
    # ── North America ────────────────────────────────────────────────────────
    "walmart.com":          "Walmart",
    "target.com":           "Target",
    "bestbuy.com":          "Best Buy",
    "newegg.com":           "Newegg",
    "bhphotovideo.com":     "B&H Photo",
    "adorama.com":          "Adorama",
    "costco.com":           "Costco",
    "macys.com":            "Macy's",
    "nordstrom.com":        "Nordstrom",
    "apple.com":            "Apple",
    "nike.com":             "Nike",
    "adidas.com":           "Adidas",
    # ── Germany ──────────────────────────────────────────────────────────────
    "mediamarkt.de":        "MediaMarkt",
    "saturn.de":            "Saturn",
    "otto.de":              "Otto",
    "zalando.de":           "Zalando",
    "alternate.de":         "Alternate",
    "notebooksbilliger.de": "Notebooksbilliger",
    # ── France ───────────────────────────────────────────────────────────────
    "fnac.fr":              "Fnac",
    "cdiscount.com":        "Cdiscount",
    "darty.com":            "Darty",
    "boulanger.com":        "Boulanger",
    # ── Spain ────────────────────────────────────────────────────────────────
    "pccomponentes.com":    "PC Componentes",
    "mediamarkt.es":        "MediaMarkt ES",
    # ── Italy ────────────────────────────────────────────────────────────────
    "mediaworld.it":        "MediaWorld",
    "unieuro.it":           "Unieuro",
    # ── Poland ───────────────────────────────────────────────────────────────
    "allegro.pl":           "Allegro",
    "morele.net":           "Morele",
    "x-kom.pl":             "x-kom",
    # ── Czech / Slovakia ─────────────────────────────────────────────────────
    "alza.cz":              "Alza",
    "alza.sk":              "Alza SK",
    # ── Netherlands / Belgium ────────────────────────────────────────────────
    "coolblue.nl":          "Coolblue",
    "bol.com":              "bol.com",
    "mediamarkt.nl":        "MediaMarkt NL",
    # ── UK ───────────────────────────────────────────────────────────────────
    "currys.co.uk":         "Currys",
    "argos.co.uk":          "Argos",
    "johnlewis.com":        "John Lewis",
    "asos.com":             "ASOS",
    # ── Global fashion / sport ───────────────────────────────────────────────
    "zalando.com":          "Zalando",
    "hm.com":               "H&M",
    "uniqlo.com":           "Uniqlo",
    "decathlon.com":        "Decathlon",
}


def _store_name(domain: str) -> str:
    """Pretty display name for a domain, falling back to the domain itself."""
    return _STORE_NAMES.get(domain, domain)


# ── Country → language (for initial status message before Gemini replies) ─────
_COUNTRY_LANGUAGE: dict[str, str] = {
    "romania": "Romanian", "ro": "Romanian",
    "germany": "German", "deutschland": "German", "de": "German",
    "france": "French", "fr": "French",
    "italy": "Italian", "italia": "Italian", "it": "Italian",
    "spain": "Spanish", "españa": "Spanish", "es": "Spanish",
    "poland": "Polish", "polska": "Polish", "pl": "Polish",
    "netherlands": "Dutch", "holland": "Dutch", "nederland": "Dutch", "nl": "Dutch",
    "belgium": "Dutch", "be": "Dutch",
    "portugal": "Portuguese", "pt": "Portuguese",
    "brazil": "Portuguese", "brasil": "Portuguese", "br": "Portuguese",
    "czech republic": "Czech", "czechia": "Czech", "cz": "Czech",
    "slovakia": "Slovak", "sk": "Slovak",
    "hungary": "Hungarian", "hu": "Hungarian",
    "sweden": "Swedish", "sverige": "Swedish", "se": "Swedish",
    "norway": "Norwegian", "norge": "Norwegian", "no": "Norwegian",
    "denmark": "Danish", "danmark": "Danish", "dk": "Danish",
    "finland": "Finnish", "suomi": "Finnish", "fi": "Finnish",
    "greece": "Greek", "gr": "Greek",
    "turkey": "Turkish", "tr": "Turkish",
    "russia": "Russian", "ru": "Russian",
    "japan": "Japanese", "jp": "Japanese",
    "china": "Chinese", "cn": "Chinese",
    "south korea": "Korean", "kr": "Korean",
    "united states": "English", "us": "English",
    "united kingdom": "English", "uk": "English", "gb": "English",
    "australia": "English", "au": "English",
    "canada": "English", "ca": "English",
    "new zealand": "English", "nz": "English",
    "ireland": "English", "ie": "English",
    "india": "English", "in": "English",
    "south africa": "English", "za": "English",
}

# ISO 639-1 code → language name (returned by Gemini classify_intent)
_ISO_TO_LANGUAGE: dict[str, str] = {
    "en": "English", "ro": "Romanian", "de": "German", "fr": "French",
    "it": "Italian", "es": "Spanish", "pl": "Polish", "nl": "Dutch",
    "pt": "Portuguese", "cs": "Czech", "sk": "Slovak", "hu": "Hungarian",
    "sv": "Swedish", "no": "Norwegian", "da": "Danish", "fi": "Finnish",
    "el": "Greek", "tr": "Turkish", "ru": "Russian", "ja": "Japanese",
    "zh": "Chinese", "ko": "Korean", "ar": "Arabic", "hi": "Hindi",
}

# Translated status messages keyed by ISO 639-1 code then message key
_STATUS_I18N: dict[str, dict[str, str]] = {
    "en": {
        "intent":               "Classifying intent...",
        "researching":          "Researching community recommendations...",
        "cache":                "Checking cache...",
        "search":               "Searching for products...",
        "found_pages":          "Found {n} page{s} — opening {stores}...",
        "browsed":              "Browsed {store} ({done}/{total})",
        "found_prods":          "Found {n} product{s} within budget — calculating scores...",
        "scoring":              "Scoring with AI...",
        "mainstream_try":       "Nothing in specialty stores — trying mainstream retailers...",
        "global":               "Trying global search...",
        "suggestions":          "Generating suggestions...",
        "results_header":       "Here are the top products ranked by value score:",
        "fallback": (
            "I couldn't find this product on local retailers — all results were "
            "out of stock or didn't meet your criteria. "
            "Here are the best options I found from global shops:"
        ),
    },
    "ro": {
        "intent":           "Clasificăm intenția...",
        "researching":      "Cercetăm recomandările comunității...",
        "cache":            "Verificăm cache-ul...",
        "search":           "Căutăm produse...",
        "found_pages":      "Am găsit {n} pagini — deschidem {stores}...",
        "browsed":          "Am navigat pe {store} ({done}/{total})",
        "found_prods":      "Am găsit {n} produse în buget — calculăm scorurile...",
        "scoring":          "Scorăm cu AI...",
        "mainstream_try":   "Nimic în magazine specializate — încercăm magazinele mari...",
        "global":           "Încercăm căutarea globală...",
        "suggestions":      "Generăm sugestii...",
        "results_header":   "Iată cele mai bune produse clasate după scorul de valoare:",
        "fallback": (
            "Nu am găsit acest produs la magazinele locale — toate rezultatele "
            "erau epuizate sau nu corespundeau criteriilor tale. "
            "Iată cele mai bune opțiuni găsite în magazinele internaționale:"
        ),
    },
    "de": {
        "intent":           "Intent wird klassifiziert...",
        "researching":      "Community-Empfehlungen werden recherchiert...",
        "cache":            "Cache wird geprüft...",
        "search":           "Produkte werden gesucht...",
        "found_pages":      "{n} Seiten gefunden — {stores} wird geöffnet...",
        "browsed":          "{store} durchsucht ({done}/{total})",
        "found_prods":      "{n} Produkte im Budget — Bewertungen werden berechnet...",
        "scoring":          "KI-Bewertung läuft...",
        "mainstream_try":   "Nichts bei Fachhändlern — große Händler werden versucht...",
        "global":           "Globale Suche wird versucht...",
        "suggestions":      "Vorschläge werden generiert...",
        "results_header":   "Hier sind die besten Produkte nach Wert-Score:",
        "fallback": (
            "Ich konnte dieses Produkt bei lokalen Händlern nicht finden — "
            "alle Ergebnisse waren ausverkauft oder entsprachen nicht deinen Kriterien. "
            "Hier sind die besten Optionen aus internationalen Shops:"
        ),
    },
    "fr": {
        "intent":           "Classification de l'intention...",
        "researching":      "Recherche de recommandations de la communauté...",
        "cache":            "Vérification du cache...",
        "search":           "Recherche de produits...",
        "found_pages":      "{n} pages trouvées — ouverture de {stores}...",
        "browsed":          "{store} parcouru ({done}/{total})",
        "found_prods":      "{n} produits dans le budget — calcul des scores...",
        "scoring":          "Notation par IA...",
        "mainstream_try":   "Rien chez les spécialistes — essai des grands distributeurs...",
        "global":           "Tentative de recherche mondiale...",
        "suggestions":      "Génération de suggestions...",
        "results_header":   "Voici les meilleurs produits classés par score de valeur :",
        "fallback": (
            "Je n'ai pas trouvé ce produit chez les revendeurs locaux — tous les résultats "
            "étaient épuisés ou ne correspondaient pas à vos critères. "
            "Voici les meilleures options trouvées dans les boutiques mondiales :"
        ),
    },
    "it": {
        "intent":           "Classificazione dell'intenzione...",
        "researching":      "Ricerca delle raccomandazioni della community...",
        "cache":            "Controllo della cache...",
        "search":           "Ricerca prodotti...",
        "found_pages":      "{n} pagine trovate — apertura di {stores}...",
        "browsed":          "{store} navigato ({done}/{total})",
        "found_prods":      "{n} prodotti nel budget — calcolo punteggi...",
        "scoring":          "Valutazione con AI...",
        "mainstream_try":   "Nessun risultato negli store specializzati — provo i grandi rivenditori...",
        "global":           "Tentativo di ricerca globale...",
        "suggestions":      "Generazione di suggerimenti...",
        "results_header":   "Ecco i migliori prodotti classificati per punteggio di valore:",
        "fallback": (
            "Non ho trovato questo prodotto nei negozi locali — tutti i risultati erano "
            "esauriti o non soddisfacevano i tuoi criteri. "
            "Ecco le migliori opzioni trovate nei negozi globali:"
        ),
    },
    "es": {
        "intent":           "Clasificando la intención...",
        "researching":      "Investigando recomendaciones de la comunidad...",
        "cache":            "Comprobando la caché...",
        "search":           "Buscando productos...",
        "found_pages":      "{n} páginas encontradas — abriendo {stores}...",
        "browsed":          "{store} navegado ({done}/{total})",
        "found_prods":      "{n} productos dentro del presupuesto — calculando puntuaciones...",
        "scoring":          "Puntuación con IA...",
        "mainstream_try":   "Sin resultados en tiendas especializadas — probando grandes tiendas...",
        "global":           "Intentando búsqueda global...",
        "suggestions":      "Generando sugerencias...",
        "results_header":   "Aquí están los mejores productos clasificados por puntuación de valor:",
        "fallback": (
            "No encontré este producto en tiendas locales — todos los resultados estaban "
            "agotados o no cumplían tus criterios. "
            "Aquí están las mejores opciones de tiendas globales:"
        ),
    },
    "pl": {
        "intent":           "Klasyfikacja intencji...",
        "researching":      "Wyszukiwanie rekomendacji społeczności...",
        "cache":            "Sprawdzanie pamięci podręcznej...",
        "search":           "Szukam produktów...",
        "found_pages":      "Znaleziono {n} stron — otwieranie {stores}...",
        "browsed":          "Przeglądnięto {store} ({done}/{total})",
        "found_prods":      "Znaleziono {n} produktów w budżecie — obliczanie wyników...",
        "scoring":          "Ocenianie przez AI...",
        "mainstream_try":   "Nic w sklepach specjalistycznych — próba dużych sklepów...",
        "global":           "Próba globalnego wyszukiwania...",
        "suggestions":      "Generowanie sugestii...",
        "results_header":   "Oto najlepsze produkty według wyniku wartości:",
        "fallback": (
            "Nie znalazłem tego produktu w lokalnych sklepach — wszystkie wyniki były "
            "niedostępne lub nie spełniały Twoich kryteriów. "
            "Oto najlepsze opcje znalezione w sklepach globalnych:"
        ),
    },
    "nl": {
        "intent":           "Intentie wordt geclassificeerd...",
        "researching":      "Community-aanbevelingen worden onderzocht...",
        "cache":            "Cache wordt gecontroleerd...",
        "search":           "Producten worden gezocht...",
        "found_pages":      "{n} pagina's gevonden — {stores} wordt geopend...",
        "browsed":          "{store} doorzocht ({done}/{total})",
        "found_prods":      "{n} producten binnen budget — scores worden berekend...",
        "scoring":          "AI-scoring...",
        "mainstream_try":   "Niets bij gespecialiseerde winkels — grote retailers worden geprobeerd...",
        "global":           "Wereldwijde zoekopdracht proberen...",
        "suggestions":      "Suggesties worden gegenereerd...",
        "results_header":   "Hier zijn de beste producten gerangschikt op waardepunt:",
        "fallback": (
            "Ik kon dit product niet vinden bij lokale retailers — alle resultaten waren "
            "uitverkocht of voldeden niet aan uw criteria. "
            "Hier zijn de beste opties uit wereldwijde winkels:"
        ),
    },
    "pt": {
        "intent":           "Classificando a intenção...",
        "researching":      "Pesquisando recomendações da comunidade...",
        "cache":            "Verificando o cache...",
        "search":           "Pesquisando produtos...",
        "found_pages":      "{n} páginas encontradas — abrindo {stores}...",
        "browsed":          "{store} navegado ({done}/{total})",
        "found_prods":      "{n} produtos dentro do orçamento — calculando pontuações...",
        "scoring":          "Pontuação com IA...",
        "mainstream_try":   "Nada em lojas especializadas — tentando grandes varejistas...",
        "global":           "Tentando pesquisa global...",
        "suggestions":      "Gerando sugestões...",
        "results_header":   "Aqui estão os melhores produtos classificados por pontuação de valor:",
        "fallback": (
            "Não encontrei este produto em lojas locais — todos os resultados estavam "
            "esgotados ou não atendiam aos seus critérios. "
            "Aqui estão as melhores opções encontradas em lojas globais:"
        ),
    },
}


def _country_to_language(country: str) -> str:
    """Map a Supabase country field (name or ISO code) → language name."""
    return _COUNTRY_LANGUAGE.get(country.strip().lower(), "English")


def _t(lang: str, key: str, **kwargs) -> str:
    """Translate a status message key, falling back to English."""
    bucket = _STATUS_I18N.get(lang) or _STATUS_I18N["en"]
    template = bucket.get(key) or _STATUS_I18N["en"].get(key, key)
    return template.format(**kwargs) if kwargs else template


_OUT_OF_STOCK_SIGNALS = frozenset({
    # English
    "outofstock", "out of stock", "out-of-stock",
    "sold out", "currently unavailable", "no longer available",
    "temporarily out of stock", "no featured offers available",
    # Romanian
    "indisponibil", "stoc epuizat", "stoc 0",
    # French
    "rupture de stock", "indisponible", "en rupture",
    # German
    "nicht verfügbar", "nicht vorrätig", "ausverkauft", "vergriffen",
    # Spanish
    "agotado", "no disponible", "sin stock",
    # Italian
    "esaurito", "non disponibile", "non disponible",
    # Polish
    "niedostępny", "brak w magazynie", "brak towaru", "wyprzedany",
    # Dutch (NL/BE)
    "niet op voorraad", "uitverkocht", "niet beschikbaar",
    # Portuguese (PT/BR)
    "esgotado", "indisponível", "sem stock", "fora de estoque",
    # Swedish
    "slut i lager", "tillfälligt slut", "ej i lager",
    # Norwegian
    "ikke på lager", "utsolgt",
    # Danish
    "udsolgt",
    # Finnish
    "ei varastossa", "loppunut",
    # Czech / Slovak
    "není skladem", "nedostupné", "vyprodáno", "nie je na sklade",
    # Hungarian
    "elfogyott", "nem elérhető", "nincs készleten",
    # Greek
    "μη διαθέσιμο", "εξαντλήθηκε",
    # Turkish
    "stokta yok", "tükendi",
    # Russian
    "нет в наличии", "нет на складе",
    # Japanese
    "在庫切れ", "品切れ",
    # Korean
    "품절",
    # Chinese (simplified)
    "缺货", "无货",
})


def _pick_contenders(
    scraped: list[dict],
    budget_max: float | None,
    n: int = 10,
    excluded_keywords: list[str] | None = None,
    price_floor: float | None = None,
) -> list[dict]:
    """
    Drop out-of-stock, over-budget, wrong-category, and below-floor-price pages,
    then return the top `n` ranked by data richness before the Gemini scoring call.

    excluded_keywords — lowercase terms that must not appear in title, category, or
    breadcrumb; populated by Gemini when the user complains of wrong-category results.
    price_floor — minimum plausible price for the real product; eliminates accessories
    and toys that slip through under the category keyword.
    """
    kw_lower = [k.lower() for k in (excluded_keywords or [])]

    def _available(s: dict) -> bool:
        avail = ((s.get("jsonld") or {}).get("availability") or "").lower()
        if avail and any(sig in avail for sig in _OUT_OF_STOCK_SIGNALS):
            return False
        # Scan more of the markdown — OOS banners often appear mid-page on niche sites.
        md_head = (s.get("markdown") or "")[:2500].lower()
        return not any(sig in md_head for sig in _OUT_OF_STOCK_SIGNALS)

    def _in_budget(s: dict) -> bool:
        if not budget_max:
            return True
        price = (s.get("jsonld") or {}).get("price")
        if price is None:
            return True  # unknown price — keep, Gemini will judge
        try:
            return float(str(price).replace(",", ".")) <= budget_max * 1.10
        except (TypeError, ValueError):
            return True

    def _above_floor(s: dict) -> bool:
        """Drop products priced below the minimum realistic floor (accessories / toys)."""
        if not price_floor:
            return True
        price = (s.get("jsonld") or {}).get("price")
        if price is None:
            return True  # price unknown — keep; Gemini will score appropriately
        try:
            return float(str(price).replace(",", ".")) >= price_floor
        except (TypeError, ValueError):
            return True

    def _right_category(s: dict) -> bool:
        """
        Reject pages whose title, JSON-LD category, or breadcrumb contain any of the
        excluded keywords. Cosine similarity is blind to 'NOT' — this is the hard filter
        that stops accessories from polluting a real-product search.
        """
        if not kw_lower:
            return True
        jld = s.get("jsonld") or {}
        # Aggregate all category-related text from JSON-LD + title
        haystack = " ".join(filter(None, [
            (jld.get("category") or ""),
            (jld.get("breadcrumb") or ""),
            (s.get("title") or ""),
            # first 200 chars of markdown often contains the category path
            (s.get("markdown") or "")[:200],
        ])).lower()
        return not any(kw in haystack for kw in kw_lower)

    def _richness(s: dict) -> int:
        score = len(s.get("markdown") or "")
        jld = s.get("jsonld") or {}
        if jld.get("price"):        score += 5_000
        if jld.get("rating"):       score += 2_000
        if jld.get("name"):         score += 1_000
        if s.get("has_buy_button"): score += 8_000  # active buy button = highest signal
        return score

    from services.scraper_service import is_likely_product_url
    candidates = [
        s for s in scraped
        if (
            is_likely_product_url(s.get("url", ""))
            # Lane B results are pre-validated by Gemini; skip markdown length check
            and (s.get("_lane") == "B" or len(s.get("markdown") or "") > 400)
            and _available(s)
            and _in_budget(s)
            and _above_floor(s)
            and _right_category(s)
        )
    ]
    dropped = len(scraped) - len(candidates)
    if dropped:
        logger.info(
            "[CONTENDER] dropped %d/%d pages (category URL, wrong category, or below price floor)",
            dropped, len(scraped),
        )
    candidates.sort(key=_richness, reverse=True)
    return candidates[:n]


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


# Heuristic fallback ranking

def _heuristic_rank(contenders: list[dict], budget_max: float | None) -> list[dict]:
    """
    Price-sort fallback for when all LLM scorers are unavailable.
    Sorts by: in-budget first → lowest price → richest structured data.
    Returns top 3 with zero scores and a note in reasoning.
    """
    def _price(c: dict) -> float | None:
        try:
            raw = (c.get("jsonld") or {}).get("price")
            return float(str(raw).replace(",", ".")) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def _sort_key(c: dict) -> tuple:
        p = _price(c)
        in_budget = budget_max is None or p is None or p <= budget_max
        richness = len(c.get("markdown") or "")
        jld = c.get("jsonld") or {}
        if jld.get("name"):   richness += 1_000
        if jld.get("rating"): richness += 500
        return (0 if in_budget else 1, p if p is not None else 1e9, -richness)

    top3 = sorted(contenders, key=_sort_key)[:3]
    results = []
    for i, c in enumerate(top3, 1):
        jld = c.get("jsonld") or {}
        p = _price(c)
        results.append({
            "rank": i,
            "title": jld.get("name") or c.get("title") or "",
            "url": c["url"],
            "price": p,
            "currency": jld.get("currency"),
            "image_url": jld.get("image"),
            "scores": {"cost_efficiency": 0, "quality_confidence": 0, "logistics": 0, "trust": 0},
            "value_score": 0.0,
            "reasoning": "AI scorer temporarily unavailable — ranked by price within budget.",
        })
    return results


# Pipeline Helper

async def _run_product_pipeline(
    query: str,
    params: IntentParams,
    city: str,
    country: str,
    local_domains: list[str] | None,
    excluded_urls: set[str] | None = None,
    is_global: bool = False,
    on_event=None,
    user_language: str = "English",
    excluded_keywords: list[str] | None = None,
    price_floor: float | None = None,
    community_picks: list[str] | None = None,
    specific_models: list[str] | None = None,
) -> list[dict]:
    """
    5-phase pipeline:

    Phase 1 — Tavily radar: cast a wide net using specific model names or query.
    Phase 3 — Traffic Cop: split URLs into Lane A (niche) and Lane B (heavy).
    Phase 4A — Lane A: curl_cffi + JSON-LD scraper for niche product pages.
    Phase 4B — Lane B: Gemini Search Grounding for enterprise/category pages.
    Phase 5 — Gemini judge: 40-point scoring matrix → top 3 ranked products.

    Returns [] on any soft or hard failure — callers handle the empty case.
    on_event: optional async callable(dict) — receives status events during each phase.
    """
    # ── Phase 1: Tavily radar ──────────────────────────────────────────────
    if on_event:
        await on_event({"type": "status", "message": _t(user_language, "search")})

    tavily_results: list[dict] = []

    if specific_models:
        # Per-model queries yield PDPs directly; broad category queries return listing/search pages.
        # Each model search targets the local domains (or global when local_domains is None).
        seen_pdp: set[str] = set()
        for model in specific_models[:3]:
            model_hits = await run_in_threadpool(
                tavily_service.search_products, f"{model} buy", 8, local_domains
            )
            for r in model_hits:
                if r["url"] not in seen_pdp:
                    tavily_results.append(r)
                    seen_pdp.add(r["url"])
        logger.info("[P1/TAVILY] specific_models (%d): %d results", len(specific_models), len(tavily_results))
    elif local_domains:
        tavily_results = await run_in_threadpool(
            tavily_service.search_products, query, 20, local_domains
        )
        logger.info("[P1/TAVILY] local (%s): %d results", ", ".join(local_domains), len(tavily_results))

    n_initial = len(tavily_results)
    if excluded_urls:
        before_excl = len(tavily_results)
        tavily_results = [r for r in tavily_results if r["url"] not in excluded_urls]
        dropped = before_excl - len(tavily_results)
        if dropped:
            logger.info("[P1/TAVILY] dropped %d excluded URL(s)", dropped)

    # ── Strict Domain Enforcement (The Bouncer) ───────────────────────────────
    # Tavily's include_domains is a soft hint; hard-filter to requested domains only.
    if local_domains:
        before_strict = len(tavily_results)
        strict_results = []
        for r in tavily_results:
            domain = urlparse(r["url"]).netloc.replace("www.", "")
            if any(req_domain in domain for req_domain in local_domains):
                strict_results.append(r)
            else:
                logger.warning("[P1/TAVILY] Bouncer dropped leaked domain: %s", domain)
        tavily_results = strict_results
        dropped_strict = before_strict - len(tavily_results)
        if dropped_strict:
            logger.info("[P1/TAVILY] Strict domain lock: dropped %d leaked URLs.", dropped_strict)

    logger.info("[P1/TAVILY] %d URLs after filters → Traffic Cop", len(tavily_results))
    if not tavily_results:
        logger.warning("[P1/TAVILY] no URLs after filters — returning empty")
        return []

    url_to_title = {r["url"]: r.get("title", "") for r in tavily_results}
    url_to_content = {r["url"]: r.get("content", "") for r in tavily_results}
    all_urls = [r["url"] for r in tavily_results]

    # ── Phase 3: Traffic Cop — split into Lane A (niche) and Lane B (heavy) ──
    from services.scraper_service import sort_urls_for_lanes
    niche_urls, heavy_urls = sort_urls_for_lanes(all_urls)
    logger.info(
        "[TRAFFIC-COP] %d niche (Lane A scraper), %d heavy (Lane B grounding)",
        len(niche_urls), len(heavy_urls),
    )

    if on_event:
        unique_domains = list(dict.fromkeys(
            urlparse(u).netloc.removeprefix("www.") for u in all_urls
        ))
        stores_str = ", ".join(_store_name(d) for d in unique_domains)
        await on_event({
            "type": "status",
            "message": _t(user_language, "found_pages", n=len(all_urls), s="s" if len(all_urls) != 1 else "", stores=stores_str),
        })

    # ── Phase 4A: Lane A — curl_cffi + JSON-LD scraper (niche product pages) ─
    async def _on_url_done(url: str, done: int, total: int) -> None:
        if on_event:
            domain = urlparse(url).netloc.removeprefix("www.") or url
            await on_event({
                "type": "status",
                "message": _t(user_language, "browsed",
                              store=_store_name(domain), done=done, total=total),
            })

    async def _run_lane_a() -> list[dict]:
        if not niche_urls:
            return []
        results = await scraper_service.scrape_urls(
            niche_urls, on_done=_on_url_done if on_event else None
        )
        for s in results:
            s["title"] = url_to_title.get(s["url"], "")
        return results

    # ── Phase 4B: Lane B — Gemini Search Grounding + Tavily snippets ─────────
    async def _run_lane_b() -> list[dict]:
        if not heavy_urls:
            return []
        lane_b_records: list[dict] = []
        seen_urls: set[str] = set()

        for url in heavy_urls[:6]:  # cap at 6 grounding calls per pipeline run
            # ── Grounding: find specific in-stock products on this URL ──────
            products = await run_in_threadpool(
                gemini_service.read_heavy_url_with_grounding,
                url,
                params.budget_max,
                params.budget_currency,
                params.category or "",
                user_language,
            )
            grounding_added = 0
            for p in products:
                if not p.get("in_stock", True):
                    continue
                if excluded_urls and p["url"] in excluded_urls:
                    continue
                if p["url"] in seen_urls:
                    continue
                seen_urls.add(p["url"])
                name = p.get("name", "Unknown")
                price = p.get("price", 0)
                currency = p.get("currency") or params.budget_currency or "RON"
                md = (
                    f"{name}\n"
                    f"Price: {price} {currency}\n"
                    f"Availability: In Stock\n"
                    f"Category: {params.category or ''}\n"
                    f"Source URL: {url}\n"
                    f"Product URL: {p['url']}\n"
                    f"This product was found via Google Search Grounding on a category "
                    f"page or major retailer. It is confirmed in stock and within budget "
                    f"({params.budget_max} {params.budget_currency}).\n"
                )
                lane_b_records.append({
                    "url": p["url"],
                    "title": name,
                    "markdown": md,
                    "jsonld": {
                        "name": name,
                        "price": price,
                        "currency": currency,
                        "availability": "In Stock",
                        "image": p.get("image_url"),
                    },
                    "has_buy_button": True,
                    "shipping_policy_url": None,
                    "return_policy_text": None,
                    "_lane": "B",
                })
                grounding_added += 1

            # ── Tavily baseline: use the snippet Tavily already returned ────
            # Only add the original URL if it is a product-detail page.
            # Category/search/listing URLs must not appear as final results —
            # if grounding found nothing from them, we simply skip.
            # Skip entirely for mainstream domains: Tavily can index a wrong URL with
            # a mismatched product title (e.g. Lian Li case URL + Razer headset title),
            # so for these sites we trust only what Gemini grounding explicitly returned.
            from services.scraper_service import is_likely_product_url, is_mainstream_domain
            url_domain = urlparse(url).netloc.removeprefix("www.")
            tavily_snippet = url_to_content.get(url, "").strip()
            if (
                tavily_snippet
                and url not in seen_urls
                and is_likely_product_url(url)
                and not is_mainstream_domain(url_domain)
            ):
                seen_urls.add(url)
                lane_b_records.append({
                    "url": url,
                    "title": url_to_title.get(url, ""),
                    "markdown": tavily_snippet,
                    "jsonld": {},
                    "has_buy_button": False,
                    "shipping_policy_url": None,
                    "return_policy_text": None,
                    "_lane": "B",
                })
        logger.info("[LANE-B] produced %d product records", len(lane_b_records))
        return lane_b_records

    # Run both lanes in parallel
    lane_a_results, lane_b_results = await asyncio.gather(_run_lane_a(), _run_lane_b())
    scraped: list[dict] = lane_a_results + lane_b_results

    contenders = _pick_contenders(
        scraped, params.budget_max,
        excluded_keywords=excluded_keywords,
        price_floor=price_floor,
    )

    # ── Diagnostic counts ─────────────────────────────────────────────────────
    _n_lane_a       = len(lane_a_results)
    _n_lane_b       = len(lane_b_results)
    _n_with_content = sum(1 for s in lane_a_results if len(s.get("markdown") or "") > 400)
    _n_fetch_fail   = _n_lane_a - _n_with_content
    _n_filter_fail  = (len(scraped) - len(contenders))

    logger.info(
        "[P4/LANES] Lane A: %d scraped, Lane B: %d products → %d contenders",
        _n_lane_a, _n_lane_b, len(contenders),
    )
    for c in contenders:
        logger.info("  ↳ [%s] %s  (%d chars, price=%s)",
                    c.get("_lane", "A"), c["url"], len(c.get("markdown", "")),
                    (c.get("jsonld") or {}).get("price", "?"))

    if not contenders:
        logger.warning(
            "[P4/LANES] no contenders after filter — returning empty\n"
            "  [DIAG] tavily=%d  lane_a=%d  lane_b=%d  fetch_fail=%d  "
            "filter_fail=%d  contenders=0  final=0",
            n_initial, _n_lane_a, _n_lane_b, _n_fetch_fail, _n_filter_fail,
        )
        return []

    if on_event:
        n = len(contenders)
        await on_event({
            "type": "status",
            "message": _t(user_language, "found_prods", n=n, s="s" if n != 1 else ""),
        })

    # ── Phase 5: Gemini judge ─────────────────────────────────────────────────
    if on_event:
        await on_event({"type": "status", "message": _t(user_language, "scoring")})

    search_description = (
        f"{params.preference} {params.category}"
        + (f" under {params.budget}" if params.budget else "")
    )
    ranked = await run_in_threadpool(
        gemini_service.score_and_rank_products,
        contenders,
        search_description,
        params.budget_max,
        params.budget_currency,
        city,
        country,
        is_global,
        user_language,
        community_picks or [],
    )
    logger.info("[P5/GEMINI] returned %d ranked products", len(ranked))

    valid_urls = {r["url"] for r in contenders}

    # Build URL → ground-truth title from actual scraped data (JSON-LD name wins).
    # Overrides Gemini-hallucinated titles so the sanity check sees the real product name.
    _contender_title: dict[str, str] = {}
    for c in contenders:
        t = (c.get("jsonld") or {}).get("name") or ""
        if t:
            _contender_title[c["url"]] = t

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
            "[P5/GEMINI] dropped %d hallucinated URL(s), %d remain",
            before - len(ranked), len(ranked),
        )

    # Replace Gemini's title with the scraped JSON-LD name when available.
    for p in ranked:
        scraped_title = _contender_title.get(p.get("url", ""))
        if scraped_title:
            p["title"] = scraped_title

    # ── OpenAI sanity check: verify ranked products match the requested category ──
    # Guards against Gemini hallucinating the wrong product type (e.g. user asked
    # for bikes but results are cars) or returning category-page titles as products.
    # Only approved products survive; all-denied triggers the no-results path below.
    # Pass only the category (not the full preference with spec requirements) so
    # gpt-4o-mini checks product TYPE only — not specs like CPU model or RAM size.
    _sanity_denied_all = False
    if ranked:
        ranked = await run_in_threadpool(
            openai_router.sanity_check_products,
            ranked,
            params.category or "",
            None,
        )
        if not ranked:
            logger.warning("[SANITY] all products denied — treating as no results")
            _sanity_denied_all = True

    # Skip heuristic fallback when the sanity check is what cleared the list —
    # price-sorting the same wrong products would just re-surface them.
    if not ranked and contenders and not _sanity_denied_all:
        logger.warning(
            "[P5/HEURISTIC] AI scorer returned nothing — price-sort fallback on %d contenders",
            len(contenders),
        )
        ranked = _heuristic_rank(contenders, params.budget_max)

    logger.info(
        "[DIAG]\n"
        "  Candidates found (Tavily): %d\n"
        "  Lane A (niche scraper):   %d\n"
        "  Lane B (grounding):       %d\n"
        "  Lane A fetch failures:    %d\n"
        "  Failed filters:           %d\n"
        "  Contenders → Gemini:      %d\n"
        "  Final recommendations:    %d",
        n_initial,
        _n_lane_a,
        _n_lane_b,
        _n_fetch_fail,
        _n_filter_fail,
        len(contenders),
        len(ranked),
    )
    return ranked


# Sync helpers (called via run_in_threadpool or asyncio.create_task)

def _save_chat_history(
    user_id: str,
    prompt: str,
    image_included: bool,
    intent: str,
    response_data: dict,
) -> None:
    """Persist chat turn to Supabase — runs in a thread pool, fire-and-forget."""
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


# Endpoints

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


@router.post("/chat")
async def chat(
    req: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Streaming SSE endpoint — emits newline-delimited JSON events:

      data: {"type": "status", "message": "Searching for products..."}\n\n
      data: {"type": "status", "message": "Reading 8 product pages..."}\n\n
      data: {"type": "result", "data": { ...ChatResponse... }}\n\n

    Or on error:
      data: {"type": "error", "message": "..."}\n\n

    The frontend reads the stream with fetch() + ReadableStream and renders
    progress messages until the final "result" event arrives.  This avoids
    Vercel's 20-second serverless function timeout because the long-running
    work happens on the Railway backend — the browser connection stays open
    for as long as necessary.
    """
    if not req.messages:
        raise HTTPException(status_code=422, detail="messages array cannot be empty")

    user_id = current_user["user_id"]
    last_message = req.messages[-1]
    image_included = bool(last_message.image_base64)

    # Fetch profile before starting the stream — blocking I/O, done once.
    supabase = get_supabase_admin()
    profile_result = (
        supabase.table("profiles")
        .select("city, country")
        .eq("id", user_id)
        .single()
        .execute()
    )
    profile = profile_result.data or {}
    city: str = profile.get("city") or ""
    country: str = profile.get("country") or ""

    # Queue bridges the pipeline coroutine and the SSE generator.
    event_q: asyncio.Queue[dict] = asyncio.Queue()

    async def emit(event: dict) -> None:
        await event_q.put(event)

    async def run_pipeline() -> None:
        try:
            # ── 1. Intent classification (OpenAI gpt-4o-mini front-end router) ─
            # Rule 3: gpt-4o-mini is the first gate — classifies intent, extracts
            # budget, generates localized query, and flags mainstream commodities.
            # Falls back to Gemini automatically if OpenAI is unavailable.
            default_language = _country_to_language(country) if country else "English"
            await emit({"type": "status", "message": _t(default_language, "intent")})
            intent_data = await run_in_threadpool(
                openai_router.classify_intent_and_route, req.messages, city, country
            )

            # Detect user language from Gemini's response; fall back to country guess.
            lang_code: str = intent_data.get("language_code") or ""
            detected_language: str = _ISO_TO_LANGUAGE.get(lang_code, default_language)

            intent: str = intent_data.get("intent", "CHAT")
            reply: str | None = intent_data.get("reply")
            raw_params: dict = intent_data.get("collected_params") or {}
            search_globally: bool = bool(intent_data.get("search_globally", False))
            is_refinement: bool = bool(intent_data.get("is_refinement", False))
            # Hybrid-search hard filters — populated by Gemini on wrong-category complaints.
            # These break the cosine-similarity blind spot for negations ("NOT accessories").
            excluded_keywords: list[str] = intent_data.get("excluded_keywords") or []
            price_floor: float | None = intent_data.get("price_floor") or None
            specific_models: list[str] | None = intent_data.get("specific_models") or None
            gemini_domains: list[str] | None = (
                None if search_globally else (intent_data.get("local_domains") or None)
            )
            gemini_localized_query: str | None = (
                intent_data.get("localized_search_query")
                or intent_data.get("search_query")
                or None
            )

            collected_params = IntentParams(
                category=raw_params.get("category"),
                budget=raw_params.get("budget"),
                budget_max=raw_params.get("budget_max"),
                budget_currency=raw_params.get("budget_currency"),
                preference=raw_params.get("preference"),
            )

            # ── 2. CHAT / CLARIFY — return immediately ───────────────────────
            if intent in ("CHAT", "CLARIFY"):
                response = ChatResponse(
                    intent=intent,
                    reply=reply or "How can I help you find the perfect product?",
                    collected_params=collected_params,
                )
                asyncio.create_task(run_in_threadpool(
                    _save_chat_history,
                    user_id, last_message.content, image_included,
                    intent, response.model_dump(),
                ))
                await emit({"type": "result", "data": response.model_dump()})
                return

            # ── 3. Build query + domain resolution ──────────────────────────
            excluded_urls: set[str] = set(req.excluded_urls) if req.excluded_urls else set()

            # Domain resolution: DB is authoritative, Gemini's hint is fallback.
            # The Traffic Cop inside _run_product_pipeline splits these into
            # niche (Lane A scraper) vs heavy (Lane B Gemini grounding) automatically.
            country_code = retailers_service.country_name_to_iso(country) if country else ""
            if search_globally:
                local_domains = None
            elif not country_code:
                local_domains = gemini_domains or None
            else:
                db_domains = retailers_service.get_domains_for_country(country_code)
                local_domains = db_domains or gemini_domains or None

            deterministic_query, local_domains = _build_search_query(
                gemini_localized_query, collected_params, local_domains
            )
            logger.info(
                "[SEARCH] query=%r  country_code=%r  all_domains=%d  city=%r  country=%r  "
                "excluded=%d  global=%s  refinement=%s",
                deterministic_query, country_code,
                len(local_domains or []),
                city, country, len(excluded_urls), search_globally, is_refinement,
            )

            await emit({"type": "status", "message": _t(detected_language, "cache")})
            embedding: list[float] = await run_in_threadpool(
                gemini_service.generate_embedding, deterministic_query
            )
            cached = None
            if not excluded_urls and not is_refinement and embedding:
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
                asyncio.create_task(run_in_threadpool(
                    _save_chat_history,
                    user_id, last_message.content, image_included,
                    "SEARCH", response.model_dump(),
                ))
                await emit({"type": "result", "data": response.model_dump()})
                return

            # ── 4. Phase 2: Community research (Gemini + Google Search grounding) ──
            # Gemini searches Reddit/forums for the most recommended specific models.
            # If Phase 1 (OpenAI) didn't extract a model name, the picks become the
            # primary Tavily search input (Phase 3), replacing the generic query.
            community_picks: list[str] = []
            await emit({"type": "status", "message": _t(detected_language, "researching")})
            try:
                research = await asyncio.wait_for(
                    run_in_threadpool(
                        gemini_service.research_community_picks,
                        collected_params.category or "",
                        collected_params.preference or None,
                        collected_params.budget or None,
                        detected_language,
                    ),
                    timeout=15.0,
                )
                community_picks = research.get("recommendations") or []
                if research.get("insight"):
                    await emit({"type": "status", "message": research["insight"]})
            except Exception as _research_exc:
                logger.warning("[RESEARCH] phase failed, continuing without: %s", _research_exc)

            # Wire Phase 2 picks → Phase 3 Tavily when Phase 1 found no specific model.
            # Phase 1's specific_models (user-named model) always takes priority.
            effective_models: list[str] | None = specific_models
            if not effective_models and community_picks:
                effective_models = community_picks[:3]
                logger.info("[PHASE2→3] using community picks as Tavily input: %s", effective_models)

            # ── 5. 5-Phase Pipeline (all products go through same flow) ──────────
            # Phase 3 Traffic Cop inside _run_product_pipeline routes:
            #   • niche-tier domains + product URL → Lane A (curl_cffi + JSON-LD)
            #   • enterprise/category/unknown URLs → Lane B (Gemini Search Grounding)
            ranked: list[dict] = []
            fallback_message: str | None = None

            ranked = await _run_product_pipeline(
                deterministic_query, collected_params, city, country, local_domains,
                excluded_urls or None, is_global=search_globally,
                on_event=emit, user_language=detected_language,
                excluded_keywords=excluded_keywords or None,
                price_floor=price_floor,
                community_picks=community_picks or None,
                specific_models=effective_models,
            )

            # ── 7. No results path ───────────────────────────────────────────
            if not ranked:
                await emit({"type": "status", "message": _t(detected_language, "suggestions")})
                clarify_reply = await run_in_threadpool(
                    gemini_service.explain_no_results,
                    collected_params.category or "product",
                    collected_params.preference or "",
                    collected_params.budget_max,
                    collected_params.budget_currency,
                    city,
                    country,
                    detected_language,
                )
                no_results_response = ChatResponse(
                    intent="CLARIFY",
                    reply=clarify_reply,
                    collected_params=collected_params,
                )
                asyncio.create_task(run_in_threadpool(
                    _save_chat_history,
                    user_id, last_message.content, image_included,
                    "CLARIFY", no_results_response.model_dump(),
                ))
                await emit({"type": "result", "data": no_results_response.model_dump()})
                return

            # ── 8. Build final response ──────────────────────────────────────
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

            products_json = [p.model_dump() for p in products]
            if embedding:
                asyncio.create_task(run_in_threadpool(
                    cache_service.save_cache,
                    deterministic_query,
                    embedding,
                    collected_params.category or "",
                    collected_params.budget_max,
                    collected_params.budget_currency,
                    collected_params.preference,
                    products_json,
                ))

            response = ChatResponse(
                intent="SEARCH",
                reply=_t(detected_language, "results_header"),
                products=products,
                collected_params=collected_params,
                from_cache=False,
                fallback_message=fallback_message,
            )
            asyncio.create_task(run_in_threadpool(
                _save_chat_history,
                user_id, last_message.content, image_included,
                "SEARCH", response.model_dump(),
            ))
            await emit({"type": "result", "data": response.model_dump()})

        except Exception as exc:
            logger.error("Pipeline error: %s", exc, exc_info=True)
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            await emit({"type": "error", "message": detail or "An unexpected error occurred."})

    task = asyncio.create_task(run_pipeline())

    async def generate():
        try:
            while True:
                event = await event_q.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event["type"] in ("result", "error"):
                    break
        finally:
            task.cancel()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering on Railway
            "Connection": "keep-alive",
        },
    )
