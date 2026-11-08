-- 0054_healthkit_readiness.sql — Phase 3A HealthKit HRV/RHR observations.
--
-- HealthKit is a third readiness source: manual/preset entries win, then these observations,
-- then the imported readiness_day row. This table is append-only; the canonical readiness query
-- selects the latest observation per date/field. No raw HealthKit time series is stored.
--
-- Additive only. Existing readiness_day and readiness_entry rows are untouched.
-- Rollback drops this table and removes the 0054 schema_migration row together.

CREATE TABLE healthkit_readiness (
    observation_id       TEXT PRIMARY KEY,              -- uuid4 hex
    device_id            TEXT NOT NULL REFERENCES ios_device(device_id),
    on_date              TEXT NOT NULL,                 -- server-local YYYY-MM-DD
    field                TEXT NOT NULL CHECK (field IN ('hrv_ms', 'rhr_bpm')),
    value                REAL NOT NULL CHECK (value > 0),
    sample_id            TEXT NOT NULL,                 -- HealthKit object UUID
    sample_at            TEXT NOT NULL,                 -- canonical UTC ISO-8601
    source_name          TEXT NOT NULL,                 -- display/audit only
    source_bundle_id     TEXT,
    source_class         TEXT NOT NULL
                         CHECK (source_class IN ('apple_watch', 'non_apple_watch', 'unknown')),
    source_model         TEXT,
    source_manufacturer  TEXT,
    imported_at          TEXT NOT NULL,                 -- UTC ISO-8601
    UNIQUE (device_id, field, sample_id)
);

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
