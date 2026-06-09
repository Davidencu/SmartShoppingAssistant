import asyncio
import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from models.search import ChatRequest, ChatResponse, IntentParams, Product, ProductScores
from routers.auth import get_current_user
from services import cache_service, gemini_service, retailers_service, scraper_service, tavily_service
from services.scraper_service import is_likely_product_url
from services.supabase_service import get_supabase_admin

router = APIRouter(prefix="/search", tags=["search"])
logger = logging.getLogger(__name__)

# ── Demo: mainstream domain blocklist ────────────────────────────────────────
# Proof-of-concept filter: drop any Tavily result whose domain is in this set
# so the demo only exercises niche retailers and the ghost-layer fallback.
# Remove this block (and the filter in _run_product_pipeline) before production.
_DEMO_BLOCKED_DOMAINS: frozenset[str] = frozenset({
    # ── North America mainstream ──────────────────────────────────────────────
    "amazon.com", "walmart.com", "target.com", "bestbuy.com",
    "costco.com", "macys.com", "nordstrom.com", "apple.com", "nike.com", "adidas.com",
    # ── UK mainstream ─────────────────────────────────────────────────────────
    "amazon.co.uk", "currys.co.uk", "argos.co.uk", "johnlewis.com", "asos.com",
    # ── Germany mainstream ────────────────────────────────────────────────────
    "amazon.de", "mediamarkt.de", "saturn.de", "otto.de", "zalando.de",
    # ── France mainstream ─────────────────────────────────────────────────────
    "amazon.fr", "cdiscount.com", "darty.com", "boulanger.com", "zalando.fr",
    # ── Italy mainstream ──────────────────────────────────────────────────────
    "amazon.it", "euronics.it", "trony.it", "mediaworld.it", "unieuro.it",
    # ── Spain mainstream ──────────────────────────────────────────────────────
    "amazon.es", "mediamarkt.es",
    # ── Poland mainstream ─────────────────────────────────────────────────────
    "amazon.pl", "allegro.pl",
    # ── Netherlands / Belgium mainstream ─────────────────────────────────────
    "amazon.nl", "coolblue.nl", "bol.com", "mediamarkt.nl",
    # ── Romania mainstream ────────────────────────────────────────────────────
    "emag.ro", "altex.ro", "flanco.ro", "cel.ro",
    # ── Czech / Slovakia mainstream ───────────────────────────────────────────
    "mall.cz",
    # ── Nordics mainstream ────────────────────────────────────────────────────
    "amazon.se", "power.fi",
    # ── Global mainstream ─────────────────────────────────────────────────────
    "amazon.ca", "amazon.com.au", "amazon.co.jp", "amazon.in",
    "amazon.com.br", "amazon.com.mx",
    "ebay.com", "ebay.co.uk", "ebay.de", "ebay.fr", "ebay.it", "ebay.es",
    "zalando.com", "hm.com", "uniqlo.com", "aliexpress.com",
})

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
        "intent":           "Classifying intent...",
        "researching":      "Researching community recommendations...",
        "cache":            "Checking cache...",
        "search":           "Searching for products...",
        "found_pages":      "Found {n} page{s} — opening {stores}...",
        "browsed":          "Browsed {store} ({done}/{total})",
        "found_prods":      "Found {n} product{s} within budget — calculating scores...",
        "scoring":          "Scoring with AI...",
        "mainstream_try":   "Nothing in specialty stores — trying mainstream retailers...",
        "global":           "Trying global search...",
        "suggestions":      "Generating suggestions...",
        "results_header":   "Here are the top products ranked by value score:",
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
        md_head = (s.get("markdown") or "")[:1500].lower()
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
        if jld.get("price"):   score += 5_000
        if jld.get("rating"):  score += 2_000
        if jld.get("name"):    score += 1_000
        return score

    candidates = [
        s for s in scraped
        if (
            len(s.get("markdown") or "") > 400
            and _available(s)
            and _in_budget(s)
            and _above_floor(s)
            and _right_category(s)
        )
    ]
    dropped = len(scraped) - len(candidates)
    if dropped:
        logger.info(
            "[CONTENDER] dropped %d/%d pages (wrong category or below price floor)",
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
    no_global_supplement: bool = False,
) -> list[dict]:
    """
    3-phase pipeline:

    Phase 1 — Tavily radar: cast a wide net (~25 URLs).
    Phase 2 — curl_cffi scrape + contender filter: parallel-scrape all URLs,
              drop out-of-stock / over-budget pages → top 10 contenders.
    Phase 3 — Gemini judge: 40-point scoring matrix → top 3 ranked products.

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

    if len(tavily_results) == 0 and not is_global and not no_global_supplement:
        # Supplement with global e-commerce domains when local/model searches come up empty.
        # Skipped for is_global=True runs and for the niche-first pass (no_global_supplement=True)
        # so the caller can try mainstream country domains before jumping straight to global.
        supplement_domains = retailers_service.get_global_domains() or None
        if specific_models:
            seen_pdp = {r["url"] for r in tavily_results}
            for model in specific_models[:3]:
                model_hits = await run_in_threadpool(
                    tavily_service.search_products, f"{model} buy", 8, supplement_domains
                )
                for r in model_hits:
                    if r["url"] not in seen_pdp:
                        tavily_results.append(r)
                        seen_pdp.add(r["url"])
            logger.info("[P1/TAVILY] specific_models global supplement: %d results", len(tavily_results))
        else:
            global_results = await run_in_threadpool(
                tavily_service.search_products, query, 15, supplement_domains
            )
            logger.info("[P1/TAVILY] global supplement: %d results", len(global_results))
            seen = {r["url"] for r in tavily_results}
            for r in global_results:
                if r["url"] not in seen:
                    tavily_results.append(r)
                    seen.add(r["url"])

    n_initial = len(tavily_results)
    if excluded_urls:
        before_excl = len(tavily_results)
        tavily_results = [r for r in tavily_results if r["url"] not in excluded_urls]
        dropped = before_excl - len(tavily_results)
        if dropped:
            logger.info("[P1/TAVILY] dropped %d excluded URL(s)", dropped)

    # ── DEMO: drop mainstream domains ────────────────────────────────────────
    before_demo = len(tavily_results)
    tavily_results = [
        r for r in tavily_results
        if urlparse(r["url"]).netloc.replace("www.", "") not in _DEMO_BLOCKED_DOMAINS
    ]
    if len(tavily_results) < before_demo:
        logger.info("[DEMO] dropped %d mainstream domain URL(s)", before_demo - len(tavily_results))

    # ── STRICT DOMAIN ENFORCEMENT (The Bouncer) ──────────────────────────
    # Tavily's include_domains is a soft hint. We must hard-filter the results
    # so mainstream aggregators never leak into our niche-first execution passes.
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
            logger.info("[P1/TAVILY] Strict domain lock enforced. Dropped %d leaked URLs.", dropped_strict)

    # Drop category/listing/search URLs — only scrape product detail pages
    before_shape = len(tavily_results)
    kept_results = []
    for r in tavily_results:
        if is_likely_product_url(r["url"]):
            kept_results.append(r)
        else:
            logger.info("[GATEKEEPER] dropped non-PDP: %s", r["url"])
    tavily_results = kept_results
    dropped_cat = before_shape - len(tavily_results)
    if dropped_cat:
        logger.info("[P1/TAVILY] dropped %d category/listing URLs via shape filter", dropped_cat)

    logger.info("[P1/TAVILY] %d total URLs for fast filter", len(tavily_results))
    if not tavily_results:
        logger.warning("[P1/TAVILY] no URLs passed filters — returning empty")
        return []

    url_to_title = {r["url"]: r.get("title", "") for r in tavily_results}

    # ── Phase 2: curl_cffi scrape + contender filter ──────────────────────
    urls = [r["url"] for r in tavily_results]

    if on_event:
        unique_domains = list(dict.fromkeys(
            urlparse(u).netloc.removeprefix("www.") for u in urls
        ))
        stores_str = ", ".join(_store_name(d) for d in unique_domains)
        await on_event({
            "type": "status",
            "message": _t(user_language, "found_pages", n=len(urls), s="s" if len(urls) != 1 else "", stores=stores_str),
        })

    # Per-URL callback: fires as each scrape resolves (parallel, out-of-order)
    async def _on_url_done(url: str, done: int, total: int) -> None:
        if on_event:
            domain = urlparse(url).netloc.removeprefix("www.") or url
            await on_event({
                "type": "status",
                "message": _t(user_language, "browsed",
                              store=_store_name(domain), done=done, total=total),
            })

    scraped: list[dict] = await scraper_service.scrape_urls(
        urls, on_done=_on_url_done if on_event else None
    )
    for s in scraped:
        s["title"] = url_to_title.get(s["url"], "")

    contenders = _pick_contenders(
        scraped, params.budget_max,
        excluded_keywords=excluded_keywords,
        price_floor=price_floor,
    )

    # ── Diagnostic counts ─────────────────────────────────────────────────────
    _n_with_content = sum(1 for s in scraped if len(s.get("markdown") or "") > 400)
    _n_fetch_fail   = len(scraped) - _n_with_content
    _n_no_struct    = sum(
        1 for s in scraped
        if len(s.get("markdown") or "") > 400 and not (s.get("jsonld") or {})
    )
    _n_filter_fail  = _n_with_content - len(contenders)

    logger.info(
        "[P2/SCRAPER] %d/%d URLs passed contender filter",
        len(contenders), len(scraped),
    )
    for c in contenders:
        logger.info("  ↳ %s  (%d chars, price=%s)",
                    c["url"], len(c.get("markdown", "")),
                    (c.get("jsonld") or {}).get("price", "?"))

    if not contenders:
        logger.warning(
            "[P2/SCRAPER] no contenders after filter — returning empty\n"
            "  [DIAG] candidates=%d  gatekeeper_rej=%d  fetch_fail=%d  "
            "no_struct=%d  filter_fail=%d  contenders=0  final=0",
            n_initial, n_initial - len(urls), _n_fetch_fail, _n_no_struct, _n_filter_fail,
        )
        return []

    if on_event:
        n = len(contenders)
        await on_event({
            "type": "status",
            "message": _t(user_language, "found_prods", n=n, s="s" if n != 1 else ""),
        })

    # ── Phase 3: Gemini judge ─────────────────────────────────────────────
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
    logger.info("[P3/GEMINI] returned %d ranked products", len(ranked))

    valid_urls = {r["url"] for r in contenders}
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
            "[P4/GEMINI] dropped %d hallucinated URL(s), %d remain",
            before - len(ranked), len(ranked),
        )

    if not ranked and contenders:
        logger.warning(
            "[P3/HEURISTIC] AI scorer returned nothing — price-sort fallback on %d contenders",
            len(contenders),
        )
        ranked = _heuristic_rank(contenders, params.budget_max)

    logger.info(
        "[DIAG]\n"
        "  Candidates found (Tavily): %d\n"
        "  Rejected by gatekeeper:   %d\n"
        "  Sent to scraper:          %d\n"
        "  Fetch failures:           %d\n"
        "  No structured data:       %d\n"
        "  Failed filters (OOS/budget/category): %d\n"
        "  Contenders → Gemini:      %d\n"
        "  Final recommendations:    %d",
        n_initial,
        n_initial - len(urls),
        len(urls),
        _n_fetch_fail,
        _n_no_struct,
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
            # ── 1. Intent classification ────────────────────────────────────
            # Use country to guess the language for the first status message
            # before Gemini returns the actual language_code.
            default_language = _country_to_language(country) if country else "English"
            await emit({"type": "status", "message": _t(default_language, "intent")})
            intent_data = await run_in_threadpool(
                gemini_service.classify_intent, req.messages, city, country
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
            # supported_retailers table maps ISO country codes → active domains +
            # proxy requirements, so we never need to hardcode retailer lists.
            # niche_domains = mid-market/specialty tier (searched first — better
            # scrapability and JSON-LD than mainstream platforms like Amazon/eMag).
            country_code = retailers_service.country_name_to_iso(country) if country else ""
            if search_globally:
                niche_domains: list[str] | None = None
                local_domains = None
            elif not country_code:
                # Unknown country — use Gemini's domain hint; no niche split available
                niche_domains = None
                local_domains = gemini_domains or None
            else:
                db_domains = retailers_service.get_domains_for_country(country_code)
                niche_domains = retailers_service.get_niche_domains_for_country(country_code) or None
                local_domains = db_domains or gemini_domains or None

            deterministic_query, local_domains = _build_search_query(
                gemini_localized_query, collected_params, local_domains
            )
            logger.info(
                "[SEARCH] query=%r  country_code=%r  niche=%d  all=%d  city=%r  country=%r  "
                "excluded=%d  global=%s  refinement=%s",
                deterministic_query, country_code,
                len(niche_domains or []), len(local_domains or []),
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

            # ── 4. Community research phase ─────────────────────────────────
            # Runs before Tavily on every cache miss. Gemini uses Google Search
            # grounding to find Reddit/Twitter/forum consensus, then:
            #   • streams the insight to the frontend (masks Tavily latency)
            #   • passes picks to the scorer as a soft quality_confidence signal
            # NOTE: picks are NOT injected into the Tavily query — they are
            # guidance only. Injecting model names would constrain Tavily to those
            # exact (often expensive/out-of-budget) products and return zero results.
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

            # ── 5. Niche-first pipeline ─────────────────────────────────────
            # 5a. Local niche + global niche combined.
            # Niche/mid-market sites have lighter anti-bot measures and richer
            # JSON-LD — combining both geographies maximises coverage without
            # touching proxy-required mainstream domains.
            ranked: list[dict] = []
            global_niche = retailers_service.get_global_niche_domains()
            if search_globally:
                combined_niche: list[str] | None = global_niche or None
            else:
                combined_niche = list(dict.fromkeys(
                    (niche_domains or []) + global_niche
                )) or None

            if combined_niche:
                ranked = await _run_product_pipeline(
                    deterministic_query, collected_params, city, country, combined_niche,
                    excluded_urls or None, is_global=False,
                    on_event=emit, user_language=detected_language,
                    excluded_keywords=excluded_keywords or None,
                    price_floor=price_floor,
                    community_picks=community_picks or None,
                    specific_models=specific_models,
                    no_global_supplement=True,
                )

            # 5b. Local mainstream when niche pass returns nothing.
            # Only relevant for country-scoped searches; global searches skip
            # straight to the global mainstream fallback below.
            if not ranked and not search_globally:
                if combined_niche:
                    await emit({"type": "status",
                                "message": _t(detected_language, "mainstream_try")})
                ranked = await _run_product_pipeline(
                    deterministic_query, collected_params, city, country, local_domains,
                    excluded_urls or None, is_global=False,
                    on_event=emit, user_language=detected_language,
                    excluded_keywords=excluded_keywords or None,
                    price_floor=price_floor,
                    community_picks=community_picks or None,
                    specific_models=specific_models,
                )

            # ── 6. Global mainstream fallback ────────────────────────────────
            # Amazon, eBay, AliExpress, etc. — proxy-heavy, but last resort.
            # Only global mainstream domains are used here; niche ones were
            # already tried in 5a so there is no point re-querying them.
            fallback_message: str | None = None
            if not ranked and (local_domains or search_globally):
                logger.info("[SEARCH] niche+local scoring empty — retrying global mainstream")
                await emit({"type": "status", "message": _t(detected_language, "global")})
                global_mainstream = retailers_service.get_global_mainstream_domains() or None
                ranked = await _run_product_pipeline(
                    deterministic_query, collected_params, city, country, global_mainstream,
                    excluded_urls or None, is_global=True,
                    on_event=emit, user_language=detected_language,
                    excluded_keywords=excluded_keywords or None,
                    price_floor=price_floor,
                    community_picks=community_picks or None,
                    specific_models=specific_models,
                )
                if ranked:
                    fallback_message = _t(detected_language, "fallback")

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
