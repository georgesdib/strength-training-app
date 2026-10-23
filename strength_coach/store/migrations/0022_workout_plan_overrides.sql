-- 0022_workout_plan_overrides — the workbook plan may change during a workout.
--
-- plan_json remains the frozen prescription snapshot. plan_modified_json is the latest
-- in-workout plan; every change also appends a workout_event with before/after detail.

ALTER TABLE workout_session ADD COLUMN plan_modified_json TEXT;
