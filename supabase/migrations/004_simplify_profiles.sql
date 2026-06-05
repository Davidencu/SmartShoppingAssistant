-- Drop address columns that are no longer collected.
-- Only city + country are stored for location-aware search; full address
-- is not needed since automated checkout has been removed from the product.
ALTER TABLE profiles
  DROP COLUMN IF EXISTS street_address,
  DROP COLUMN IF EXISTS postal_code;
