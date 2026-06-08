-- Migration: retailer tiers
-- Adds a `tier` column so the search pipeline can try mid-market/specialty stores
-- (tier = 'niche') before falling back to large mainstream platforms
-- (tier = 'mainstream'). Default is 'mainstream' so existing rows are unaffected
-- until the UPDATE below re-classifies them.

ALTER TABLE supported_retailers
ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'mainstream'
CONSTRAINT valid_tier CHECK (tier IN ('niche', 'mainstream'));

-- ── Re-classify existing specialty / mid-market retailers as 'niche' ──────────
UPDATE supported_retailers
SET tier = 'niche'
WHERE domain IN (
    -- North America specialty
    'newegg.com', 'bhphotovideo.com', 'adorama.com',
    'canadacomputers.com', 'staples.ca',
    -- UK specialty
    'very.co.uk',
    -- Germany specialty
    'alternate.de', 'notebooksbilliger.de', 'cyberport.de', 'mediaexpert.de',
    -- France specialty
    'fnac.fr',
    -- Italy specialty
    'euronics.it',
    -- Spain specialty
    'pccomponentes.com', 'fnac.es',
    -- Poland specialty
    'morele.net', 'x-kom.pl', 'mediaexpert.pl',
    -- Nordics specialty
    'webhallen.com',
    'komplett.no', 'komplett.se', 'komplett.dk',
    'elkjop.no', 'power.no', 'power.fi', 'gigantti.fi', 'verkkokauppa.com',
    'elgiganten.se', 'elgiganten.dk',
    -- Portugal specialty
    'worten.pt', 'fnac.pt',
    -- Czech / Slovakia specialty
    'alza.cz', 'czc.cz', 'datart.cz', 'alza.sk', 'mall.sk',
    -- Hungary specialty
    'alza.hu', 'extreme-digital.hu',
    -- Greece specialty
    'skroutz.gr', 'public.gr',
    -- Austria specialty
    'cyberport.at',
    -- Switzerland specialty (best scrapability in Europe)
    'digitec.ch', 'galaxus.ch',
    -- Australia specialty
    'jbhifi.com.au', 'officeworks.com.au',
    -- India specialty
    'croma.com', 'reliancedigital.in',
    -- Brazil specialty
    'casasbahia.com.br', 'submarino.com.br',
    -- South Africa
    'takealot.com', 'game.co.za',
    -- Romania specialty (small, no heavy anti-bot)
    'pcgarage.ro', 'bb-shop.ro', 'sportguru.ro', 'watchshop.ro', 'hervis.ro',
    -- Global manufacturer / specialty
    'decathlon.com', 'samsung.com'
);

-- ── New niche domains ─────────────────────────────────────────────────────────
INSERT INTO supported_retailers (domain, target_country, requires_proxy, tier) VALUES

-- ── Germany ───────────────────────────────────────────────────────────────────
('mindfactory.de',          'DE', FALSE, 'niche'),   -- PC components
('euronics.de',             'DE', FALSE, 'niche'),   -- franchise dealer network
('reichelt.de',             'DE', FALSE, 'niche'),   -- electronic components

-- ── France ───────────────────────────────────────────────────────────────────
('ldlc.com',                'FR', FALSE, 'niche'),   -- IT specialty
('topachat.com',            'FR', FALSE, 'niche'),   -- tech specialty
('rueducommerce.fr',        'FR', FALSE, 'niche'),   -- mid-market tech

-- ── Italy ─────────────────────────────────────────────────────────────────────
('trony.it',                'IT', FALSE, 'niche'),   -- consumer electronics chain

-- ── United Kingdom ────────────────────────────────────────────────────────────
('scan.co.uk',              'GB', FALSE, 'niche'),   -- IT components
('ebuyer.com',              'GB', FALSE, 'niche'),   -- tech/components
('overclockers.co.uk',      'GB', FALSE, 'niche'),   -- gaming/PC
('laptopsdirect.co.uk',     'GB', FALSE, 'niche'),   -- laptop specialty

-- ── United States ─────────────────────────────────────────────────────────────
('overstock.com',           'US', FALSE, 'niche'),   -- discount/home
('wayfair.com',             'US', FALSE, 'niche'),   -- home furnishings
('chewy.com',               'US', FALSE, 'niche'),   -- pet supplies
('rei.com',                 'US', FALSE, 'niche'),   -- outdoor/sporting
('rakuten.com',             'US', FALSE, 'niche'),   -- cashback marketplace
('microcenter.com',         'US', FALSE, 'niche'),   -- computer specialty

-- ── Romania ──────────────────────────────────────────────────────────────────
('evomag.ro',               'RO', FALSE, 'niche'),   -- tech specialty
('quickmobile.ro',          'RO', FALSE, 'niche'),   -- mobile/accessories

-- ── GLOBAL niche ──────────────────────────────────────────────────────────────
('reverb.com',              'GLOBAL', FALSE, 'niche'),  -- used music gear
('sweetwater.com',          'GLOBAL', FALSE, 'niche'),  -- audio/music equipment
('backcountry.com',         'GLOBAL', FALSE, 'niche'),  -- outdoor gear
('zappos.com',              'GLOBAL', FALSE, 'niche')   -- shoes / apparel

ON CONFLICT (domain)
DO UPDATE SET
    tier           = EXCLUDED.tier,
    requires_proxy = EXCLUDED.requires_proxy,
    target_country = EXCLUDED.target_country,
    is_active      = COALESCE(supported_retailers.is_active, TRUE);
