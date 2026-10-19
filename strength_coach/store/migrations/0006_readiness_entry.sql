-- 0006_readiness_entry — manual readiness is history, not an upsert.
--
-- readiness_day is derived from the exported CSV and is re-written on import. A manual reading
-- needs the opposite: re-logging a date appends a version, and the latest value per field wins.
-- Imported values stay in readiness_day; manual entries live here and are overlaid per field
-- at read time (DEC-READINESS-03/04).

CREATE TABLE readiness_entry (
    entry_id    TEXT    PRIMARY KEY,
    on_date     TEXT    NOT NULL,
    field       TEXT    NOT NULL CHECK (field IN (
                    'sleep', 'energy', 'mood', 'soreness', 'stress', 'nutrition',
                    'hydration', 'squat_readiness', 'bench_readiness',
                    'deadlift_readiness', 'hrv_ms', 'rhr_bpm', 'bodyweight_kg', 'fat_pct'
                )),
    value       REAL    NOT NULL,
    source      TEXT    NOT NULL CHECK (source IN ('manual', 'import')),
    recorded_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    note        TEXT
);

CREATE INDEX idx_readiness_entry_date ON readiness_entry(on_date, field, recorded_at);

CREATE TRIGGER readiness_entry_no_update BEFORE UPDATE ON readiness_entry
BEGIN SELECT RAISE(ABORT, 'append-only: readiness_entry rows cannot be updated'); END;
CREATE TRIGGER readiness_entry_no_delete BEFORE DELETE ON readiness_entry
BEGIN SELECT RAISE(ABORT, 'append-only: readiness_entry rows cannot be deleted'); END;
