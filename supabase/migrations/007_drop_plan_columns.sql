-- Remove plan/billing columns added by 002_plan_schema.sql.
-- Lemon Squeezy billing and the plan gate have been removed from the product.
ALTER TABLE public.profiles
    DROP COLUMN IF EXISTS plan,
    DROP COLUMN IF EXISTS checkout_credits;
