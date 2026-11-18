-- 0071_hrv_recovery.sql — a dated recovery-HRV series beside the raw HealthKit series.
--
-- Phase 3A stores the newest HealthKit SDNN sample per day in healthkit_readiness. Readiness now
-- reads a recovery value instead: one median per night, taken from the night/morning window, so a
-- daytime reading no longer feeds readiness. That series needs its own dated ingestion because the
-- readiness sample route only accepts today's date, and the history is backfilled from HealthKit.
--
-- healthkit_readiness is unchanged and remains the audit record of what was measured. The
-- readiness merge overrides hrv_ms from this table when a day has a recovery value and suppresses
-- it otherwise, so raw and recovery values are never mixed in one baseline.
--
-- Roll back by dropping the table and removing the override in queries._effective_readiness_rows.

CREATE TABLE hrv_recovery (
    sample_id       TEXT PRIMARY KEY,
    device_id       TEXT NOT NULL REFERENCES ios_device(device_id),
    on_date         TEXT NOT NULL,
    value           REAL NOT NULL CHECK (value > 0),
    sample_at       TEXT NOT NULL,
    source_name     TEXT NOT NULL,
    source_class    TEXT NOT NULL
                    CHECK (source_class IN ('apple_watch', 'non_apple_watch', 'unknown')),
    sample_count    INTEGER NOT NULL DEFAULT 0,
    imported_at     TEXT NOT NULL,
    UNIQUE (device_id, sample_id)
);

CREATE INDEX idx_hrv_recovery_date ON hrv_recovery(on_date, sample_at);
CREATE INDEX idx_hrv_recovery_device ON hrv_recovery(device_id, on_date);

CREATE TRIGGER hrv_recovery_no_update
BEFORE UPDATE ON hrv_recovery
BEGIN SELECT RAISE(ABORT, 'append-only: hrv_recovery rows cannot be updated'); END;

CREATE TRIGGER hrv_recovery_no_delete
BEFORE DELETE ON hrv_recovery
BEGIN SELECT RAISE(ABORT, 'append-only: hrv_recovery rows cannot be deleted'); END;
