-- 0060_plank_variants — split Side Plank and Chinese Plank from the generic plank.
--
-- Both are distinct holds with their own log names, and until now every plank variant resolved
-- to `plank`, so their history was pooled. The raw rows are untouched; clean_set identity is
-- rewritten with an audit trail, exactly as migrations 0014 and 0015 did.
--
-- Regular Plank (and the bare 'plank' rows) stay `plank`. Only the imported rows carry a
-- `raw_exercise`, so a live-logged hold can only be split when its logged name says so.

DROP TRIGGER clean_set_no_update;

INSERT INTO exercise_remap_log (raw_id, old_exercise_id, new_exercise_id, reason)
SELECT s.raw_id, s.exercise_id, 'side_plank', 'plank variant split 2026-11-14'
FROM clean_set s
WHERE s.raw_exercise = 'Side Plank'
  AND s.exercise_id = 'plank';

UPDATE clean_set
SET exercise_id = 'side_plank'
WHERE raw_exercise = 'Side Plank'
  AND exercise_id = 'plank';

INSERT INTO exercise_remap_log (raw_id, old_exercise_id, new_exercise_id, reason)
SELECT s.raw_id, s.exercise_id, 'chinese_plank', 'plank variant split 2026-11-14'
FROM clean_set s
WHERE s.raw_exercise = 'Chinese Plank'
  AND s.exercise_id = 'plank';

UPDATE clean_set
SET exercise_id = 'chinese_plank'
WHERE raw_exercise = 'Chinese Plank'
  AND exercise_id = 'plank';

CREATE TRIGGER clean_set_no_update BEFORE UPDATE ON clean_set
BEGIN SELECT RAISE(ABORT, 'append-only: clean_set rows cannot be updated'); END;
