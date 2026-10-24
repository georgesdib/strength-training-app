-- 0029_readiness_wearable_score — allow the optional wearable readiness observation.
--
-- readiness_day has carried wearable_score since migration 0009, and the form/repository write
-- it, but the readiness_entry CHECK added in 0026 omitted it. Rebuild the append-only entry table
-- with the same columns plus wearable_score; no rows are dropped.

CREATE TABLE readiness_entry_new (
    entry_id    TEXT PRIMARY KEY,
    on_date     TEXT NOT NULL,
    field       TEXT NOT NULL CHECK (field IN (
                    'sleep', 'energy', 'mood', 'soreness', 'stress', 'nutrition',
                    'hydration', 'squat_readiness', 'bench_readiness',
                    'deadlift_readiness', 'hrv_ms', 'rhr_bpm', 'bodyweight_kg', 'fat_pct',
                    'grip_strength_kg', 'wearable_score'
                )),
    value       REAL NOT NULL,
    source      TEXT NOT NULL CHECK (source IN ('manual', 'import', 'preset')),
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
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
