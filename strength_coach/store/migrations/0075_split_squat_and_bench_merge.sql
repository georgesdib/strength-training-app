-- 0075_split_squat_and_bench_merge - split the rear-foot-elevated variant out of split_squat
-- and merge the wide-grip bench press back into bench_press (DEC-VARIANT-06).
--
-- The raw rows are untouched. clean_set identity is rewritten with an audit trail, exactly as
-- migrations 0014, 0015 and 0060 did. Bulgarian sets are identified by their raw log name;
-- the wide-grip bench rows are identified by the retired id, which covers both imported rows
-- ("Bench Press (wide grip)") and live-logged rows (raw name is the id).
--
-- Derived tables (derived_set, derived_session_exercise) are caches: run
--   strength-coach --db <db> analytics build
-- after this migration so their exercise ids match the rewritten history. Prescription
-- snapshots, form ratings and the e1rm override table are records of what was recorded at the
-- time; they are left alone.

DROP TRIGGER clean_set_no_update;

INSERT INTO exercise_remap_log (raw_id, old_exercise_id, new_exercise_id, reason)
SELECT s.raw_id, s.exercise_id, 'bulgarian_split_squat', 'split squat variant split 2026-11-22'
FROM clean_set s
WHERE s.exercise_id = 'split_squat'
  AND lower(trim(s.raw_exercise)) = 'bulgarian split squat';

UPDATE clean_set
SET exercise_id = 'bulgarian_split_squat'
WHERE exercise_id = 'split_squat'
  AND lower(trim(raw_exercise)) = 'bulgarian split squat';

INSERT INTO exercise_remap_log (raw_id, old_exercise_id, new_exercise_id, reason)
SELECT s.raw_id, s.exercise_id, 'bench_press', 'wide-grip bench merged 2026-11-22'
FROM clean_set s
WHERE s.exercise_id = 'bench_press_wide_grip';

UPDATE clean_set
SET exercise_id = 'bench_press'
WHERE exercise_id = 'bench_press_wide_grip';

CREATE TRIGGER clean_set_no_update BEFORE UPDATE ON clean_set
BEGIN SELECT RAISE(ABORT, 'append-only: clean_set rows cannot be updated'); END;
