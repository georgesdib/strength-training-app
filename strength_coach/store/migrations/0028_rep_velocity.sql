-- 0028_rep_velocity — optional per-rep velocity detail.
--
-- A set's mean velocity remains clean_set.velocity_mps. Rep samples are optional detail and
-- are append-only: a correction is a new workout_rep_event snapshot, and materialisation writes
-- individual clean_rep rows. No rule or prescription reads this table.

CREATE TABLE workout_rep_event (
    event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id    TEXT NOT NULL REFERENCES workout_session(workout_id),
    set_id        INTEGER NOT NULL REFERENCES workout_set(set_id),
    reps_json     TEXT NOT NULL,
    source        TEXT NOT NULL CHECK (source IN ('import', 'device', 'manual')),
    batch_id      TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_workout_rep_event_set
    ON workout_rep_event(workout_id, set_id, event_id);

CREATE TRIGGER workout_rep_event_no_update BEFORE UPDATE ON workout_rep_event
BEGIN SELECT RAISE(ABORT, 'append-only: workout_rep_event rows cannot be updated'); END;
CREATE TRIGGER workout_rep_event_no_delete BEFORE DELETE ON workout_rep_event
BEGIN SELECT RAISE(ABORT, 'append-only: workout_rep_event rows cannot be deleted'); END;

CREATE TABLE clean_rep (
    rep_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    clean_set_id INTEGER NOT NULL REFERENCES clean_set(set_id),
    rep_index    INTEGER NOT NULL CHECK (rep_index > 0),
    velocity_mps REAL NOT NULL,
    source       TEXT NOT NULL CHECK (source IN ('import', 'device', 'manual')),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (clean_set_id, rep_index)
);

CREATE INDEX idx_clean_rep_set ON clean_rep(clean_set_id, rep_index);

CREATE TRIGGER clean_rep_no_update BEFORE UPDATE ON clean_rep
BEGIN SELECT RAISE(ABORT, 'append-only: clean_rep rows cannot be updated'); END;
CREATE TRIGGER clean_rep_no_delete BEFORE DELETE ON clean_rep
BEGIN SELECT RAISE(ABORT, 'append-only: clean_rep rows cannot be deleted'); END;
