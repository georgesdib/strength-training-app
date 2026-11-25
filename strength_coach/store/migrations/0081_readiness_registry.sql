-- 0081_readiness_registry — append-only, date-effective registry of daily readiness inputs.
--
-- The global readiness score is a gate: it can move a load and cut sets. Its inputs, weights,
-- scale, baseline and minimum-field rule were hard-coded in readiness_score.py. This table makes
-- them a versioned data set without changing the score in release one: the effective registry for
-- a date is the latest row with effective_from <= date, the same semantic as settings_profile.
-- Rows are append-only; an edit adds a version and a rollback copies an older payload into a new
-- version.
--
-- Payload (validated in code, never trusted): {schema_version, min_core_fields, require_any_of,
-- wearable_weight, metrics: [{key, role, enabled, weight, baseline_days, counts_as_core, order,
-- min_readings, slope}]}. A metric key must exist in metric_definition, which carries the label,
-- scale and direction; the registry carries only the operational fields.

CREATE TABLE readiness_registry (
    registry_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    effective_from  TEXT    NOT NULL,
    schema_version  INTEGER NOT NULL,
    payload_json    TEXT    NOT NULL,
    note            TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_readiness_registry_effective
    ON readiness_registry(effective_from, registry_id);

CREATE TRIGGER readiness_registry_no_update BEFORE UPDATE ON readiness_registry
BEGIN SELECT RAISE(ABORT, 'append-only: readiness_registry rows cannot be updated'); END;
CREATE TRIGGER readiness_registry_no_delete BEFORE DELETE ON readiness_registry
BEGIN SELECT RAISE(ABORT, 'append-only: readiness_registry rows cannot be deleted'); END;

-- Catalogue rows so the seed and future registry keys resolve. source = 'readiness' separates
-- them from the periodic measurement catalogue; no measurement UI or query reads them.
INSERT OR IGNORE INTO metric_definition (
    metric_key, label, scale_min, scale_max, higher_is_better, aggregation, unit, source,
    active_from
)
VALUES
    ('sleep',    'Sleep',              1, 5, 1, 'last', NULL,  'readiness', NULL),
    ('energy',   'Energy',             1, 5, 1, 'last', NULL,  'readiness', NULL),
    ('mood',     'Mood',               1, 5, 1, 'last', NULL,  'readiness', NULL),
    ('stress',   'Stress',             1, 5, 1, 'last', NULL,  'readiness', NULL),
    ('soreness', 'Soreness',           1, 5, 1, 'last', NULL,  'readiness', NULL),
    ('hrv_ms',   'HRV (SDNN)',         0, NULL, 1, 'mean', 'ms', 'readiness', NULL),
    ('rhr_bpm',  'Resting heart rate', 0, NULL, 0, 'mean', 'bpm', 'readiness', NULL);

-- Seed version 1 with the pre-registry defaults. 1970-01-01 makes the seed effective for every
-- date, so historical prescriptions and current scores resolve to the same inputs they had.
INSERT INTO readiness_registry (effective_from, schema_version, payload_json, note, created_at)
VALUES (
    '1970-01-01',
    1,
    '{
      "schema_version": 1,
      "min_core_fields": 3,
      "require_any_of": ["sleep", "energy"],
      "wearable_weight": 0.1,
      "metrics": [
        {"key": "sleep",    "role": "core",   "enabled": true, "weight": 1.0,
         "baseline_days": 0,  "counts_as_core": true, "order": 1},
        {"key": "energy",   "role": "core",   "enabled": true, "weight": 1.0,
         "baseline_days": 0,  "counts_as_core": true, "order": 2},
        {"key": "mood",     "role": "core",   "enabled": true, "weight": 1.0,
         "baseline_days": 0,  "counts_as_core": true, "order": 3},
        {"key": "stress",   "role": "core",   "enabled": true, "weight": 1.0,
         "baseline_days": 0,  "counts_as_core": true, "order": 4},
        {"key": "soreness", "role": "core",   "enabled": true, "weight": 1.0,
         "baseline_days": 0,  "counts_as_core": true, "order": 5},
        {"key": "hrv_ms",   "role": "device", "enabled": true, "weight": 0.5,
         "baseline_days": 28, "counts_as_core": false, "min_readings": 7,
         "slope": 0.5, "order": 6},
        {"key": "rhr_bpm",  "role": "device", "enabled": true, "weight": 0.5,
         "baseline_days": 28, "counts_as_core": false, "min_readings": 7,
         "slope": 0.5, "order": 7}
      ]
    }',
    'seed: pre-registry defaults',
    '1970-01-01T00:00:00.000Z'
);
