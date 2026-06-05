-- Migration: supported_retailers
-- Replaces the hardcoded _HARD_DOMAINS list and Gemini-guessed local_domains.
-- target_country: ISO 3166-1 alpha-2 code (RO, DE, …) or 'GLOBAL'
-- requires_proxy: TRUE → skip free direct fetch, route straight to residential proxy
-- is_active:      FALSE → excluded from all lookups without deleting the row

CREATE TABLE IF NOT EXISTS supported_retailers (
    id              BIGSERIAL PRIMARY KEY,
    domain          TEXT        NOT NULL UNIQUE,
    target_country  TEXT        NOT NULL,
    requires_proxy  BOOLEAN     NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT valid_country CHECK (
        target_country ~ '^[A-Z]{2}$' OR target_country = 'GLOBAL'
    )
);

CREATE INDEX IF NOT EXISTS idx_supported_retailers_active_country
    ON supported_retailers (target_country)
    WHERE is_active = TRUE;

ALTER TABLE supported_retailers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON supported_retailers USING (true);

-- ─────────────────────────────────────────────────────────────────────────────
-- SEED DATA
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO supported_retailers (domain, target_country, requires_proxy) VALUES

-- ── Romania ──────────────────────────────────────────────────────────────────
('emag.ro',          'RO', TRUE),
('altex.ro',         'RO', TRUE),
('flanco.ro',        'RO', TRUE),
('pcgarage.ro',      'RO', TRUE),
('cel.ro',           'RO', TRUE),
('elefant.ro',       'RO', TRUE),
('dedeman.ro',       'RO', TRUE),
('carrefour.ro',     'RO', TRUE),
('mediagalaxy.ro',   'RO', TRUE),
('auchan.ro',        'RO', FALSE),
('decathlon.ro',     'RO', TRUE),
('sportguru.ro',     'RO', TRUE),
('hervis.ro',        'RO', FALSE),
('watchshop.ro',     'RO', FALSE),
('bb-shop.ro',       'RO', FALSE),

-- ── Germany ───────────────────────────────────────────────────────────────────
('mediamarkt.de',         'DE', TRUE),
('saturn.de',             'DE', TRUE),
('otto.de',               'DE', FALSE),
('zalando.de',            'DE', TRUE),
('alternate.de',          'DE', FALSE),
('notebooksbilliger.de',  'DE', FALSE),
('cyberport.de',          'DE', FALSE),
('mediaexpert.de',        'DE', FALSE),

-- ── France ───────────────────────────────────────────────────────────────────
('fnac.fr',          'FR', FALSE),
('cdiscount.com',    'FR', FALSE),
('darty.com',        'FR', FALSE),
('boulanger.com',    'FR', FALSE),
('zalando.fr',       'FR', TRUE),

-- ── Italy ─────────────────────────────────────────────────────────────────────
('mediaworld.it',    'IT', FALSE),
('unieuro.it',       'IT', FALSE),
('euronics.it',      'IT', FALSE),

-- ── Spain ─────────────────────────────────────────────────────────────────────
('pccomponentes.com', 'ES', FALSE),
('mediamarkt.es',     'ES', TRUE),
('fnac.es',           'ES', FALSE),

-- ── Poland ───────────────────────────────────────────────────────────────────
('allegro.pl',       'PL', FALSE),
('morele.net',       'PL', FALSE),
('x-kom.pl',         'PL', FALSE),
('mediaexpert.pl',   'PL', FALSE),

-- ── Netherlands ──────────────────────────────────────────────────────────────
('coolblue.nl',      'NL', TRUE),
('bol.com',          'NL', TRUE),
('mediamarkt.nl',    'NL', TRUE),

-- ── Belgium ───────────────────────────────────────────────────────────────────
('coolblue.be',      'BE', TRUE),
('bol.be',           'BE', TRUE),
('mediamarkt.be',    'BE', TRUE),

-- ── United Kingdom ────────────────────────────────────────────────────────────
('currys.co.uk',     'GB', TRUE),
('argos.co.uk',      'GB', TRUE),
('johnlewis.com',    'GB', TRUE),
('asos.com',         'GB', TRUE),
('very.co.uk',       'GB', FALSE),

-- ── United States ─────────────────────────────────────────────────────────────
('walmart.com',       'US', TRUE),
('target.com',        'US', TRUE),
('bestbuy.com',       'US', TRUE),
('newegg.com',        'US', TRUE),
('bhphotovideo.com',  'US', FALSE),
('adorama.com',       'US', FALSE),
('costco.com',        'US', TRUE),
('macys.com',         'US', TRUE),
('nordstrom.com',     'US', TRUE),

-- ── Sweden ────────────────────────────────────────────────────────────────────
('elgiganten.se',    'SE', FALSE),
('webhallen.com',    'SE', FALSE),
('komplett.se',      'SE', FALSE),

-- ── Norway ────────────────────────────────────────────────────────────────────
('elkjop.no',        'NO', FALSE),
('komplett.no',      'NO', FALSE),
('power.no',         'NO', FALSE),

-- ── Denmark ───────────────────────────────────────────────────────────────────
('elgiganten.dk',    'DK', FALSE),
('komplett.dk',      'DK', FALSE),

