-- 0068_cardio_exclusion — hiding an imported workout without deleting it.
--
-- The corpus is append-only and the export cannot report deletions, so a wrong or unwanted workout
-- has no way out. Hiding is the honest correction: the row stays, every read path filters it, and
-- the decision is itself an append-only event (hide / show), latest wins.
--
-- This is not deletion. Nothing is lost, and un-hiding restores the row to every metric.

BEGIN IMMEDIATE;

CREATE TABLE cardio_exclusion (
    exclusion_id        TEXT PRIMARY KEY,
    external_workout_id TEXT NOT NULL REFERENCES external_workout(external_workout_id),
    action              TEXT NOT NULL CHECK (action IN ('hide', 'show')),
    reason              TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_cardio_exclusion_workout
    ON cardio_exclusion(external_workout_id, created_at);

CREATE TRIGGER cardio_exclusion_no_update BEFORE UPDATE ON cardio_exclusion
BEGIN SELECT RAISE(ABORT, 'append-only: cardio_exclusion rows cannot be updated'); END;
CREATE TRIGGER cardio_exclusion_no_delete BEFORE DELETE ON cardio_exclusion
BEGIN SELECT RAISE(ABORT, 'append-only: cardio_exclusion rows cannot be deleted'); END;

COMMIT;
