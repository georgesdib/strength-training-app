-- 0055_healthkit_bodyweight.sql — add body mass to the Phase 3A observation table.
--
-- Phase 3A originally allowed HRV and resting HR only. The owner subsequently requested
-- HealthKit bodyweight as an optional readiness input. SQLite cannot alter a CHECK constraint in
-- place, so this rebuilds the additive table while preserving every row and its provenance.
--
-- Roll back by rebuilding the same table with the original two-field CHECK, or by dropping
-- healthkit_readiness with migration rows 0054/0055 (§13.2).

CREATE TABLE healthkit_readiness_new (
    observation_id       TEXT PRIMARY KEY,
    device_id            TEXT NOT NULL REFERENCES ios_device(device_id),
    on_date              TEXT NOT NULL,
    field                TEXT NOT NULL
                         CHECK (field IN ('hrv_ms', 'rhr_bpm', 'bodyweight_kg')),
    value                REAL NOT NULL CHECK (value > 0),
    sample_id            TEXT NOT NULL,
    sample_at            TEXT NOT NULL,
    source_name          TEXT NOT NULL,
    source_bundle_id     TEXT,
    source_class         TEXT NOT NULL
                         CHECK (source_class IN ('apple_watch', 'non_apple_watch', 'unknown')),
    source_model         TEXT,
    source_manufacturer  TEXT,
    imported_at          TEXT NOT NULL,
    UNIQUE (device_id, field, sample_id)
);

INSERT INTO healthkit_readiness_new (
    observation_id, device_id, on_date, field, value, sample_id, sample_at,
    source_name, source_bundle_id, source_class, source_model,
    source_manufacturer, imported_at
)
SELECT observation_id, device_id, on_date, field, value, sample_id, sample_at,
       source_name, source_bundle_id, source_class, source_model,
       source_manufacturer, imported_at
  FROM healthkit_readiness;

DROP TABLE healthkit_readiness;
ALTER TABLE healthkit_readiness_new RENAME TO healthkit_readiness;

CREATE INDEX idx_healthkit_readiness_date
    ON healthkit_readiness(on_date, field, sample_at);
CREATE INDEX idx_healthkit_readiness_device
    ON healthkit_readiness(device_id, on_date);

CREATE TRIGGER healthkit_readiness_no_update
BEFORE UPDATE ON healthkit_readiness
BEGIN SELECT RAISE(ABORT, 'append-only: healthkit_readiness rows cannot be updated'); END;

CREATE TRIGGER healthkit_readiness_no_delete
BEFORE DELETE ON healthkit_readiness
BEGIN SELECT RAISE(ABORT, 'append-only: healthkit_readiness rows cannot be deleted'); END;
