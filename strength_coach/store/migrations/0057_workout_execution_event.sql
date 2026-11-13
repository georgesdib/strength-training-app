-- 0057_workout_execution_event — append-only device execution telemetry.
--
-- This is deliberately separate from workout_event (the server mutation/audit stream) and
-- workout_set (the canonical performed set). Events never create or mutate sets; they record
-- when the user started/completed work and rest. event_id is the client-generated identity used
-- for idempotent ingestion across delayed offline replay.

BEGIN IMMEDIATE;

CREATE TABLE workout_execution_event (
    event_id        TEXT PRIMARY KEY,
    workout_id      TEXT NOT NULL REFERENCES workout_session(workout_id),
    event_type      TEXT NOT NULL CHECK (event_type IN (
                        'set_started', 'set_completed',
                        'rest_started', 'rest_completed', 'rest_skipped', 'rest_extended',
                        'exercise_started', 'exercise_completed',
                        'workout_paused', 'workout_resumed'
                    )),
    plan_item_index INTEGER,
    set_id          INTEGER REFERENCES workout_set(set_id),
    local_set_id    TEXT,
    occurred_at     TEXT NOT NULL,
    received_at     TEXT NOT NULL,
    device_id       TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'ios' CHECK (source IN ('ios')),
    payload_json    TEXT NOT NULL DEFAULT '{}',
    CHECK (plan_item_index IS NULL OR plan_item_index >= 0),
    CHECK (local_set_id IS NULL OR length(local_set_id) <= 64),
    CHECK (length(payload_json) <= 8192)
);

CREATE INDEX idx_workout_execution_event_workout
    ON workout_execution_event(workout_id, occurred_at, event_id);
CREATE INDEX idx_workout_execution_event_type
    ON workout_execution_event(workout_id, event_type, occurred_at);
CREATE INDEX idx_workout_execution_event_set
    ON workout_execution_event(workout_id, set_id);
CREATE INDEX idx_workout_execution_event_local_set
    ON workout_execution_event(workout_id, local_set_id);

CREATE TRIGGER workout_execution_event_no_update
BEFORE UPDATE ON workout_execution_event
BEGIN SELECT RAISE(ABORT, 'append-only: workout_execution_event rows cannot be updated'); END;

CREATE TRIGGER workout_execution_event_no_delete
BEFORE DELETE ON workout_execution_event
BEGIN SELECT RAISE(ABORT, 'append-only: workout_execution_event rows cannot be deleted'); END;

COMMIT;
