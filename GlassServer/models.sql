-- GlassServer/models.sql

-- == SALES (from Gumroad webhook) ==
CREATE TABLE IF NOT EXISTS sales (
  sale_id TEXT PRIMARY KEY,
  seller_id TEXT,
  product_id TEXT,
  buyer_email TEXT,
  refunded INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  raw_payload TEXT
);

CREATE INDEX IF NOT EXISTS idx_sales_created_at  ON sales (created_at);
CREATE INDEX IF NOT EXISTS idx_sales_buyer_email ON sales (buyer_email);
CREATE INDEX IF NOT EXISTS idx_sales_product_id  ON sales (product_id);

-- == DEVICES / TIERS ==
CREATE TABLE IF NOT EXISTS devices (
  hwid TEXT PRIMARY KEY,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS device_tiers (
  hwid TEXT PRIMARY KEY,
  tier TEXT NOT NULL CHECK (tier IN ('free','referral','pro')),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- == REFERRALS ==
CREATE TABLE IF NOT EXISTS referrals (
  code TEXT PRIMARY KEY,
  referrer_hwid TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  successful_activations INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ref_clicks (
  id BIGSERIAL PRIMARY KEY,
  code TEXT NOT NULL,
  ip TEXT,
  user_agent TEXT,
  clicked_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ref_downloads (
  id BIGSERIAL PRIMARY KEY,
  code TEXT,
  ip TEXT,
  user_agent TEXT,
  downloaded_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS activations (
  id BIGSERIAL PRIMARY KEY,
  hwid TEXT NOT NULL,
  ip TEXT,
  user_agent TEXT,
  matched_code TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- == LICENSES (optional key-based) ==
CREATE TABLE IF NOT EXISTS licenses (
  license_key TEXT PRIMARY KEY,
  buyer_email TEXT,
  hwid TEXT,
  tier TEXT NOT NULL CHECK (tier IN ('pro')),
  issued_at TIMESTAMP DEFAULT NOW()
);

-- Helpful referral indexes
CREATE INDEX IF NOT EXISTS idx_clicks_code_time ON ref_clicks (code, clicked_at DESC);
CREATE INDEX IF NOT EXISTS idx_dl_code_time    ON ref_downloads (code, downloaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_act_hwid_time   ON activations (hwid, created_at DESC);

-- No-refunds: ability to revoke on refund/chargeback
ALTER TABLE licenses
  ADD COLUMN IF NOT EXISTS revoked INTEGER DEFAULT 0; -- 0=false, 1=true
