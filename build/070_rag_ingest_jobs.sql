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
