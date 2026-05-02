-- profiles extends auth.users with display name + phone
CREATE TABLE IF NOT EXISTS public.profiles (
  id          UUID        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  full_name   TEXT        NOT NULL,
  phone       TEXT        NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- shipping addresses (one per user for MVP, default flag for future multi-address)
CREATE TABLE IF NOT EXISTS public.addresses (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  recipient_name  TEXT        NOT NULL,
  street          TEXT        NOT NULL,
  city            TEXT        NOT NULL,
  state           TEXT,
  country         TEXT        NOT NULL DEFAULT 'RO',
  zip_code        TEXT        NOT NULL,
  is_default      BOOLEAN     NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- master ledger wallet (one per user)
CREATE TABLE IF NOT EXISTS public.wallets (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID        NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
  balance_cents INTEGER     NOT NULL DEFAULT 0 CHECK (balance_cents >= 0),
  frozen_cents  INTEGER     NOT NULL DEFAULT 0 CHECK (frozen_cents >= 0),
  currency      TEXT        NOT NULL DEFAULT 'USD',
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- immutable ledger — never UPDATE, only INSERT
CREATE TABLE IF NOT EXISTS public.wallet_transactions (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  wallet_id     UUID        NOT NULL REFERENCES public.wallets(id) ON DELETE RESTRICT,
  type          TEXT        NOT NULL CHECK (type IN ('TOPUP', 'FREEZE', 'DEDUCT', 'REFUND')),
  amount_cents  INTEGER     NOT NULL CHECK (amount_cents > 0),
  reference_id  TEXT,
  order_id      UUID,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Row Level Security ────────────────────────────────────────────────────────
ALTER TABLE public.profiles            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.addresses           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wallets             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wallet_transactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "profiles_owner"  ON public.profiles
  FOR ALL USING (auth.uid() = id);

CREATE POLICY "addresses_owner" ON public.addresses
  FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "wallets_owner"   ON public.wallets
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "transactions_owner" ON public.wallet_transactions
  FOR SELECT USING (
    wallet_id IN (SELECT id FROM public.wallets WHERE user_id = auth.uid())
  );

-- ── Indexes ──────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_addresses_user_id          ON public.addresses(user_id);
CREATE INDEX IF NOT EXISTS idx_wallets_user_id            ON public.wallets(user_id);
CREATE INDEX IF NOT EXISTS idx_txn_wallet_id              ON public.wallet_transactions(wallet_id);
CREATE INDEX IF NOT EXISTS idx_txn_created_at             ON public.wallet_transactions(created_at DESC);

-- ── Trigger: auto-create wallet on sign-up ────────────────────────────────────
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  INSERT INTO public.wallets (user_id) VALUES (NEW.id);
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ── Atomic wallet credit (avoids race conditions) ────────────────────────────
CREATE OR REPLACE FUNCTION public.credit_wallet(
  p_user_id      UUID,
  p_amount_cents INTEGER,
  p_reference_id TEXT
) RETURNS SETOF public.wallet_transactions LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  v_wallet_id UUID;
BEGIN
  SELECT id INTO v_wallet_id
  FROM public.wallets
  WHERE user_id = p_user_id
  FOR UPDATE;

  UPDATE public.wallets
  SET balance_cents = balance_cents + p_amount_cents,
      updated_at    = NOW()
  WHERE id = v_wallet_id;

  RETURN QUERY
  INSERT INTO public.wallet_transactions (wallet_id, type, amount_cents, reference_id)
  VALUES (v_wallet_id, 'TOPUP', p_amount_cents, p_reference_id)
  RETURNING *;
END;
$$;
