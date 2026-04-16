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
