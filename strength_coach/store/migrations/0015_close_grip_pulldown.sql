-- 0015_close_grip_pulldown — split close-grip pulldown from lat pulldown.
--
-- Close grip is a genuine variant of the lat pulldown, not the same lift: narrower grip,
-- different leverage and load. It keeps its own history and selection slot.
-- The raw rows are untouched; clean_set identity is rewritten with an audit trail.

DROP TRIGGER clean_set_no_update;

INSERT INTO exercise_remap_log (raw_id, old_exercise_id, new_exercise_id, reason)
SELECT s.raw_id, s.exercise_id, 'close_grip_pulldown', 'close-grip grip variant split 2026-10-20'
FROM clean_set s
WHERE s.raw_exercise = 'Close Grip Pulldown'
  AND s.exercise_id = 'lat_pulldown';

UPDATE clean_set
SET exercise_id = 'close_grip_pulldown'
WHERE raw_exercise = 'Close Grip Pulldown'
  AND exercise_id = 'lat_pulldown';

CREATE TRIGGER clean_set_no_update BEFORE UPDATE ON clean_set
BEGIN SELECT RAISE(ABORT, 'append-only: clean_set rows cannot be updated'); END;
