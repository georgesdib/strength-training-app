-- 0021_workout_review — link the deterministic critique and mark review completion.
--
-- The critique is computed from the materialised session; this column makes the end-workout
-- rubric run auditable and lets the workout close only after human marks are saved.

ALTER TABLE workout_session ADD COLUMN critique_id TEXT;
ALTER TABLE workout_session ADD COLUMN reviewed_at TEXT;
