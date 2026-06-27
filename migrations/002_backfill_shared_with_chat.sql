-- Migration 002: backfill NULL shared_with_chat and enforce the constraint.
--
-- Symptom this fixes: some rows have shared_with_chat = NULL (the column
-- pre-existed nullable, so migration 001's "ADD COLUMN IF NOT EXISTS ... NOT
-- NULL DEFAULT true" skipped setting the default/backfill). The chat-context
-- read filters use `shared_with_chat = true`, which EXCLUDES NULL rows — so
-- any activity with a NULL flag silently disappears from what the AI sees
-- (e.g. weight entries). This backfills NULLs to true and enforces the column
-- so it can never be NULL again. Safe to re-run.

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'meal_entries', 'exercise_logs', 'weight_entries', 'sleep_entries',
        'daily_water', 'daily_steps', 'supplement_logs', 'period_entries'
    ]
    LOOP
        EXECUTE format('UPDATE %I SET shared_with_chat = true WHERE shared_with_chat IS NULL;', t);
        EXECUTE format('ALTER TABLE %I ALTER COLUMN shared_with_chat SET DEFAULT true;', t);
        EXECUTE format('ALTER TABLE %I ALTER COLUMN shared_with_chat SET NOT NULL;', t);
    END LOOP;
END $$;

-- Also ensure the users default-map column is non-null.
UPDATE users SET chat_sharing_defaults = '{}'::jsonb WHERE chat_sharing_defaults IS NULL;
ALTER TABLE users ALTER COLUMN chat_sharing_defaults SET DEFAULT '{}'::jsonb;
ALTER TABLE users ALTER COLUMN chat_sharing_defaults SET NOT NULL;
