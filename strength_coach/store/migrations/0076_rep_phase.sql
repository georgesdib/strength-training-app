-- 0076_rep_phase — optional per-rep motion detail.
--
-- A set's mean velocity stays clean_set.velocity_mps and its per-rep velocities stay
-- clean_rep. Phase durations, range of motion and a confidence score are separate detail:
-- they can exist for a set that carries no velocity at all, so they must not live in
-- clean_rep, whose velocity_mps is NOT NULL.
--
-- Append-only, like every other clean table. No rule, prescription or readiness module
-- reads this table; it is descriptive.

-- The per-rep motion payload carries one algorithm version per set, not per rep: it is a
-- property of the build that derived the values.
ALTER TABLE workout_rep_event ADD COLUMN motion_version TEXT;

CREATE TABLE clean_rep_phase (
    phase_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    clean_set_id   INTEGER NOT NULL REFERENCES clean_set(set_id),
    rep_index      INTEGER NOT NULL CHECK (rep_index > 0),
    lower_ms       INTEGER,
    lift_ms        INTEGER,
    pause_ms       INTEGER,
    rom_m          REAL,
    steadiness     REAL,
    confidence     REAL,
    -- Without raw samples the on-device algorithm cannot be re-run, so its version is part
    -- of the measurement: a version change is a step change in every number.
    method_version TEXT NOT NULL,
    started_at     TEXT,
    source         TEXT NOT NULL CHECK (source IN ('import', 'device', 'manual')),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (clean_set_id, rep_index)
);

CREATE INDEX idx_clean_rep_phase_set ON clean_rep_phase(clean_set_id, rep_index);

CREATE TRIGGER clean_rep_phase_no_update BEFORE UPDATE ON clean_rep_phase
BEGIN SELECT RAISE(ABORT, 'append-only: clean_rep_phase rows cannot be updated'); END;
CREATE TRIGGER clean_rep_phase_no_delete BEFORE DELETE ON clean_rep_phase
BEGIN SELECT RAISE(ABORT, 'append-only: clean_rep_phase rows cannot be deleted'); END;
