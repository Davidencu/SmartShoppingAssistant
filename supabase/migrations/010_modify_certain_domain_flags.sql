UPDATE supported_retailers
SET requires_proxy = TRUE
WHERE domain IN (
    -- The TradeInn Network (Already discussed, but good to include in the master patch)
    'evomag.ro', 'tradeinn.com', 'bikeinn.com', 'runnerinn.com', 'swiminn.com',
    
    -- Decathlon Global (DataDome protected)
    'decathlon.ro', 'decathlon.com', 'decathlon.de', 'decathlon.fr', 
    'decathlon.it', 'decathlon.es', 'decathlon.pl', 'decathlon.nl', 
    'decathlon.be', 'decathlon.co.uk', 'decathlon.se', 'decathlon.cz', 
    'decathlon.hu', 'decathlon.at', 'decathlon.pt',
    
    -- Heavy US Enterprise WAFs
    'wayfair.com', 'gamestop.com', 'zappos.com', 'rakuten.com', 'rei.com', 'chewy.com',
    
    -- UK Anti-Scalper Tech WAFs
    'scan.co.uk', 'overclockers.co.uk'
);