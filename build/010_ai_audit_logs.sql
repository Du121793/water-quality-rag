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