-- ── Finland ───────────────────────────────────────────────────────────────────
('verkkokauppa.com', 'FI', FALSE),
('power.fi',         'FI', FALSE),
('gigantti.fi',      'FI', FALSE),

-- ── Portugal ─────────────────────────────────────────────────────────────────
('worten.pt',        'PT', FALSE),
('fnac.pt',          'PT', FALSE),

-- ── Czech Republic ────────────────────────────────────────────────────────────
('alza.cz',          'CZ', FALSE),
('czc.cz',           'CZ', FALSE),
('datart.cz',        'CZ', FALSE),

-- ── Slovakia ──────────────────────────────────────────────────────────────────
('alza.sk',          'SK', FALSE),
('mall.sk',          'SK', FALSE),

-- ── Hungary ───────────────────────────────────────────────────────────────────
('emag.hu',          'HU', TRUE),
('alza.hu',          'HU', FALSE),
('extreme-digital.hu', 'HU', FALSE),

-- ── Greece ────────────────────────────────────────────────────────────────────
('skroutz.gr',       'GR', FALSE),
('public.gr',        'GR', FALSE),
('mediamarkt.gr',    'GR', TRUE),

-- ── Austria ───────────────────────────────────────────────────────────────────
('mediamarkt.at',    'AT', TRUE),
('saturn.at',        'AT', TRUE),
('cyberport.at',     'AT', FALSE),

-- ── Switzerland ───────────────────────────────────────────────────────────────
('digitec.ch',       'CH', FALSE),
('galaxus.ch',       'CH', FALSE),
('mediamarkt.ch',    'CH', TRUE),

-- ── Australia ─────────────────────────────────────────────────────────────────
('jbhifi.com.au',           'AU', FALSE),
('harveynorman.com.au',     'AU', FALSE),
('bigw.com.au',             'AU', FALSE),
('officeworks.com.au',      'AU', FALSE),

-- ── Canada ────────────────────────────────────────────────────────────────────
('bestbuy.ca',       'CA', TRUE),
('staples.ca',       'CA', FALSE),
('canadacomputers.com', 'CA', FALSE),

-- ── India ─────────────────────────────────────────────────────────────────────
('flipkart.com',     'IN', TRUE),
('croma.com',        'IN', FALSE),
('reliancedigital.in', 'IN', FALSE),

-- ── Brazil ────────────────────────────────────────────────────────────────────
('mercadolivre.com.br',  'BR', TRUE),
('americanas.com.br',    'BR', FALSE),
('casasbahia.com.br',    'BR', FALSE),
('submarino.com.br',     'BR', FALSE),

-- ── South Africa ──────────────────────────────────────────────────────────────
('takealot.com',     'ZA', FALSE),
('game.co.za',       'ZA', FALSE),

-- ── Ireland ───────────────────────────────────────────────────────────────────
('currys.ie',        'IE', TRUE),
('argos.ie',         'IE', TRUE),

-- ── New Zealand ───────────────────────────────────────────────────────────────
('jbhifi.co.nz',     'NZ', FALSE),
('harveynorman.co.nz', 'NZ', FALSE),

-- ── GLOBAL (all-region retailers — Amazon storefronts, eBay, AliExpress, etc.) ─
('amazon.com',       'GLOBAL', TRUE),
('amazon.de',        'GLOBAL', TRUE),
('amazon.co.uk',     'GLOBAL', TRUE),
('amazon.fr',        'GLOBAL', TRUE),
('amazon.it',        'GLOBAL', TRUE),
('amazon.es',        'GLOBAL', TRUE),
('amazon.pl',        'GLOBAL', TRUE),
('amazon.nl',        'GLOBAL', TRUE),
('amazon.se',        'GLOBAL', TRUE),
('amazon.ca',        'GLOBAL', TRUE),
('amazon.com.au',    'GLOBAL', TRUE),
('amazon.com.br',    'GLOBAL', TRUE),
('amazon.in',        'GLOBAL', TRUE),
('amazon.co.jp',     'GLOBAL', TRUE),
('amazon.com.mx',    'GLOBAL', TRUE),
('ebay.com',         'GLOBAL', FALSE),
('ebay.co.uk',       'GLOBAL', FALSE),
('ebay.de',          'GLOBAL', FALSE),
('ebay.fr',          'GLOBAL', FALSE),
('ebay.it',          'GLOBAL', FALSE),
('ebay.es',          'GLOBAL', FALSE),
('ebay.com.au',      'GLOBAL', FALSE),
('aliexpress.com',   'GLOBAL', TRUE),
('zalando.com',      'GLOBAL', TRUE),
('hm.com',           'GLOBAL', FALSE),
('uniqlo.com',       'GLOBAL', FALSE),
('decathlon.com',    'GLOBAL', FALSE),
('apple.com',        'GLOBAL', TRUE),
('nike.com',         'GLOBAL', TRUE),
('adidas.com',       'GLOBAL', TRUE),
('zara.com',         'GLOBAL', FALSE),
('ikea.com',         'GLOBAL', TRUE),
('samsung.com',      'GLOBAL', FALSE),
('jd.com',           'GLOBAL', FALSE)

ON CONFLICT (domain)
DO UPDATE SET 
    requires_proxy = EXCLUDED.requires_proxy,
    target_country = EXCLUDED.target_country,
    is_active = EXCLUDED.is_active;
