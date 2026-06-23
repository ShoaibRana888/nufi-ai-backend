-- Migration 001: user-controlled "share with AI chat" flag
--
-- Run this in the Supabase SQL editor BEFORE deploying the backend changes
-- that filter on `shared_with_chat`. Safe to re-run (idempotent).
--
-- 1) Per-row opt-out flag on every activity table. Default TRUE preserves
--    today's behaviour (everything is shared with the AI coach unless the
--    user explicitly hides it).

ALTER TABLE meal_entries     ADD COLUMN IF NOT EXISTS shared_with_chat boolean NOT NULL DEFAULT true;
ALTER TABLE exercise_logs    ADD COLUMN IF NOT EXISTS shared_with_chat boolean NOT NULL DEFAULT true;
ALTER TABLE weight_entries   ADD COLUMN IF NOT EXISTS shared_with_chat boolean NOT NULL DEFAULT true;
ALTER TABLE sleep_entries    ADD COLUMN IF NOT EXISTS shared_with_chat boolean NOT NULL DEFAULT true;
ALTER TABLE daily_water      ADD COLUMN IF NOT EXISTS shared_with_chat boolean NOT NULL DEFAULT true;
ALTER TABLE daily_steps      ADD COLUMN IF NOT EXISTS shared_with_chat boolean NOT NULL DEFAULT true;
ALTER TABLE supplement_logs  ADD COLUMN IF NOT EXISTS shared_with_chat boolean NOT NULL DEFAULT true;
ALTER TABLE period_entries   ADD COLUMN IF NOT EXISTS shared_with_chat boolean NOT NULL DEFAULT true;

-- 2) Per-activity-type master defaults, stored on the user. When a new entry
--    is logged, the backend reads this to decide the initial shared_with_chat
--    value for that activity type. Example value: {"weight": false, "period": false}

ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_sharing_defaults jsonb NOT NULL DEFAULT '{}'::jsonb;

-- 3) Partial indexes to keep the "only shared rows" reads fast.

CREATE INDEX IF NOT EXISTS idx_meal_entries_shared    ON meal_entries (user_id, meal_date)     WHERE shared_with_chat;
CREATE INDEX IF NOT EXISTS idx_exercise_logs_shared   ON exercise_logs (user_id, exercise_date) WHERE shared_with_chat;
CREATE INDEX IF NOT EXISTS idx_weight_entries_shared  ON weight_entries (user_id, date)         WHERE shared_with_chat;
CREATE INDEX IF NOT EXISTS idx_sleep_entries_shared   ON sleep_entries (user_id, date)          WHERE shared_with_chat;
CREATE INDEX IF NOT EXISTS idx_daily_water_shared     ON daily_water (user_id, date)            WHERE shared_with_chat;
CREATE INDEX IF NOT EXISTS idx_daily_steps_shared     ON daily_steps (user_id, date)            WHERE shared_with_chat;
CREATE INDEX IF NOT EXISTS idx_supplement_logs_shared ON supplement_logs (user_id, date)        WHERE shared_with_chat;
CREATE INDEX IF NOT EXISTS idx_period_entries_shared  ON period_entries (user_id, start_date)   WHERE shared_with_chat;

-- 4) Apply per-type master defaults to NEW entries via a trigger. When a row
--    is inserted, if the user has set chat_sharing_defaults[<type>] = false,
--    the new row's shared_with_chat is set to false automatically. Otherwise it
--    keeps the column default (true). Each trigger passes its activity-type key
--    as the first trigger argument.

CREATE OR REPLACE FUNCTION apply_chat_sharing_default()
RETURNS trigger AS $$
DECLARE
    default_val boolean;
BEGIN
    SELECT COALESCE((u.chat_sharing_defaults ->> TG_ARGV[0])::boolean, true)
      INTO default_val
      FROM users u
     WHERE u.id = NEW.user_id;

    IF default_val IS NOT NULL THEN
        NEW.shared_with_chat := default_val;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_share_default ON meal_entries;
CREATE TRIGGER trg_share_default BEFORE INSERT ON meal_entries
    FOR EACH ROW EXECUTE FUNCTION apply_chat_sharing_default('meal');

DROP TRIGGER IF EXISTS trg_share_default ON exercise_logs;
CREATE TRIGGER trg_share_default BEFORE INSERT ON exercise_logs
    FOR EACH ROW EXECUTE FUNCTION apply_chat_sharing_default('exercise');

DROP TRIGGER IF EXISTS trg_share_default ON weight_entries;
CREATE TRIGGER trg_share_default BEFORE INSERT ON weight_entries
    FOR EACH ROW EXECUTE FUNCTION apply_chat_sharing_default('weight');

DROP TRIGGER IF EXISTS trg_share_default ON sleep_entries;
CREATE TRIGGER trg_share_default BEFORE INSERT ON sleep_entries
    FOR EACH ROW EXECUTE FUNCTION apply_chat_sharing_default('sleep');

DROP TRIGGER IF EXISTS trg_share_default ON daily_water;
CREATE TRIGGER trg_share_default BEFORE INSERT ON daily_water
    FOR EACH ROW EXECUTE FUNCTION apply_chat_sharing_default('water');

DROP TRIGGER IF EXISTS trg_share_default ON daily_steps;
CREATE TRIGGER trg_share_default BEFORE INSERT ON daily_steps
    FOR EACH ROW EXECUTE FUNCTION apply_chat_sharing_default('steps');

DROP TRIGGER IF EXISTS trg_share_default ON supplement_logs;
CREATE TRIGGER trg_share_default BEFORE INSERT ON supplement_logs
    FOR EACH ROW EXECUTE FUNCTION apply_chat_sharing_default('supplement');

DROP TRIGGER IF EXISTS trg_share_default ON period_entries;
CREATE TRIGGER trg_share_default BEFORE INSERT ON period_entries
    FOR EACH ROW EXECUTE FUNCTION apply_chat_sharing_default('period');
