-- Migration: expand niche retailer coverage across all supported markets
-- Adds mid-market and specialty retailers spanning fashion, books, beauty,
-- DIY, cycling, outdoor, electronics accessories, gaming, pet care, and more.
-- These sites carry lighter anti-bot measures and richer JSON-LD than the
-- mainstream platforms, so they should be searched first by the pipeline.

-- ── Re-classify existing misclassified domains ────────────────────────────────
-- decathlon.ro has good JSON-LD and no heavy WAF — the pipeline was wastefully
-- routing it through the residential-proxy path on the mainstream fallback.
UPDATE supported_retailers
SET tier = 'niche', requires_proxy = FALSE
WHERE domain IN ('decathlon.ro', 'decathlon.com', 'sportguru.ro');

INSERT INTO supported_retailers (domain, target_country, requires_proxy, tier) VALUES

-- ── Romania ───────────────────────────────────────────────────────────────────
('notino.ro',              'RO', FALSE, 'niche'),   -- beauty / cosmetics specialty
('answear.ro',             'RO', FALSE, 'niche'),   -- fashion / clothing
('fashion-days.ro',        'RO', FALSE, 'niche'),   -- fashion flash sales
('libris.ro',              'RO', FALSE, 'niche'),   -- books / culture
('intersport.ro',          'RO', FALSE, 'niche'),   -- multi-sport chain
('zooplus.ro',             'RO', FALSE, 'niche'),   -- pet supplies specialty
('sportisimo.ro',          'RO', FALSE, 'niche'),   -- CEE sports chain

-- ── Germany ───────────────────────────────────────────────────────────────────
('galaxus.de',             'DE', FALSE, 'niche'),   -- Digitec Galaxus marketplace (best JSON-LD in EU)
('conrad.de',              'DE', FALSE, 'niche'),   -- electronics / components
('voelkner.de',            'DE', FALSE, 'niche'),   -- electronics / components
('thalia.de',              'DE', FALSE, 'niche'),   -- books / stationery / media
('about-you.de',           'DE', FALSE, 'niche'),   -- fashion (Hamburg)
('home24.de',              'DE', FALSE, 'niche'),   -- home furnishings
('computeruniverse.net',   'DE', FALSE, 'niche'),   -- IT components
('rose-bikes.com',         'DE', FALSE, 'niche'),   -- cycling specialty
('fahrrad.de',             'DE', FALSE, 'niche'),   -- cycling specialty
('bike-discount.de',       'DE', FALSE, 'niche'),   -- cycling discount
('decathlon.de',           'DE', FALSE, 'niche'),   -- sports / outdoor (DE storefront)
('douglas.de',             'DE', FALSE, 'niche'),   -- beauty / perfumery
('zooplus.de',             'DE', FALSE, 'niche'),   -- pet supplies
('mytoys.de',              'DE', FALSE, 'niche'),   -- toys / children
('baur.de',                'DE', FALSE, 'niche'),   -- fashion / home

-- ── France ────────────────────────────────────────────────────────────────────
('materiel.net',           'FR', FALSE, 'niche'),   -- IT components
('manomano.fr',            'FR', FALSE, 'niche'),   -- DIY / garden / home
('cultura.com',            'FR', FALSE, 'niche'),   -- books / art / hobbies
('alltricks.fr',           'FR', FALSE, 'niche'),   -- cycling / outdoor specialty
('decathlon.fr',           'FR', FALSE, 'niche'),   -- sports / outdoor (FR storefront)
('veepee.fr',              'FR', FALSE, 'niche'),   -- flash sales
('rakuten.fr',             'FR', FALSE, 'niche'),   -- marketplace
('zooplus.fr',             'FR', FALSE, 'niche'),   -- pet supplies
('showroomprive.com',      'FR', FALSE, 'niche'),   -- members-only flash sales
('alapage.com',            'FR', FALSE, 'niche'),   -- books / culture
('decitre.fr',             'FR', FALSE, 'niche'),   -- books specialty

-- ── Italy ─────────────────────────────────────────────────────────────────────
('ibs.it',                 'IT', FALSE, 'niche'),   -- books / culture
('eprice.it',              'IT', FALSE, 'niche'),   -- electronics marketplace
('manomano.it',            'IT', FALSE, 'niche'),   -- DIY / home improvement
('decathlon.it',           'IT', FALSE, 'niche'),   -- sports / outdoor (IT storefront)
('spartoo.it',             'IT', FALSE, 'niche'),   -- shoes / fashion
('zooplus.it',             'IT', FALSE, 'niche'),   -- pet supplies
('unieuro.it',             'IT', FALSE, 'niche'),   -- consumer electronics chain

