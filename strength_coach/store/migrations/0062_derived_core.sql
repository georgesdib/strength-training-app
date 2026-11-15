-- 0061_derived_core — Milestone B core derived rows.
--
-- Per-set derived values and per-session/exercise aggregates used by the progress and
-- strength-trend owners. Rows are disposable and versioned; the owners keep the formulas.
-- Consumers filter on method_version and only read these tables when the core family is ready.

BEGIN IMMEDIATE;

CREATE TABLE derived_set (
    set_id           INTEGER PRIMARY KEY,
    method_version   TEXT NOT NULL,
    session_id       TEXT NOT NULL,
    exercise_id      TEXT NOT NULL,
    occurred_on      TEXT NOT NULL,
    e1rm_kg          REAL,
    e1rm_usable      INTEGER NOT NULL DEFAULT 0,
    strength_json    TEXT,
    computed_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_derived_set_session ON derived_set(session_id);
CREATE INDEX idx_derived_set_lookup ON derived_set(exercise_id, occurred_on);

CREATE TABLE derived_session_exercise (
    session_id       TEXT NOT NULL,
    exercise_id      TEXT NOT NULL,
    method_version   TEXT NOT NULL,
    occurred_on      TEXT NOT NULL,
    best_e1rm_kg     REAL,
    working_sets     INTEGER NOT NULL DEFAULT 0,
    tonnage_kg       REAL,
    total_reps       INTEGER NOT NULL DEFAULT 0,
    mean_load_kg     REAL,
    computed_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (session_id, exercise_id, method_version)
);

CREATE INDEX idx_derived_session_exercise_method
    ON derived_session_exercise(method_version, exercise_id, occurred_on);

COMMIT;
