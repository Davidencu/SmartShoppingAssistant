-- profiles: extends auth.users with application-specific fields
CREATE TABLE IF NOT EXISTS public.profiles (
    id             UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email          TEXT UNIQUE NOT NULL,
    phone          TEXT NOT NULL,
    street_address TEXT NOT NULL,
    city           TEXT NOT NULL,
    state          TEXT,
    postal_code    TEXT NOT NULL,
    country        TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- passkeys: stores WebAuthn credentials per user
CREATE TABLE IF NOT EXISTS public.passkeys (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    email         TEXT NOT NULL,
    credential_id TEXT UNIQUE NOT NULL,
    public_key    TEXT NOT NULL,
    sign_count    INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- RLS: all writes go through the backend service role key only
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.passkeys ENABLE ROW LEVEL SECURITY;
