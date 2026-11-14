-- 0062_derived_week — Milestone C weekly spinal exposures and set fields for consumers.

BEGIN IMMEDIATE;

ALTER TABLE derived_set ADD COLUMN load_kg REAL;
ALTER TABLE derived_set ADD COLUMN reps INTEGER;
ALTER TABLE derived_set ADD COLUMN rir INTEGER;
ALTER TABLE derived_set ADD COLUMN is_working_set INTEGER;
ALTER TABLE derived_set ADD COLUMN tonnage_kg REAL;

CREATE TABLE derived_week (
    iso_week        TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    exercise_id     TEXT NOT NULL,
    method_version  TEXT NOT NULL,
    weighted_cost   REAL NOT NULL,
    computed_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (iso_week, session_id, exercise_id, method_version)
);

CREATE INDEX idx_derived_week_version ON derived_week(method_version, iso_week);

COMMIT;
