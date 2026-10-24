-- 0024_high_intensity_exposure — record near-max tests/attempts separately from volume.
--
-- A test or max attempt is an assessment/exposure, not a working set. This table gives it a
-- recovery context without changing the volume ledger. Rows are append-only; a correction is
-- a new row with supersedes_id.

CREATE TABLE high_intensity_exposure (
    exposure_id      TEXT PRIMARY KEY,
    performed_on     TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN
                       ('test', 'max_attempt', 'competition', 'unplanned', 'other')),
    exercise_id      TEXT,
    session_id       TEXT REFERENCES session(session_id),
    set_id           INTEGER,
    region_load      TEXT NOT NULL CHECK (region_load IN
                       ('upper', 'lower', 'axial', 'mixed', 'unknown')),
    intensity_class  TEXT NOT NULL CHECK (intensity_class IN
                       ('near_max', 'high', 'moderate', 'unknown')),
    axial_cost       INTEGER,
    novelty          TEXT NOT NULL DEFAULT 'unknown'
                       CHECK (novelty IN ('familiar', 'novel', 'unknown')),
    test_type        TEXT CHECK (test_type IS NULL OR test_type IN
                       ('1RM', '3RM', '5RM', 'other')),
    source           TEXT NOT NULL CHECK (source IN
                       ('test_record', 'set_link', 'manual')),
    source_id        TEXT,
    supersedes_id    TEXT REFERENCES high_intensity_exposure(exposure_id),
    note             TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (set_id IS NULL OR session_id IS NOT NULL)
);

CREATE INDEX idx_high_intensity_date
    ON high_intensity_exposure(performed_on, exposure_id);
CREATE UNIQUE INDEX idx_high_intensity_source
    ON high_intensity_exposure(source, source_id)
    WHERE source_id IS NOT NULL;

CREATE TRIGGER high_intensity_exposure_no_update
BEFORE UPDATE ON high_intensity_exposure
BEGIN SELECT RAISE(ABORT, 'append-only: high_intensity_exposure rows cannot be updated'); END;
CREATE TRIGGER high_intensity_exposure_no_delete
BEFORE DELETE ON high_intensity_exposure
BEGIN SELECT RAISE(ABORT, 'append-only: high_intensity_exposure rows cannot be deleted'); END;
