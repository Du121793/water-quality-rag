BEGIN;

ALTER TABLE chat_sessions
ADD COLUMN IF NOT EXISTS summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE chat_sessions
SET summary_json = jsonb_build_object(
    'version', 1,
    'updated_at', COALESCE(updated_at, NOW())::text,
    'current_goal', NULLIF(btrim(summary), ''),
    'confirmed_facts', '[]'::jsonb,
    'open_questions', '[]'::jsonb,
    'recent_topics', '[]'::jsonb,
    'time_preferences', '{}'::jsonb,
    'important_metrics', '{}'::jsonb,
    'assistant_state', '{}'::jsonb,
    'legacy_summary_text', summary
)
WHERE summary_json = '{}'::jsonb
  AND summary IS NOT NULL
  AND btrim(summary) <> '';

COMMIT;
