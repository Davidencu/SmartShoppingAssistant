-- Migration: retailer categories
-- Adds a `category` column so the search pipeline only queries shops that sell the
-- kind of product the user asked for (e.g. a fridge search no longer hits notino.ro).
--
-- category is an array because many shops cover several categories
-- (altex.ro = electronics + appliances). 'general' = marketplace / department store /
-- hypermarket that sells everything — these always match.
--
-- Selection in retailers_service: country AND tier AND
--   (category && <requested categories>  OR  'general' = ANY(category)).
-- Rows not classified below keep the default '{general}', so they behave exactly
-- as before (always eligible).

ALTER TABLE supported_retailers
ADD COLUMN IF NOT EXISTS category TEXT[] NOT NULL DEFAULT '{general}';

ALTER TABLE supported_retailers
DROP CONSTRAINT IF EXISTS valid_category;

ALTER TABLE supported_retailers
ADD CONSTRAINT valid_category CHECK (
    cardinality(category) > 0
    AND category <@ ARRAY[
        'general', 'electronics', 'appliances', 'gaming', 'fashion', 'beauty',
        'health', 'sports', 'cycling', 'outdoor', 'books', 'home', 'diy',
        'pets', 'toys', 'baby', 'music', 'auto'
    ]::TEXT[]
);

CREATE INDEX IF NOT EXISTS idx_supported_retailers_category
    ON supported_retailers USING GIN (category);

-- ─────────────────────────────────────────────────────────────────────────────
-- CLASSIFY EXISTING RETAILERS
-- Anything not listed stays '{general}'.
-- ─────────────────────────────────────────────────────────────────────────────

-- Consumer-electronics chains that also sell large/small appliances
UPDATE supported_retailers SET category = '{electronics,appliances}' WHERE domain IN (
    'altex.ro', 'flanco.ro', 'mediagalaxy.ro', 'cel.ro',
    'mediamarkt.de', 'saturn.de', 'mediamarkt.es', 'mediamarkt.nl', 'mediamarkt.be',
    'mediamarkt.gr', 'mediamarkt.at', 'saturn.at', 'mediamarkt.ch',
    'darty.com', 'boulanger.com',
    'mediaworld.it', 'unieuro.it', 'euronics.it', 'euronics.de', 'euronics.hu', 'trony.it',
    'coolblue.nl', 'coolblue.be', 'vandenborre.be', 'krefel.be', 'bcc.nl',
    'currys.co.uk', 'currys.ie', 'ao.com', 'powercity.ie',
    'bestbuy.com', 'bestbuy.ca',
    'elgiganten.se', 'elgiganten.dk', 'elkjop.no', 'power.no', 'power.fi', 'gigantti.fi',
    'verkkokauppa.com', 'worten.pt', 'datart.cz', 'nay.sk', 'extreme-digital.hu',
    'kotsovolos.gr', 'euro.com.pl', 'mediaexpert.pl', 'microspot.ch',
    'jbhifi.com.au', 'jbhifi.co.nz', 'croma.com', 'reliancedigital.in', 'vijaysales.com',
    'fastshop.com.br', 'samsung.com'
);

UPDATE supported_retailers SET category = '{electronics,appliances,home}' WHERE domain IN (
    'harveynorman.com.au', 'harveynorman.co.nz', 'casasbahia.com.br'
);