-- ── Spain ─────────────────────────────────────────────────────────────────────
('elcorteingles.es',       'ES', TRUE,  'mainstream'), -- major department store (heavy JS/WAF)
('decathlon.es',           'ES', FALSE, 'niche'),   -- sports / outdoor (ES storefront)
('manomano.es',            'ES', FALSE, 'niche'),   -- DIY / home improvement
('sprinter.es',            'ES', FALSE, 'niche'),   -- sports chain
('bikeinn.com',            'ES', FALSE, 'niche'),   -- cycling specialty (TradeInn)
('game.es',                'ES', FALSE, 'niche'),   -- video games specialty
('zooplus.es',             'ES', FALSE, 'niche'),   -- pet supplies
('carrefour.es',           'ES', TRUE,  'mainstream'), -- hypermarket (heavy WAF)

-- ── Poland ────────────────────────────────────────────────────────────────────
('empik.com',              'PL', FALSE, 'niche'),   -- books / culture / general
('decathlon.pl',           'PL', FALSE, 'niche'),   -- sports / outdoor (PL storefront)
('answear.com',            'PL', FALSE, 'niche'),   -- fashion (Polish origin)
('euro.com.pl',            'PL', FALSE, 'niche'),   -- consumer electronics
('zooplus.pl',             'PL', FALSE, 'niche'),   -- pet supplies
('halfprice.com',          'PL', FALSE, 'niche'),   -- fashion / discount (CEE chain)

-- ── Netherlands ───────────────────────────────────────────────────────────────
('wehkamp.nl',             'NL', FALSE, 'niche'),   -- fashion / general
('bcc.nl',                 'NL', FALSE, 'niche'),   -- consumer electronics chain
('centralpoint.nl',        'NL', FALSE, 'niche'),   -- IT specialty
('megekko.nl',             'NL', FALSE, 'niche'),   -- PC components
('fonq.nl',                'NL', FALSE, 'niche'),   -- home design / lifestyle
('zooplus.nl',             'NL', FALSE, 'niche'),   -- pet supplies
('decathlon.nl',           'NL', FALSE, 'niche'),   -- sports / outdoor (NL storefront)
('bol.be',                 'NL', TRUE,  'mainstream'), -- already in BE but NL uses it too

-- ── Belgium ───────────────────────────────────────────────────────────────────
('vandenborre.be',         'BE', FALSE, 'niche'),   -- consumer electronics (major Belgian chain)
('krefel.be',              'BE', FALSE, 'niche'),   -- consumer electronics
('decathlon.be',           'BE', FALSE, 'niche'),   -- sports / outdoor (BE storefront)
('zooplus.be',             'BE', FALSE, 'niche'),   -- pet supplies

-- ── United Kingdom ────────────────────────────────────────────────────────────
('halfords.com',           'GB', FALSE, 'niche'),   -- bikes / auto accessories
('sportsdirect.com',       'GB', FALSE, 'niche'),   -- sports / fashion discount
('screwfix.com',           'GB', FALSE, 'niche'),   -- tools / DIY trade
('ao.com',                 'GB', FALSE, 'niche'),   -- appliances specialty
('box.co.uk',              'GB', FALSE, 'niche'),   -- consumer tech
('dunelm.com',             'GB', FALSE, 'niche'),   -- home furnishings
('therange.co.uk',         'GB', FALSE, 'niche'),   -- home / crafts / leisure
('decathlon.co.uk',        'GB', FALSE, 'niche'),   -- sports / outdoor (UK storefront)
('waterstones.com',        'GB', FALSE, 'niche'),   -- books / stationery
('hmv.com',                'GB', FALSE, 'niche'),   -- music / film / gaming
('zooplus.co.uk',          'GB', FALSE, 'niche'),   -- pet supplies
('smythstoys.com',         'GB', FALSE, 'niche'),   -- toys / games chain
('game.co.uk',             'GB', FALSE, 'niche'),   -- video games specialty
('richer-sounds.com',      'GB', FALSE, 'niche'),   -- audio / AV specialty
('toolstation.com',        'GB', FALSE, 'niche'),   -- tools / building supplies

