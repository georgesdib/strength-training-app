-- 0017_workout — live workout session linked to the prescription snapshot.
--
-- A workout is an operational draft: it has a mutable status/end time, while the prescription
-- and the actual sets are append-only. The plan snapshot is copied so a later prescription
-- regeneration cannot rewrite what was shown when the workout started.

CREATE TABLE workout_session (
    workout_id          TEXT PRIMARY KEY,
    prescription_id     TEXT REFERENCES prescription(prescription_id),
    for_date            TEXT NOT NULL,
    session_type        TEXT,
    session_day         TEXT NOT NULL CHECK (session_day IN ('A', 'B', 'C')),
    status              TEXT NOT NULL DEFAULT 'in_progress'
                        CHECK (status IN ('in_progress', 'completed', 'abandoned')),
    plan_json           TEXT NOT NULL,
    readiness_json      TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    ended_at            TEXT,
    duration_measured_s INTEGER,
    duration_min        REAL,
    duration_source     TEXT CHECK (duration_source IN ('measured', 'manual')),
    session_rpe         REAL,
    session_rpe_recorded INTEGER NOT NULL DEFAULT 0 CHECK (session_rpe_recorded IN (0, 1)),
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_workout_status ON workout_session(status, started_at);

CREATE TABLE workout_set (
    set_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id              TEXT NOT NULL REFERENCES workout_session(workout_id),
    exercise_id             TEXT NOT NULL,
    set_index               INTEGER NOT NULL,
    load_kg                 REAL,
    reps                    INTEGER,
    rir                     INTEGER,
    velocity                REAL,
    source                  TEXT NOT NULL DEFAULT 'manual'
                            CHECK (source IN ('manual', 'import', 'device')),
    prescription_item_index INTEGER,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (workout_id, exercise_id, set_index)
);

CREATE INDEX idx_workout_set_workout ON workout_set(workout_id, exercise_id, set_index);

CREATE TABLE workout_event (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id     TEXT NOT NULL REFERENCES workout_session(workout_id),
    event_type     TEXT NOT NULL,
    target_set_id  INTEGER REFERENCES workout_set(set_id),
    payload_json   TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_workout_event_workout ON workout_event(workout_id, event_id);

CREATE TRIGGER workout_event_no_update BEFORE UPDATE ON workout_event
BEGIN SELECT RAISE(ABORT, 'append-only: workout_event rows cannot be updated'); END;

CREATE TRIGGER workout_event_no_delete BEFORE DELETE ON workout_event
BEGIN SELECT RAISE(ABORT, 'append-only: workout_event rows cannot be deleted'); END;
