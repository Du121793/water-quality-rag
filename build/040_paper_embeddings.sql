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
