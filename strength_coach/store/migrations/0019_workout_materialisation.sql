-- 0019_workout_materialisation — workout sets become normal actual sets.
--
-- The workout draft is not a second permanent store. On completion the sets are materialised
-- into session/clean_set so e1RM, volume and review see them; the workout tables keep the
-- event audit and the prescription snapshot.

ALTER TABLE session ADD COLUMN prescription_id TEXT;
ALTER TABLE session ADD COLUMN source TEXT NOT NULL DEFAULT 'import';
ALTER TABLE session ADD COLUMN workout_id TEXT;
ALTER TABLE session ADD COLUMN session_rpe REAL;
ALTER TABLE session ADD COLUMN session_rpe_recorded INTEGER NOT NULL DEFAULT 0
    CHECK (session_rpe_recorded IN (0, 1));

ALTER TABLE clean_set ADD COLUMN prescription_item_index INTEGER;
