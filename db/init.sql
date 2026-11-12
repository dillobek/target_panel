-- Targetpanel ma'lumotlar bazasi sxemasi

CREATE TABLE connections (
  id              SERIAL PRIMARY KEY,
  platform        TEXT NOT NULL CHECK (platform IN ('meta', 'tg_ads')),
  name            TEXT NOT NULL,
  token_enc       TEXT NOT NULL,
  token_last4     TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'ok',        -- ok | error | pending_api
  last_error      TEXT,
  last_checked_at TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ad_accounts (
  id              SERIAL PRIMARY KEY,
  connection_id   INT NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
  platform        TEXT NOT NULL,
  external_id     TEXT NOT NULL,                     -- Meta: account_id (act_ siz)
  name            TEXT NOT NULL,
  currency        TEXT,
  account_status  INT,
  disable_reason  INT,
  spend_cap       NUMERIC,                           -- valyuta birligida
  amount_spent    NUMERIC,
  yesterday_spend NUMERIC,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (platform, external_id)
);

CREATE TABLE tg_groups (
  id           SERIAL PRIMARY KEY,
  chat_id      BIGINT NOT NULL UNIQUE,
  title        TEXT NOT NULL,
  bot_is_admin BOOLEAN NOT NULL DEFAULT false,
  active       BOOLEAN NOT NULL DEFAULT true,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE clients (
  id                SERIAL PRIMARY KEY,
  name              TEXT NOT NULL,
  result_type       TEXT NOT NULL DEFAULT 'messaging',  -- messaging | lead_form | lead_site | purchase
  group_id          INT REFERENCES tg_groups(id) ON DELETE SET NULL,
  report_daily      BOOLEAN NOT NULL DEFAULT true,
  report_daily_time TEXT NOT NULL DEFAULT '09:00',
  report_weekly     BOOLEAN NOT NULL DEFAULT true,
  diagnostics       BOOLEAN NOT NULL DEFAULT true,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE client_sources (
  id            SERIAL PRIMARY KEY,
  client_id     INT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  ad_account_id INT NOT NULL REFERENCES ad_accounts(id) ON DELETE CASCADE,
  tg_prefix     TEXT,          -- TG Ads: [MIJOZ] prefiksi bo'yicha reklamalarni ajratish
  UNIQUE (client_id, ad_account_id)
);

-- client_id = 0 -> umumiy (standart) qoida, aks holda mijozga xos
CREATE TABLE alert_rules (
  id            SERIAL PRIMARY KEY,
  client_id     INT NOT NULL DEFAULT 0,
  type          TEXT NOT NULL,
  enabled       BOOLEAN NOT NULL DEFAULT true,
  threshold     NUMERIC,
  notify_client BOOLEAN NOT NULL DEFAULT false,
  UNIQUE (client_id, type)
);

INSERT INTO alert_rules (client_id, type, enabled, threshold, notify_client) VALUES
  (0, 'account_status', true, NULL, false),
  (0, 'ad_issues',      true, NULL, false),
  (0, 'spend_limit',    true, 90,   false),
  (0, 'cpr_spike',      true, 30,   false),
  (0, 'spend_no_result',true, 5,    false),
  (0, 'token_error',    true, NULL, false);

CREATE TABLE insights_daily (
  ad_account_id INT NOT NULL REFERENCES ad_accounts(id) ON DELETE CASCADE,
  date          DATE NOT NULL,
  spend         NUMERIC NOT NULL DEFAULT 0,
  impressions   BIGINT NOT NULL DEFAULT 0,
  reach         BIGINT NOT NULL DEFAULT 0,
  clicks        BIGINT NOT NULL DEFAULT 0,
  ctr           NUMERIC NOT NULL DEFAULT 0,
  cpm           NUMERIC NOT NULL DEFAULT 0,
  frequency     NUMERIC NOT NULL DEFAULT 0,
  actions       JSONB NOT NULL DEFAULT '[]',
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ad_account_id, date)
);

CREATE TABLE events (
  id          BIGSERIAL PRIMARY KEY,
  source      TEXT NOT NULL,
  external_id TEXT,
  field       TEXT NOT NULL,
  payload     JSONB NOT NULL,
  processed   BOOLEAN NOT NULL DEFAULT false,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX events_unprocessed ON events (processed) WHERE processed = false;

CREATE TABLE alerts_log (
  id            BIGSERIAL PRIMARY KEY,
  dedupe_key    TEXT NOT NULL UNIQUE,
  type          TEXT NOT NULL,
  ad_account_id INT,
  client_id     INT,
  message       TEXT NOT NULL,
  sent_to       TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reports_log (
  id         BIGSERIAL PRIMARY KEY,
  client_id  INT NOT NULL,
  kind       TEXT NOT NULL,           -- daily | weekly | diagnostics
  period     DATE NOT NULL,
  ok         BOOLEAN NOT NULL,
  error      TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, kind, period)
);

CREATE TABLE jobs (
  id         BIGSERIAL PRIMARY KEY,
  type       TEXT NOT NULL,           -- sync_now | test_report | diagnostics_now
  payload    JSONB NOT NULL DEFAULT '{}',
  status     TEXT NOT NULL DEFAULT 'pending',
  error      TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  done_at    TIMESTAMPTZ
);

CREATE TABLE heartbeat (
  name TEXT PRIMARY KEY,
  at   TIMESTAMPTZ NOT NULL
);
