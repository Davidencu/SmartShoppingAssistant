-- Add plan columns to profiles.
-- Run after 001_initial_schema.sql.

ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS plan             TEXT    NOT NULL DEFAULT 'free'
        CHECK (plan IN ('free', 'pro')),
    ADD COLUMN IF NOT EXISTS checkout_credits INTEGER NOT NULL DEFAULT 2;

