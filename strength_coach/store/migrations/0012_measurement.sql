-- 0012_measurement — periodic assessment metrics (VO2max, grip, function, steps, sitting).
--
-- Why separate from readiness: readiness is daily state that can reduce a load; a measurement
-- is an outcome taken every few weeks and must never change a prescription. Why a foreign key
-- to `metric_definition`: the direction (higher/lower is better) and aggregation must be
-- declared before a value can be interpreted, which is the rule that prevents the "stress 5
-- means no stress" class of inversion.
--
-- Append-only: a correction is a new row.

CREATE TABLE measurement (
    measurement_id TEXT    PRIMARY KEY,
    metric_key     TEXT    NOT NULL REFERENCES metric_definition(metric_key),
    measured_on    TEXT    NOT NULL,
    value          REAL    NOT NULL,
    -- Free text so the protocol travels with the number (step test vs 1.5-mile, which hand,
    -- which device). Comparing two protocols as one series would be a silent data error.
    method         TEXT,
    source         TEXT    NOT NULL DEFAULT 'user'
                   CHECK (source IN ('user', 'clinician', 'device')),
    note           TEXT,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_measurement_metric ON measurement(metric_key, measured_on);

CREATE TRIGGER measurement_no_update BEFORE UPDATE ON measurement
BEGIN SELECT RAISE(ABORT, 'append-only: measurement rows cannot be updated'); END;
CREATE TRIGGER measurement_no_delete BEFORE DELETE ON measurement
BEGIN SELECT RAISE(ABORT, 'append-only: measurement rows cannot be deleted'); END;