-- IT / computer / tech specialists
UPDATE supported_retailers SET category = '{electronics}' WHERE domain IN (
    'pcgarage.ro', 'evomag.ro', 'quickmobile.ro',
    'alternate.de', 'notebooksbilliger.de', 'cyberport.de', 'cyberport.at', 'mediaexpert.de',
    'mindfactory.de', 'reichelt.de', 'conrad.de', 'voelkner.de', 'computeruniverse.net',
    'ldlc.com', 'topachat.com', 'rueducommerce.fr', 'materiel.net',
    'pccomponentes.com', 'morele.net', 'x-kom.pl',
    'scan.co.uk', 'ebuyer.com', 'overclockers.co.uk', 'laptopsdirect.co.uk', 'box.co.uk',
    'newegg.com', 'bhphotovideo.com', 'adorama.com', 'microcenter.com',
    'komplett.se', 'komplett.no', 'komplett.dk', 'inet.se', 'proshop.no', 'proshop.dk',
    'czc.cz', 'centralpoint.nl', 'megekko.nl', 'digitec.ch', 'steg-electronics.ch',
    'canadacomputers.com', 'memoryexpress.com', 'staples.ca', 'officeworks.com.au',
    'kabum.com.br', 'pbtech.co.nz', 'plaisio.gr', 'incredible.co.za', 'eprice.it',
    'apple.com', 'casetify.com', 'dbrand.com', 'nomadgoods.com'
);

UPDATE supported_retailers SET category = '{electronics,gaming}' WHERE domain IN (
    'webhallen.com'
);

UPDATE supported_retailers SET category = '{electronics,books,gaming}' WHERE domain IN (
    'fnac.fr', 'fnac.es', 'fnac.pt', 'public.gr'
);

UPDATE supported_retailers SET category = '{electronics,music}' WHERE domain IN (
    'richer-sounds.com'
);

-- Video games
UPDATE supported_retailers SET category = '{gaming}' WHERE domain IN (
    'game.es', 'game.co.uk', 'gamestop.com'
);

UPDATE supported_retailers SET category = '{gaming,music,books}' WHERE domain IN (
    'hmv.com', 'mightyape.com'
);

-- Fashion / footwear / accessories
UPDATE supported_retailers SET category = '{fashion}' WHERE domain IN (
    'answear.ro', 'fashion-days.ro', 'watchshop.ro',
    'zalando.de', 'zalando.fr', 'zalando.com', 'about-you.de', 'aboutyou.com',
    'asos.com', 'hm.com', 'uniqlo.com', 'zara.com', 'spartoo.it', 'answear.com',
    'halfprice.com', 'nelly.com', 'myntra.com', 'zappos.com',
    'allbirds.com', 'skims.com', 'fashionnova.com', 'ohpolly.com', 'tentree.com',
    'taylorstitch.com', 'bombas.com'
);

UPDATE supported_retailers SET category = '{fashion,sports}' WHERE domain IN (
    'nike.com', 'adidas.com', 'footlocker.com', 'gymshark.com', 'vuoriclothing.com',
    'sportsdirect.com'
);

UPDATE supported_retailers SET category = '{fashion,home}' WHERE domain IN (
    'simons.ca', 'urbanoutfitters.com', 'anthropologie.com', 'baur.de'
);

UPDATE supported_retailers SET category = '{fashion,beauty,home}' WHERE domain IN (
    'macys.com', 'nordstrom.com', 'kohls.com'
);

UPDATE supported_retailers SET category = '{fashion,outdoor}' WHERE domain IN (
    'patagonia.com', 'thenorthface.com'
);

-- Beauty / cosmetics
UPDATE supported_retailers SET category = '{beauty}' WHERE domain IN (
    'notino.ro', 'notino.cz', 'notino.sk', 'notino.hu', 'notino.com',
    'douglas.de', 'nykaa.com',
    'kyliecosmetics.com', 'colourpop.com', 'fentybeauty.com', 'morphe.com', 'beardbrand.com'
);

UPDATE supported_retailers SET category = '{beauty,health}' WHERE domain IN (
    'bipa.at'
);

-- Health / supplements
UPDATE supported_retailers SET category = '{health}' WHERE domain IN (
    'iherb.com', 'bulletproof.com'
);

UPDATE supported_retailers SET category = '{health,sports}' WHERE domain IN (
    'myprotein.com'
);

