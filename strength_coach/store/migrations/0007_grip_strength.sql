-- 0007_grip_strength — manual grip strength in kg.
--
-- Grip is a device measurement, not a 1-5 score: zero is impossible, so it uses the same
-- zero-is-missing rule as HRV/RHR/bodyweight. The field is added to readiness_day for
-- imported rows and to readiness_entry's allow-list for manual rows.

ALTER TABLE readiness_day ADD COLUMN grip_strength_kg REAL;

CREATE TABLE readiness_entry_new (
    entry_id    TEXT    PRIMARY KEY,
    on_date     TEXT    NOT NULL,
    field       TEXT    NOT NULL CHECK (field IN (
                    'sleep', 'energy', 'mood', 'soreness', 'stress', 'nutrition',
                    'hydration', 'squat_readiness', 'bench_readiness',
                    'deadlift_readiness', 'hrv_ms', 'rhr_bpm', 'bodyweight_kg', 'fat_pct',
                    'grip_strength_kg'
                )),
    value       REAL    NOT NULL,
    source      TEXT    NOT NULL CHECK (source IN ('manual', 'import')),
    recorded_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    note        TEXT
);

INSERT INTO readiness_entry_new (
    entry_id, on_date, field, value, source, recorded_at, note
)
SELECT entry_id, on_date, field, value, source, recorded_at, note
  FROM readiness_entry;

DROP TABLE readiness_entry;
ALTER TABLE readiness_entry_new RENAME TO readiness_entry;

CREATE INDEX idx_readiness_entry_date ON readiness_entry(on_date, field, recorded_at);

CREATE TRIGGER readiness_entry_no_update BEFORE UPDATE ON readiness_entry
BEGIN SELECT RAISE(ABORT, 'append-only: readiness_entry rows cannot be updated'); END;
CREATE TRIGGER readiness_entry_no_delete BEFORE DELETE ON readiness_entry
BEGIN SELECT RAISE(ABORT, 'append-only: readiness_entry rows cannot be deleted'); END;
