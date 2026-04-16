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