-- Sports (multi-sport chains)
UPDATE supported_retailers SET category = '{sports,outdoor,cycling}' WHERE domain IN (
    'decathlon.ro', 'decathlon.com', 'decathlon.de', 'decathlon.fr', 'decathlon.it',
    'decathlon.es', 'decathlon.pl', 'decathlon.nl', 'decathlon.be', 'decathlon.co.uk',
    'decathlon.se', 'decathlon.cz', 'decathlon.hu', 'decathlon.at', 'decathlon.pt',
    'tradeinn.com', 'rei.com'
);

UPDATE supported_retailers SET category = '{sports,fashion}' WHERE domain IN (
    'sportguru.ro', 'hervis.ro', 'intersport.ro', 'sportisimo.ro', 'sportisimo.cz',
    'sportisimo.sk', 'sprinter.es', 'rebel.com.au', 'sportchek.com'
);

UPDATE supported_retailers SET category = '{sports,outdoor}' WHERE domain IN (
    'dickssportinggoods.com', 'academy.com'
);

UPDATE supported_retailers SET category = '{sports}' WHERE domain IN (
    'tennispoint.com', 'runnerinn.com', 'swiminn.com'
);

-- Cycling
UPDATE supported_retailers SET category = '{cycling}' WHERE domain IN (
    'rose-bikes.com', 'fahrrad.de', 'bike-discount.de', 'bikeinn.com',
    'wiggle.com', 'chainreactioncycles.com', 'bike24.com', 'probikekit.com'
);

UPDATE supported_retailers SET category = '{cycling,outdoor}' WHERE domain IN (
    'alltricks.fr'
);

UPDATE supported_retailers SET category = '{cycling,auto}' WHERE domain IN (
    'halfords.com'
);

-- Outdoor / camping
UPDATE supported_retailers SET category = '{outdoor}' WHERE domain IN (
    'backcountry.com', 'cabelas.com', 'mec.ca', 'sail.ca', 'anaconda.com.au',
    'bcf.com.au', 'cotopaxi.com'
);

-- Books
UPDATE supported_retailers SET category = '{books}' WHERE domain IN (
    'libris.ro', 'thalia.de', 'alapage.com', 'decitre.fr', 'ibs.it',
    'waterstones.com', 'thriftbooks.com', 'booksamillion.com', 'libro.at'
);

UPDATE supported_retailers SET category = '{books,toys,music}' WHERE domain IN (
    'cultura.com'
);

-- Home / furniture
UPDATE supported_retailers SET category = '{home}' WHERE domain IN (
    'home24.de', 'wayfair.com', 'overstock.com', 'crateandbarrel.com', 'fonq.nl',
    'dunelm.com', 'brooklinen.com', 'ruggable.com', 'ikea.com'
);

UPDATE supported_retailers SET category = '{home,appliances}' WHERE domain IN (
    'williams-sonoma.com'
);

UPDATE supported_retailers SET category = '{home,diy}' WHERE domain IN (
    'therange.co.uk'
);

-- DIY / tools / garden
UPDATE supported_retailers SET category = '{diy,home}' WHERE domain IN (
    'manomano.fr', 'manomano.it', 'manomano.es', 'manomano.pt', 'manomano.com',
    'screwfix.com', 'toolstation.com'
);

UPDATE supported_retailers SET category = '{diy,home,appliances}' WHERE domain IN (
    'dedeman.ro', 'homedepot.com', 'lowes.com'
);

-- Pets
UPDATE supported_retailers SET category = '{pets}' WHERE domain IN (
    'zooplus.ro', 'zooplus.de', 'zooplus.fr', 'zooplus.it', 'zooplus.es', 'zooplus.pl',
    'zooplus.nl', 'zooplus.be', 'zooplus.co.uk', 'zooplus.com',
    'chewy.com', 'petsmart.com', 'petco.com', 'petbarn.com.au'
);

-- Toys / baby
UPDATE supported_retailers SET category = '{toys,baby}' WHERE domain IN (
    'mytoys.de', 'firstcry.com'
);

UPDATE supported_retailers SET category = '{toys,gaming}' WHERE domain IN (
    'smythstoys.com'
);

