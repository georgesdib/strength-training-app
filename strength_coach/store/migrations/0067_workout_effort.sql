-- 0067_workout_effort — the session effort Apple records per workout.
--
-- Apple's effort score is 1-10, the same scale as session RPE, and the watch app writes the
-- lifter's own sRPE into it. Storing it beside the workout (rather than in `measurement`) keeps it
-- attached to the session it describes; `measurement` is for periodic outcomes, not per-workout
-- metadata.
--
-- Nullable: only workouts with an effort relationship carry one, and absence is meaningful.

BEGIN IMMEDIATE;

ALTER TABLE external_workout ADD COLUMN srpe REAL
    CHECK (srpe IS NULL OR (srpe >= 1 AND srpe <= 10));

COMMIT;