-- ── United States ─────────────────────────────────────────────────────────────
('dickssportinggoods.com', 'US', TRUE,  'niche'),   -- sports (some bot protection)
('patagonia.com',          'US', FALSE, 'niche'),   -- outdoor / sustainability brand
('thenorthface.com',       'US', TRUE,  'niche'),   -- outdoor brand
('footlocker.com',         'US', TRUE,  'niche'),   -- sports / sneakers
('academy.com',            'US', FALSE, 'niche'),   -- sports / outdoor chain
('cabelas.com',            'US', FALSE, 'niche'),   -- outdoor / hunting / fishing
('williams-sonoma.com',    'US', FALSE, 'niche'),   -- kitchen / home
('crateandbarrel.com',     'US', FALSE, 'niche'),   -- home furnishings
('urbanoutfitters.com',    'US', TRUE,  'niche'),   -- fashion / lifestyle
('anthropologie.com',      'US', TRUE,  'niche'),   -- fashion / home décor
('gamestop.com',           'US', FALSE, 'niche'),   -- video games specialty
('petsmart.com',           'US', FALSE, 'niche'),   -- pet supplies chain
('petco.com',              'US', FALSE, 'niche'),   -- pet supplies chain
('thriftbooks.com',        'US', FALSE, 'niche'),   -- used / discount books
('booksamillion.com',      'US', FALSE, 'niche'),   -- books / stationery
('homedepot.com',          'US', TRUE,  'mainstream'), -- DIY / home improvement (heavy WAF)
('lowes.com',              'US', TRUE,  'mainstream'), -- DIY / home improvement
('kohls.com',              'US', TRUE,  'mainstream'), -- department store

-- ── Sweden ────────────────────────────────────────────────────────────────────
('inet.se',                'SE', FALSE, 'niche'),   -- IT components specialty
('nelly.com',              'SE', FALSE, 'niche'),   -- fashion (Nordic)
('cdon.com',               'SE', FALSE, 'niche'),   -- Nordic marketplace
('decathlon.se',           'SE', FALSE, 'niche'),   -- sports / outdoor (SE storefront)

-- ── Norway ────────────────────────────────────────────────────────────────────
('proshop.no',             'NO', FALSE, 'niche'),   -- IT specialty

-- ── Denmark ───────────────────────────────────────────────────────────────────
('proshop.dk',             'DK', FALSE, 'niche'),   -- IT specialty

-- ── Portugal ──────────────────────────────────────────────────────────────────
('decathlon.pt',           'PT', FALSE, 'niche'),   -- sports / outdoor (PT storefront)
('manomano.pt',            'PT', FALSE, 'niche'),   -- DIY / home improvement

-- ── Czech Republic ────────────────────────────────────────────────────────────
('sportisimo.cz',          'CZ', FALSE, 'niche'),   -- sports chain (Czech origin)
('mall.cz',                'CZ', FALSE, 'niche'),   -- marketplace
('decathlon.cz',           'CZ', FALSE, 'niche'),   -- sports / outdoor (CZ storefront)
('notino.cz',              'CZ', FALSE, 'niche'),   -- beauty / cosmetics (Czech origin)

-- ── Slovakia ──────────────────────────────────────────────────────────────────
('sportisimo.sk',          'SK', FALSE, 'niche'),   -- sports chain
('nay.sk',                 'SK', FALSE, 'niche'),   -- consumer electronics (Slovak)
('notino.sk',              'SK', FALSE, 'niche'),   -- beauty / cosmetics

-- ── Hungary ───────────────────────────────────────────────────────────────────
('euronics.hu',            'HU', FALSE, 'niche'),   -- consumer electronics
('notino.hu',              'HU', FALSE, 'niche'),   -- beauty / cosmetics
('decathlon.hu',           'HU', FALSE, 'niche'),   -- sports / outdoor (HU storefront)

-- ── Greece ────────────────────────────────────────────────────────────────────
('kotsovolos.gr',          'GR', FALSE, 'niche'),   -- consumer electronics (Greek chain)
('plaisio.gr',             'GR', FALSE, 'niche'),   -- tech / office / stationery

