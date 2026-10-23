-- 0018_workout_guards — actual sets are append-only.
--
-- Removal is recorded as a workout_event and filtered by the reader, never as a DELETE or
-- UPDATE. The session row itself is operational state and may still be completed/abandoned.

CREATE TRIGGER workout_set_no_update BEFORE UPDATE ON workout_set
BEGIN SELECT RAISE(ABORT, 'append-only: workout_set rows cannot be updated'); END;

CREATE TRIGGER workout_set_no_delete BEFORE DELETE ON workout_set
BEGIN SELECT RAISE(ABORT, 'append-only: workout_set rows cannot be deleted'); END;
