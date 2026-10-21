-- 0011_cardio_log — cardio sessions as a separate exposure from resistance training.
--
-- Why a separate table: cardio is not a strength session. It has its own duration, heart
-- rate, RPE and (later) training impulse, and a single "session" row would force it into the
-- strength shape. Append-only, like every other observation: a correction is a new row.
--
-- Capture first (ROADMAP §4.13). No fatigue model reads this yet; the columns are the data
-- such a model would need, so adding the model later does not require a second migration.

CREATE TABLE cardio_log (
    entry_id      TEXT    PRIMARY KEY,
    performed_on  TEXT    NOT NULL,
    -- Free text so a new modality is data, not a migration. Examples: walk, run, bike,
    -- row, intervals, swim, hike.
    modality      TEXT    NOT NULL,
    duration_s    INTEGER NOT NULL CHECK (duration_s > 0),
    avg_hr        INTEGER CHECK (avg_hr BETWEEN 30 AND 230),
    max_hr        INTEGER CHECK (max_hr BETWEEN 30 AND 250),
    distance_m    REAL    CHECK (distance_m IS NULL OR distance_m >= 0),
    -- Session RPE, 1-10 (Borg CR10). The fallback impulse input when HR is absent.
    srpe          INTEGER CHECK (srpe BETWEEN 1 AND 10),
    note          TEXT,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- A device can report average HR above max in bad data; refuse the contradiction rather
    -- than storing something no summary can interpret.
    CHECK (avg_hr IS NULL OR max_hr IS NULL OR avg_hr <= max_hr)
);

CREATE INDEX idx_cardio_date ON cardio_log(performed_on, created_at);

CREATE TRIGGER cardio_log_no_update BEFORE UPDATE ON cardio_log
BEGIN SELECT RAISE(ABORT, 'append-only: cardio_log rows cannot be updated'); END;
CREATE TRIGGER cardio_log_no_delete BEFORE DELETE ON cardio_log
BEGIN SELECT RAISE(ABORT, 'append-only: cardio_log rows cannot be deleted'); END;
