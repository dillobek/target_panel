-- Har ishga tushishda bajariladi (idempotent). Yangi o'zgarishlar shu faylga qo'shiladi.

CREATE TABLE IF NOT EXISTS settings (
  key        TEXT PRIMARY KEY,
  value      TEXT,
  is_secret  BOOLEAN NOT NULL DEFAULT false,   -- true: value AES-GCM bilan shifrlangan
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analyses (
  id         BIGSERIAL PRIMARY KEY,
  client_id  INT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL DEFAULT 'daily',   -- daily | manual | question
  question   TEXT,
  findings   JSONB NOT NULL DEFAULT '[]',     -- qoidalar topgan signallar
  ai_json    JSONB,                           -- AI tuzilgan javobi
  ai_text    TEXT,                            -- AI matni (savol-javob yoki zaxira)
  model      TEXT,
  error      TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS analyses_client ON analyses (client_id, id DESC);

ALTER TABLE clients ADD COLUMN IF NOT EXISTS ai_to_group BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS result JSONB;

INSERT INTO settings (key, value) VALUES
  ('ai_enabled', 'true'),
  ('ai_model', 'claude-sonnet-5-5'),
  ('diagnostics_time', '08:30')
ON CONFLICT (key) DO NOTHING;
