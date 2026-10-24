-- 0026_readiness_context — preset source and optional context flags.
--
-- Presets write ordinary readiness entries with source='preset'. Context flags are separate
-- append-only observations; they are displayed beside readiness and do not change the score
-- unless an explicit device-suppression config is enabled.

CREATE TABLE readiness_entry_new (
    entry_id    TEXT PRIMARY KEY,
    on_date     TEXT NOT NULL,
    field       TEXT NOT NULL CHECK (field IN (
                    'sleep', 'energy', 'mood', 'soreness', 'stress', 'nutrition',
                    'hydration', 'squat_readiness', 'bench_readiness',
                    'deadlift_readiness', 'hrv_ms', 'rhr_bpm', 'bodyweight_kg', 'fat_pct',
                    'grip_strength_kg'
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

CREATE TABLE readiness_context (
    context_id TEXT PRIMARY KEY,
    on_date    TEXT NOT NULL,
    flag       TEXT NOT NULL,
    note       TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_readiness_context_date ON readiness_context(on_date, flag, created_at);
CREATE TRIGGER readiness_context_no_update BEFORE UPDATE ON readiness_context
BEGIN SELECT RAISE(ABORT, 'append-only: readiness_context rows cannot be updated'); END;
CREATE TRIGGER readiness_context_no_delete BEFORE DELETE ON readiness_context
BEGIN SELECT RAISE(ABORT, 'append-only: readiness_context rows cannot be deleted'); END;
