-- 0010_readiness_setting — per-athlete readiness-score settings.
--
-- The rolling median baseline is the default. These append-only rows let one athlete change
-- the baseline window, minimum readings, slopes and weights without changing code. The latest
-- row with effective_from <= the score date wins. No row means config/defaults.

CREATE TABLE readiness_setting (
    setting_id             TEXT    PRIMARY KEY,
    effective_from         TEXT    NOT NULL,
    baseline_days          INTEGER NOT NULL CHECK (baseline_days BETWEEN 1 AND 365),
    baseline_min_readings  INTEGER NOT NULL CHECK (baseline_min_readings BETWEEN 1 AND baseline_days),
    hrv_slope              REAL    NOT NULL CHECK (hrv_slope > 0 AND hrv_slope <= 1),
    rhr_slope              REAL    NOT NULL CHECK (rhr_slope > 0 AND rhr_slope <= 1),
    hrv_weight             REAL    NOT NULL CHECK (hrv_weight BETWEEN 0.0 AND 1.0),
    rhr_weight             REAL    NOT NULL CHECK (rhr_weight BETWEEN 0.0 AND 1.0),
    wearable_weight        REAL    NOT NULL CHECK (wearable_weight BETWEEN 0.0 AND 1.0),
    note                   TEXT,
    source                 TEXT    NOT NULL DEFAULT 'user',
    created_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_readiness_setting_date ON readiness_setting(effective_from, created_at);

CREATE TRIGGER readiness_setting_no_update BEFORE UPDATE ON readiness_setting
BEGIN SELECT RAISE(ABORT, 'append-only: readiness_setting rows cannot be updated'); END;
CREATE TRIGGER readiness_setting_no_delete BEFORE DELETE ON readiness_setting
BEGIN SELECT RAISE(ABORT, 'append-only: readiness_setting rows cannot be deleted'); END;
