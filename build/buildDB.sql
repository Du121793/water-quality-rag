BEGIN;

-- Reset existing schema objects before rebuilding
DROP TABLE IF EXISTS rag_ingest_jobs CASCADE;
DROP TABLE IF EXISTS chat_messages CASCADE;
DROP TABLE IF EXISTS chat_sessions CASCADE;
DROP TABLE IF EXISTS paper_embeddings CASCADE;
DROP TABLE IF EXISTS paper_chunks CASCADE;
DROP TABLE IF EXISTS paper_sources CASCADE;
DROP TABLE IF EXISTS ai_audit_logs CASCADE;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS ai_audit_logs (
    id                BIGSERIAL PRIMARY KEY,
    request_id        TEXT NOT NULL UNIQUE,
    user_id           BIGINT NOT NULL,
    pond_id           BIGINT NOT NULL,
    question          TEXT NOT NULL,
    context_summary   JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_text     TEXT,
    status            TEXT NOT NULL DEFAULT 'pending',
    error_message     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ai_audit_logs_user_pond
ON ai_audit_logs (user_id, pond_id, created_at DESC);

CREATE TABLE IF NOT EXISTS paper_sources (
    id                BIGSERIAL PRIMARY KEY,
    title             TEXT NOT NULL,
    title_normalized  TEXT NOT NULL DEFAULT '',
    authors           TEXT,
    journal_name      TEXT,
    doi               TEXT,
    source_url        TEXT NOT NULL,
    local_file_path   TEXT,
    file_hash         TEXT,
    content_hash      TEXT,
    published_at      DATE,
    species_tags      TEXT[] NOT NULL DEFAULT '{}',
    topic_tags        TEXT[] NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_sources_published_at
ON paper_sources (published_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_sources_source_url
ON paper_sources (source_url);

CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_sources_doi
ON paper_sources (lower(doi))
WHERE doi IS NOT NULL AND btrim(doi) <> '';

CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_sources_file_hash
ON paper_sources (file_hash)
WHERE file_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_sources_content_hash
ON paper_sources (content_hash)
WHERE content_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_paper_sources_title_normalized
ON paper_sources (title_normalized);

CREATE TABLE IF NOT EXISTS paper_chunks (
    id                BIGSERIAL PRIMARY KEY,
    paper_source_id   BIGINT NOT NULL REFERENCES paper_sources(id) ON DELETE CASCADE,
    chunk_index       INTEGER NOT NULL,
    chunk_text        TEXT NOT NULL,
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (paper_source_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_paper_chunks_source
ON paper_chunks (paper_source_id, chunk_index);

CREATE TABLE IF NOT EXISTS paper_embeddings (
    id                BIGSERIAL PRIMARY KEY,
    paper_chunk_id    BIGINT NOT NULL REFERENCES paper_chunks(id) ON DELETE CASCADE,
    embedding_provider TEXT NOT NULL,
    embedding_model   TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL,
    embedding         vector NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (paper_chunk_id, embedding_provider, embedding_model)
);

CREATE INDEX IF NOT EXISTS idx_paper_embeddings_lookup
ON paper_embeddings (embedding_provider, embedding_model, paper_chunk_id);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id                BIGSERIAL PRIMARY KEY,
    session_id        TEXT NOT NULL UNIQUE,
    user_id           BIGINT NOT NULL,
    pond_id           BIGINT NOT NULL,
    title             TEXT,
    summary           TEXT NOT NULL DEFAULT '',
    summary_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id                BIGSERIAL PRIMARY KEY,
    session_id        TEXT NOT NULL,
    role              TEXT NOT NULL,
    message           TEXT NOT NULL,
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
ON chat_messages (session_id, created_at);

CREATE TABLE IF NOT EXISTS rag_ingest_jobs (
    id                BIGSERIAL PRIMARY KEY,
    job_id            TEXT NOT NULL UNIQUE,
    paper_source_id   BIGINT REFERENCES paper_sources(id) ON DELETE SET NULL,
    requested_by      BIGINT,
    status            TEXT NOT NULL DEFAULT 'queued',
    embedding_provider TEXT,
    embedding_model   TEXT,
    chunk_total       INTEGER NOT NULL DEFAULT 0,
    embedded_chunks   INTEGER NOT NULL DEFAULT 0,
    error_message     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_rag_ingest_jobs_status_created_at
ON rag_ingest_jobs (status, created_at DESC);

COMMIT;