-- ── Austria ───────────────────────────────────────────────────────────────────
('libro.at',               'AT', FALSE, 'niche'),   -- books / stationery / hobbies
('bipa.at',                'AT', FALSE, 'niche'),   -- beauty / drugstore
('decathlon.at',           'AT', FALSE, 'niche'),   -- sports / outdoor (AT storefront)

-- ── Switzerland ───────────────────────────────────────────────────────────────
('microspot.ch',           'CH', FALSE, 'niche'),   -- electronics specialty
('steg-electronics.ch',    'CH', FALSE, 'niche'),   -- IT components specialty

-- ── Australia ─────────────────────────────────────────────────────────────────
('kmart.com.au',           'AU', FALSE, 'niche'),   -- general retail / home
('myer.com.au',            'AU', FALSE, 'niche'),   -- department store
('rebel.com.au',           'AU', FALSE, 'niche'),   -- sports specialty
('anaconda.com.au',        'AU', FALSE, 'niche'),   -- outdoor / camping
('catch.com.au',           'AU', FALSE, 'niche'),   -- marketplace / deals
('petbarn.com.au',         'AU', FALSE, 'niche'),   -- pet supplies
('supercheapauto.com.au',  'AU', FALSE, 'niche'),   -- auto parts / accessories
('bcf.com.au',             'AU', FALSE, 'niche'),   -- boating / camping / fishing

-- ── Canada ────────────────────────────────────────────────────────────────────
('memoryexpress.com',      'CA', FALSE, 'niche'),   -- IT components specialty
('sportchek.com',          'CA', FALSE, 'niche'),   -- sports chain
('mec.ca',                 'CA', FALSE, 'niche'),   -- Mountain Equipment Company (outdoor co-op)
('sail.ca',                'CA', FALSE, 'niche'),   -- outdoor specialty
('simons.ca',              'CA', FALSE, 'niche'),   -- fashion / home

-- ── India ─────────────────────────────────────────────────────────────────────
('tatacliq.com',           'IN', FALSE, 'niche'),   -- Tata marketplace
('myntra.com',             'IN', FALSE, 'niche'),   -- fashion
('nykaa.com',              'IN', FALSE, 'niche'),   -- beauty / wellness
('vijaysales.com',         'IN', FALSE, 'niche'),   -- consumer electronics (chain)
('firstcry.com',           'IN', FALSE, 'niche'),   -- baby / kids specialty

-- ── Brazil ────────────────────────────────────────────────────────────────────
('magazineluiza.com.br',   'BR', TRUE,  'mainstream'), -- Magalu, largest BR retailer (heavy WAF)
('kabum.com.br',           'BR', FALSE, 'niche'),   -- IT / components specialty
('fastshop.com.br',        'BR', FALSE, 'niche'),   -- consumer electronics specialty

-- ── South Africa ──────────────────────────────────────────────────────────────
('makro.co.za',            'ZA', FALSE, 'niche'),   -- wholesale / bulk retail
('incredible.co.za',       'ZA', FALSE, 'niche'),   -- consumer electronics (Incredible Connection)
('onedayonly.co.za',       'ZA', FALSE, 'niche'),   -- daily deals

-- ── Ireland ───────────────────────────────────────────────────────────────────
('powercity.ie',           'IE', FALSE, 'niche'),   -- consumer electronics (Irish)

-- ── New Zealand ───────────────────────────────────────────────────────────────
('pbtech.co.nz',           'NZ', FALSE, 'niche'),   -- IT components specialty
('mightyape.com',          'NZ', FALSE, 'niche'),   -- games / entertainment / general

