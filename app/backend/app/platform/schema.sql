-- RAG Platform Demo — minimal Postgres schema
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name  TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  vector_doc_id TEXT,
  filename      TEXT NOT NULL,
  title         TEXT,
  source_path   TEXT,
  status        TEXT NOT NULL DEFAULT 'pending',
  error_message TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_documents_user_created
  ON documents(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS conversations (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title      TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
  ON conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role             TEXT NOT NULL,
  content          TEXT NOT NULL DEFAULT '',
  citations_json   JSONB NOT NULL DEFAULT '[]'::jsonb,
  latency_ms       INT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
  ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS eval_datasets (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval_items (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_id      UUID NOT NULL REFERENCES eval_datasets(id) ON DELETE CASCADE,
  question        TEXT NOT NULL,
  correct_answer  TEXT NOT NULL,
  citation_text   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS eval_runs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  dataset_id  UUID NOT NULL REFERENCES eval_datasets(id) ON DELETE CASCADE,
  status      TEXT NOT NULL DEFAULT 'queued',
  pass_rate   DOUBLE PRECISION,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS eval_results (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id       UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
  item_id      UUID NOT NULL REFERENCES eval_items(id) ON DELETE CASCADE,
  model_answer TEXT NOT NULL DEFAULT '',
  decision     TEXT NOT NULL,
  correctness  DOUBLE PRECISION,
  grounding    DOUBLE PRECISION,
  rationale    TEXT
);
CREATE INDEX IF NOT EXISTS idx_eval_results_run ON eval_results(run_id);
