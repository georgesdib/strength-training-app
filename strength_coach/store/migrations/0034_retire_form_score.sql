-- 0034_retire_form_score — the imported per-set Form column is no longer needed.
--
-- The 1=best / 5=worst values were averaged per exercise, inverted and copied into
-- session_form_rating. The raw_row payload still contains the exact imported Form value for
-- audit, so this intentional migration only clears the derived clean_set column. It is the
-- same kind of deliberate, logged exception as the earlier identity migrations; the normal
-- append-only trigger is restored immediately afterwards.

DROP TRIGGER clean_set_no_update;
UPDATE clean_set SET form_score = NULL WHERE form_score IS NOT NULL;
CREATE TRIGGER clean_set_no_update BEFORE UPDATE ON clean_set
BEGIN SELECT RAISE(ABORT, 'append-only: clean_set rows cannot be updated'); END;
