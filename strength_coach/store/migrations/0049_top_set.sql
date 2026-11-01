-- Step 3 top-set/back-off structure and role-aware workout logging.
--
-- set_groups_json is an ordered array of planned set groups (top_set/back_off). An empty
-- array is the historical/straight-set representation, so no backfill is needed.
-- workout_set.set_role is nullable for the same reason: old and imported sets are ordinary.

ALTER TABLE prescription_item ADD COLUMN set_groups_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE workout_set ADD COLUMN set_role TEXT;
ALTER TABLE clean_set ADD COLUMN set_role TEXT;
