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