-- ── GLOBAL niche ──────────────────────────────────────────────────────────────
('wiggle.com',             'GLOBAL', FALSE, 'niche'),  -- cycling specialty (UK, ships EU-wide)
('chainreactioncycles.com','GLOBAL', FALSE, 'niche'),  -- cycling specialty (ships worldwide)
('bike24.com',             'GLOBAL', FALSE, 'niche'),  -- cycling / MTB (EU, DE-based)
('probikekit.com',         'GLOBAL', FALSE, 'niche'),  -- cycling (UK, ships worldwide)
('thomann.de',             'GLOBAL', FALSE, 'niche'),  -- music instruments (ships to 150+ countries)
('iherb.com',              'GLOBAL', FALSE, 'niche'),  -- health / supplements / natural products
('myprotein.com',          'GLOBAL', FALSE, 'niche'),  -- sports nutrition (ships worldwide)
('notino.com',             'GLOBAL', FALSE, 'niche'),  -- beauty / cosmetics (ships 30+ countries)
('tradeinn.com',           'GLOBAL', FALSE, 'niche'),  -- multi-sport: runninginn, swiminn, bikeinn (ships 180+)
('manomano.com',           'GLOBAL', FALSE, 'niche'),  -- DIY / garden / home (EU-wide)
('aboutyou.com',           'GLOBAL', FALSE, 'niche'),  -- fashion (European)
('privalia.com',           'GLOBAL', FALSE, 'niche'),  -- flash sales (IT, ES, BR, MX)
('runnerinn.com',          'GLOBAL', FALSE, 'niche'),  -- running / trail specialty (TradeInn)
('swiminn.com',            'GLOBAL', FALSE, 'niche'),  -- swimming specialty (TradeInn)
('tennispoint.com',        'GLOBAL', FALSE, 'niche'),  -- tennis specialty (ships EU+)
('musiciansfriend.com',    'GLOBAL', FALSE, 'niche'),  -- music instruments (US-focused, ships widely)
('zooplus.com',            'GLOBAL', FALSE, 'niche'),  -- pet supplies (EU-wide)

-- ── Shopify-powered DTC brands (GLOBAL niche) ─────────────────────────────────
-- Shopify/Shopify Plus outputs standardised JSON-LD on every storefront —
-- richer structured data than most mainstream retailers, no proxy needed.
-- ── Apparel / footwear ────────────────────────────────────────────────────────
('gymshark.com',           'GLOBAL', FALSE, 'niche'),  -- fitness apparel (UK)
('allbirds.com',           'GLOBAL', FALSE, 'niche'),  -- sustainable footwear (US)
('skims.com',              'GLOBAL', FALSE, 'niche'),  -- shapewear / loungewear (US)
('fashionnova.com',        'GLOBAL', FALSE, 'niche'),  -- fast fashion (US)
('ohpolly.com',            'GLOBAL', FALSE, 'niche'),  -- women's fashion (UK)
('vuoriclothing.com',      'GLOBAL', FALSE, 'niche'),  -- performance apparel (US)
('tentree.com',            'GLOBAL', FALSE, 'niche'),  -- sustainable apparel (CA)
('taylorstitch.com',       'GLOBAL', FALSE, 'niche'),  -- premium menswear (US)
-- ── Beauty / grooming ─────────────────────────────────────────────────────────
('kyliecosmetics.com',     'GLOBAL', FALSE, 'niche'),  -- cosmetics (US)
('colourpop.com',          'GLOBAL', FALSE, 'niche'),  -- affordable cosmetics (US)
('fentybeauty.com',        'GLOBAL', FALSE, 'niche'),  -- beauty / cosmetics (US)
('morphe.com',             'GLOBAL', FALSE, 'niche'),  -- makeup / brushes (US)
('beardbrand.com',         'GLOBAL', FALSE, 'niche'),  -- men's grooming specialty (US)
-- ── Home / lifestyle ──────────────────────────────────────────────────────────
('brooklinen.com',         'GLOBAL', FALSE, 'niche'),  -- premium bedding / home (US)
('ruggable.com',           'GLOBAL', FALSE, 'niche'),  -- washable rugs / home décor (US)
('bombas.com',             'GLOBAL', FALSE, 'niche'),  -- socks / underwear / basics (US)
-- ── Tech accessories ──────────────────────────────────────────────────────────
('casetify.com',           'GLOBAL', FALSE, 'niche'),  -- phone cases / accessories
('dbrand.com',             'GLOBAL', FALSE, 'niche'),  -- phone / laptop skins
('nomadgoods.com',         'GLOBAL', FALSE, 'niche'),  -- premium Apple accessories (US)
-- ── Outdoor / health ──────────────────────────────────────────────────────────
('cotopaxi.com',           'GLOBAL', FALSE, 'niche'),  -- outdoor / gear / lifestyle (US)
('bulletproof.com',        'GLOBAL', FALSE, 'niche')   -- health / performance supplements (US)

ON CONFLICT (domain)
DO UPDATE SET
    tier           = EXCLUDED.tier,
    requires_proxy = EXCLUDED.requires_proxy,
    target_country = EXCLUDED.target_country,
    is_active      = COALESCE(supported_retailers.is_active, TRUE);
