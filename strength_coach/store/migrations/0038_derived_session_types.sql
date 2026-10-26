-- 0038_derived_session_types — allow volume_fill_<original> and technique sessions.
--
-- 9c-2 stores the derived session type as data (the schedule maps it back to its original
-- family). The old CHECK only allowed the four normal types, so both the prescription and the
-- materialised session must drop that CHECK. The values are validated in code
-- (prescribe/session_identity.py). Both tables are rebuilt because SQLite cannot alter a CHECK.

PRAGMA foreign_keys = OFF;

CREATE TABLE session_0038 (
    session_id        TEXT    PRIMARY KEY,
    occurred_on       TEXT    NOT NULL,
    workout_label     TEXT,
    set_count         INTEGER NOT NULL,
    working_set_count INTEGER NOT NULL DEFAULT 0,
    exercise_count    INTEGER NOT NULL,
    main_lifts        TEXT    NOT NULL DEFAULT '[]',
    tonnage_kg        REAL,
    duration_min      REAL,
    duration_basis    TEXT    NOT NULL DEFAULT 'unavailable'
                      CHECK (duration_basis IN ('measured', 'unavailable')),
    flags             TEXT    NOT NULL DEFAULT '[]',
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at        TEXT,
    prescription_id   TEXT,
    source            TEXT    NOT NULL DEFAULT 'import',
    workout_id        TEXT,
    session_rpe       REAL,
    session_rpe_recorded INTEGER NOT NULL DEFAULT 0
                      CHECK (session_rpe_recorded IN (0, 1)),
    session_type      TEXT    NOT NULL DEFAULT 'unknown',
    needs_review      INTEGER NOT NULL DEFAULT 0,
    edited_at         TEXT,
    voided            INTEGER NOT NULL DEFAULT 0,
    voided_at         TEXT,
    void_reason       TEXT
);
INSERT INTO session_0038 (
    session_id, occurred_on, workout_label, set_count, working_set_count, exercise_count,
    main_lifts, tonnage_kg, duration_min, duration_basis, flags, created_at, updated_at,
    prescription_id, source, workout_id, session_rpe, session_rpe_recorded, session_type,
    needs_review, edited_at, voided, voided_at, void_reason
)
SELECT
    session_id, occurred_on, workout_label, set_count, working_set_count, exercise_count,
    main_lifts, tonnage_kg, duration_min, duration_basis, flags, created_at, updated_at,
    prescription_id, source, workout_id, session_rpe, session_rpe_recorded, session_type,
    needs_review, edited_at, voided, voided_at, void_reason
FROM session;
DROP TABLE session;
ALTER TABLE session_0038 RENAME TO session;
CREATE INDEX idx_session_date ON session(occurred_on);
CREATE INDEX idx_session_type ON session(session_type);

DROP TRIGGER IF EXISTS prescription_no_update;
DROP TRIGGER IF EXISTS prescription_no_delete;
CREATE TABLE prescription_0038 (
    prescription_id       TEXT PRIMARY KEY,
    run_id                TEXT NOT NULL REFERENCES run(run_id),
    for_date              TEXT NOT NULL,
    fallback_level        TEXT NOT NULL
                          CHECK (fallback_level IN ('full', 'fatigue_reduced', 'llm_downgraded')),
    rule_document_version TEXT,
    calibration_ids       TEXT NOT NULL DEFAULT '[]',
    approved_by           TEXT NOT NULL CHECK (approved_by IN ('deterministic', 'llm+policy')),
    supersedes_id         TEXT REFERENCES prescription(prescription_id),
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    session_type          TEXT NOT NULL DEFAULT 'unknown'
);
INSERT INTO prescription_0038 (
    prescription_id, run_id, for_date, fallback_level, rule_document_version,
    calibration_ids, approved_by, supersedes_id, created_at, session_type
)
SELECT
    prescription_id, run_id, for_date, fallback_level, rule_document_version,
    calibration_ids, approved_by, supersedes_id, created_at, session_type
FROM prescription;
DROP TABLE prescription;
ALTER TABLE prescription_0038 RENAME TO prescription;
CREATE TRIGGER prescription_no_update BEFORE UPDATE ON prescription
BEGIN SELECT RAISE(ABORT, 'append-only: prescription rows cannot be updated'); END;
CREATE TRIGGER prescription_no_delete BEFORE DELETE ON prescription
BEGIN SELECT RAISE(ABORT, 'append-only: prescription rows cannot be deleted'); END;

PRAGMA foreign_keys = ON;