-- Music instruments / audio
UPDATE supported_retailers SET category = '{music}' WHERE domain IN (
    'reverb.com', 'sweetwater.com', 'thomann.de', 'musiciansfriend.com'
);

-- Auto
UPDATE supported_retailers SET category = '{auto}' WHERE domain IN (
    'supercheapauto.com.au'
);

-- ─────────────────────────────────────────────────────────────────────────────
-- NEW RETAILERS (Romania)
-- requires_proxy defaults to FALSE; the scraper learns hostile domains at runtime
-- and persists them to hostile_domains, so no need to guess here.
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO supported_retailers (domain, target_country, requires_proxy, tier, category) VALUES

-- Electronics / IT / photo
('vexio.ro',             'RO', FALSE, 'niche',      '{electronics}'),
('itgalaxy.ro',          'RO', FALSE, 'niche',      '{electronics}'),
('f64.ro',               'RO', FALSE, 'niche',      '{electronics}'),
('avstore.ro',           'RO', FALSE, 'niche',      '{electronics,music}'),

-- Books
('bookzone.ro',          'RO', FALSE, 'niche',      '{books}'),
('librariadelfin.ro',    'RO', FALSE, 'niche',      '{books}'),

-- Beauty / pharmacy
('sephora.ro',           'RO', FALSE, 'niche',      '{beauty}'),
('douglas.ro',           'RO', FALSE, 'niche',      '{beauty}'),
('makeup.ro',            'RO', FALSE, 'niche',      '{beauty}'),
('drmax.ro',             'RO', FALSE, 'niche',      '{health,beauty}'),
('catena.ro',            'RO', FALSE, 'niche',      '{health,beauty}'),
('farmaciatei.ro',       'RO', FALSE, 'niche',      '{health,beauty}'),
('helpnet.ro',           'RO', FALSE, 'niche',      '{health,beauty}'),

-- Pets
('animax.ro',            'RO', FALSE, 'niche',      '{pets}'),
('petmart.ro',           'RO', FALSE, 'niche',      '{pets}'),

-- Toys / baby
('noriel.ro',            'RO', FALSE, 'niche',      '{toys,baby}'),
('nichiduta.ro',         'RO', FALSE, 'niche',      '{baby,toys}'),
('magazinuldejocuri.ro', 'RO', FALSE, 'niche',      '{toys,gaming}'),

-- Music instruments
('kytary.ro',            'RO', FALSE, 'niche',      '{music}'),

-- Fashion / footwear
('depurtat.ro',          'RO', FALSE, 'niche',      '{fashion}'),
('epantofi.ro',          'RO', FALSE, 'niche',      '{fashion}'),
('modivo.ro',            'RO', FALSE, 'niche',      '{fashion}'),
('aboutyou.ro',          'RO', FALSE, 'niche',      '{fashion}'),
('sportvision.ro',       'RO', FALSE, 'niche',      '{sports,fashion}'),

-- Home / furniture
('vivre.ro',             'RO', FALSE, 'niche',      '{home}'),
('jysk.ro',              'RO', FALSE, 'niche',      '{home}'),
('mobexpert.ro',         'RO', FALSE, 'niche',      '{home}'),

-- DIY / home improvement (large chains → mainstream)
('mathaus.ro',           'RO', FALSE, 'niche',      '{diy,home}'),
('leroymerlin.ro',       'RO', FALSE, 'mainstream', '{diy,home,appliances}'),
('hornbach.ro',          'RO', FALSE, 'mainstream', '{diy,home}'),
('bricodepot.ro',        'RO', FALSE, 'mainstream', '{diy,home}'),

-- Auto parts
('autodoc.ro',           'RO', FALSE, 'niche',      '{auto}'),
('pieseauto.ro',         'RO', FALSE, 'niche',      '{auto}')

ON CONFLICT (domain)
DO UPDATE SET
    category       = EXCLUDED.category,
    tier           = EXCLUDED.tier,
    target_country = EXCLUDED.target_country,
    is_active      = COALESCE(supported_retailers.is_active, TRUE);
