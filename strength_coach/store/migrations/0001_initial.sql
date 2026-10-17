-- 0001_initial — the v0 schema, per docs/DATA-MODEL.md sections 1-10.
--
-- Two conventions hold across every table:
--
--   * `created_at` is set by the store (a column DEFAULT), never by a caller, so a
--     backfilled row cannot claim to be older than it is.
--   * Artifacts are append-only. Triggers below refuse UPDATE and DELETE on every
--     immutable table, which is stricter than a convention: a correction must insert a
--     new row with `supersedes_id`, and the old row stays visible.
--
-- `session` and `run` are deliberately mutable: a session is derived from clean_set and
-- is recomputed when sets are added, and a run's `finished_at`/`status` are written when
-- it ends. Neither is an "artifact" in the DEC sense.

CREATE TABLE raw_row (
    raw_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name   TEXT    NOT NULL CHECK (table_name IN ('training', 'readiness')),
    source_row   INTEGER NOT NULL,
    file_sha256  TEXT    NOT NULL,
    payload      TEXT    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- Identity is (which file, which line). NOT content: DQ-DUP-01 says identical
    -- repeated training rows are real sets, so they must never collapse into one row.
    UNIQUE (table_name, source_row, file_sha256)
);

CREATE TABLE session (
    session_id        TEXT    PRIMARY KEY,
    occurred_on       TEXT    NOT NULL,
    workout_label     TEXT,
    set_count         INTEGER NOT NULL,
    working_set_count INTEGER NOT NULL DEFAULT 0,
    exercise_count    INTEGER NOT NULL,
    main_lifts        TEXT    NOT NULL DEFAULT '[]',
    day_guess         TEXT    NOT NULL DEFAULT 'unknown'
                      CHECK (day_guess IN ('A', 'B', 'C', 'unknown')),
    day_confidence    REAL    NOT NULL DEFAULT 0.0,
    -- Why the day was assigned or left unknown. Stored so "do not force a bucket" is
    -- auditable rather than an unexplained unknown.
    day_reason        TEXT,
    tonnage_kg        REAL,
    duration_min      REAL,
    duration_basis    TEXT    NOT NULL DEFAULT 'unavailable'
                      CHECK (duration_basis IN ('measured', 'unavailable')),
    flags             TEXT    NOT NULL DEFAULT '[]',
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at        TEXT
);

CREATE TABLE clean_set (
    set_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_id            INTEGER NOT NULL REFERENCES raw_row(raw_id),
    session_id        TEXT    NOT NULL REFERENCES session(session_id),
    occurred_on       TEXT    NOT NULL,
    exercise_id       TEXT    NOT NULL,
    raw_exercise      TEXT,
    load_kg           REAL,
    load_basis        TEXT    NOT NULL
                      CHECK (load_basis IN ('external', 'bodyweight_total', 'added', 'unknown')),
    external_load_kg  REAL,
    reps              INTEGER,
    reps_unit         TEXT    NOT NULL CHECK (reps_unit IN ('reps', 'seconds')),
    rir               INTEGER,
    -- 'logged_warmup' is DEC-RIR-01's marker: the value was logged, but it labels a
    -- warm-up rather than an effort level, so it must stay distinguishable.
    rir_source        TEXT    CHECK (rir_source IN ('logged', 'logged_warmup', 'assumed_default', 'missing')),
    velocity_mps      REAL,
    velocity_present  INTEGER NOT NULL CHECK (velocity_present IN (0, 1)),
    power_w           REAL,
    rom_mm            REAL,
    tut_s             REAL,
    form_score        INTEGER,
    -- Nullable on purpose: weight x reps on a plank or a pull-up is meaningless and
    -- must never be summed into tonnage (DATA-MODEL section 2).
    tonnage_kg        REAL,
    is_working_set    INTEGER NOT NULL CHECK (is_working_set IN (0, 1)),
    flags             TEXT    NOT NULL DEFAULT '[]',
    supersedes_id     INTEGER REFERENCES clean_set(set_id),
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- One canonical set per source line. Re-importing the same export is therefore a
    -- no-op rather than a duplicate, while two genuinely repeated sets (different
    -- source_row) stay two rows.
    UNIQUE (raw_id)
);

CREATE TABLE quarantine (
    quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_id        INTEGER NOT NULL REFERENCES raw_row(raw_id),
    reason        TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (raw_id)
);

CREATE TABLE readiness_day (
    on_date            TEXT PRIMARY KEY,
    sleep              INTEGER,
    energy             INTEGER,
    mood               INTEGER,
    soreness           INTEGER,
    stress             INTEGER,
    nutrition          INTEGER,
    hydration          INTEGER,
    squat_readiness    INTEGER,
    bench_readiness    INTEGER,
    deadlift_readiness INTEGER,
    hrv_ms             REAL,
    rhr_bpm            REAL,
    bodyweight_kg      REAL,
    fat_pct            REAL,
    composite          REAL,
    composite_basis    TEXT,
    merge_note         TEXT,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE vbt_calibration (
    calibration_id  TEXT    PRIMARY KEY,
    exercise_id     TEXT,
    vbt_family      TEXT,
    scope           TEXT    NOT NULL CHECK (scope IN ('lift', 'family', 'global_prior')),
    rep_count       INTEGER NOT NULL,
    rir_low         INTEGER NOT NULL,
    rir_high        INTEGER NOT NULL,
    velocity_median REAL,
    velocity_mad    REAL,
    velocity_low    REAL,
    velocity_high   REAL,
    n_sets          INTEGER NOT NULL,
    n_sessions      INTEGER NOT NULL,
    window_start    TEXT,
    window_end      TEXT,
    method_version  TEXT    NOT NULL,
    params_json     TEXT    NOT NULL,
    source          TEXT    NOT NULL DEFAULT 'computed'
                    CHECK (source IN ('computed', 'override')),
    override_reason TEXT,
    valid_from      TEXT,
    valid_until     TEXT,
    supersedes_id   TEXT REFERENCES vbt_calibration(calibration_id),
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- An override without a reason is an unexplained number, so it is rejected.
    CHECK (source <> 'override' OR (override_reason IS NOT NULL AND override_reason <> ''))
);

CREATE TABLE rule_document (
    document_id    TEXT NOT NULL,
    version        TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    source_hash    TEXT NOT NULL,
    body_yaml      TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- Rules are immutable: a change is a NEW version, never an edit of this one.
    PRIMARY KEY (document_id, version)
);

CREATE TABLE rule (
    rule_id                    TEXT NOT NULL,
    document_id                TEXT NOT NULL,
    document_version           TEXT NOT NULL,
    severity                   TEXT NOT NULL
                               CHECK (severity IN ('veto', 'downgrade', 'warn', 'advisory')),
    scope                      TEXT,
    check_fn                   TEXT,
    citations                  TEXT NOT NULL DEFAULT '[]',
    depends_on_data_decisions  TEXT NOT NULL DEFAULT '[]',
    body_json                  TEXT NOT NULL DEFAULT '{}',
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (rule_id, document_id, document_version),
    FOREIGN KEY (document_id, document_version)
        REFERENCES rule_document(document_id, version)
);

CREATE TABLE prescription (
    prescription_id       TEXT PRIMARY KEY,
    run_id                TEXT NOT NULL REFERENCES run(run_id),
    for_date              TEXT NOT NULL,
    session_day           TEXT NOT NULL CHECK (session_day IN ('A', 'B', 'C')),
    fallback_level        TEXT NOT NULL
                          CHECK (fallback_level IN ('full', 'fatigue_reduced', 'llm_downgraded')),
    rule_document_version TEXT,
    calibration_ids       TEXT NOT NULL DEFAULT '[]',
    approved_by           TEXT NOT NULL CHECK (approved_by IN ('deterministic', 'llm+policy')),
    supersedes_id         TEXT REFERENCES prescription(prescription_id),
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE prescription_item (
    item_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    prescription_id    TEXT    NOT NULL REFERENCES prescription(prescription_id),
    order_index        INTEGER NOT NULL,
    exercise_id        TEXT    NOT NULL,
    sets               INTEGER NOT NULL,
    reps_low           INTEGER,
    reps_high          INTEGER,
    load_kg            REAL,
    load_basis         TEXT    NOT NULL,
    rounding_increment REAL,
    rir_target         INTEGER,
    velocity_target    REAL,
    vbt_basis          TEXT,
    rest_s             INTEGER,
    time_cap_s         INTEGER,
    essential          INTEGER NOT NULL DEFAULT 1 CHECK (essential IN (0, 1)),
    rationale_refs     TEXT    NOT NULL DEFAULT '[]',
    substitution_for   TEXT,
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (prescription_id, order_index)
);

CREATE TABLE critique (
    critique_id TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES run(run_id),
    session_id  TEXT REFERENCES session(session_id),
    narrative   TEXT,
    facts_hash  TEXT NOT NULL,
    supersedes_id TEXT REFERENCES critique(critique_id),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE rubric_score (
    score_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    critique_id    TEXT    NOT NULL REFERENCES critique(critique_id),
    item           TEXT    NOT NULL,
    score          REAL,
    weight         REAL,
    evidence_refs  TEXT    NOT NULL DEFAULT '[]',
    rule_ids       TEXT    NOT NULL DEFAULT '[]',
    -- 0 means "the data cannot support this metric". Such a row carries no score rather
    -- than a guessed one (DATA-MODEL section 9).
    measurable     INTEGER NOT NULL CHECK (measurable IN (0, 1)),
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (critique_id, item),
    CHECK (measurable = 1 OR score IS NULL)
);

CREATE TABLE run (
    run_id       TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    input_hash   TEXT NOT NULL,
    code_version TEXT NOT NULL,
    config_hash  TEXT,
    window_start TEXT,
    window_end   TEXT,
    llm_model    TEXT,
    llm_tokens   INTEGER,
    status       TEXT NOT NULL DEFAULT 'ok'
                 CHECK (status IN ('ok', 'llm_failed', 'llm_downgraded', 'error'))
);

CREATE TABLE run_event (
    run_id     TEXT    NOT NULL REFERENCES run(run_id),
    seq        INTEGER NOT NULL,
    kind       TEXT    NOT NULL
               CHECK (kind IN ('input', 'feature', 'tool_call', 'llm_output',
                               'policy_verdict', 'artifact')),
    payload    TEXT    NOT NULL DEFAULT '{}',
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (run_id, seq)
);

CREATE INDEX idx_clean_set_session   ON clean_set(session_id);
CREATE INDEX idx_clean_set_exercise  ON clean_set(exercise_id);
CREATE INDEX idx_clean_set_date      ON clean_set(occurred_on);
CREATE INDEX idx_clean_set_working   ON clean_set(is_working_set);
CREATE INDEX idx_quarantine_reason   ON quarantine(reason);
CREATE INDEX idx_session_date        ON session(occurred_on);
CREATE INDEX idx_vbt_lookup          ON vbt_calibration(exercise_id, rep_count, scope);
CREATE INDEX idx_run_event_kind      ON run_event(run_id, kind);

-- --- append-only guards ----------------------------------------------------
-- A trigger, not a convention: an UPDATE here is a bug in the caller, and failing loudly
-- is the only way an append-only store stays append-only.
CREATE TRIGGER raw_row_no_update BEFORE UPDATE ON raw_row
BEGIN SELECT RAISE(ABORT, 'append-only: raw_row rows cannot be updated'); END;

CREATE TRIGGER raw_row_no_delete BEFORE DELETE ON raw_row
BEGIN SELECT RAISE(ABORT, 'append-only: raw_row rows cannot be deleted'); END;

CREATE TRIGGER clean_set_no_update BEFORE UPDATE ON clean_set
BEGIN SELECT RAISE(ABORT, 'append-only: clean_set rows cannot be updated'); END;

CREATE TRIGGER clean_set_no_delete BEFORE DELETE ON clean_set
BEGIN SELECT RAISE(ABORT, 'append-only: clean_set rows cannot be deleted'); END;

CREATE TRIGGER quarantine_no_update BEFORE UPDATE ON quarantine
BEGIN SELECT RAISE(ABORT, 'append-only: quarantine rows cannot be updated'); END;

CREATE TRIGGER quarantine_no_delete BEFORE DELETE ON quarantine
BEGIN SELECT RAISE(ABORT, 'append-only: quarantine rows cannot be deleted'); END;

CREATE TRIGGER vbt_calibration_no_update BEFORE UPDATE ON vbt_calibration
BEGIN SELECT RAISE(ABORT, 'append-only: vbt_calibration rows cannot be updated'); END;

CREATE TRIGGER vbt_calibration_no_delete BEFORE DELETE ON vbt_calibration
BEGIN SELECT RAISE(ABORT, 'append-only: vbt_calibration rows cannot be deleted'); END;

CREATE TRIGGER rule_document_no_update BEFORE UPDATE ON rule_document
BEGIN SELECT RAISE(ABORT, 'append-only: rule_document rows cannot be updated'); END;

CREATE TRIGGER rule_document_no_delete BEFORE DELETE ON rule_document
BEGIN SELECT RAISE(ABORT, 'append-only: rule_document rows cannot be deleted'); END;

CREATE TRIGGER rule_no_update BEFORE UPDATE ON rule
BEGIN SELECT RAISE(ABORT, 'append-only: rule rows cannot be updated'); END;

CREATE TRIGGER rule_no_delete BEFORE DELETE ON rule
BEGIN SELECT RAISE(ABORT, 'append-only: rule rows cannot be deleted'); END;

CREATE TRIGGER prescription_no_update BEFORE UPDATE ON prescription
BEGIN SELECT RAISE(ABORT, 'append-only: prescription rows cannot be updated'); END;

CREATE TRIGGER prescription_no_delete BEFORE DELETE ON prescription
BEGIN SELECT RAISE(ABORT, 'append-only: prescription rows cannot be deleted'); END;

CREATE TRIGGER prescription_item_no_update BEFORE UPDATE ON prescription_item
BEGIN SELECT RAISE(ABORT, 'append-only: prescription_item rows cannot be updated'); END;

CREATE TRIGGER prescription_item_no_delete BEFORE DELETE ON prescription_item
BEGIN SELECT RAISE(ABORT, 'append-only: prescription_item rows cannot be deleted'); END;

CREATE TRIGGER critique_no_update BEFORE UPDATE ON critique
BEGIN SELECT RAISE(ABORT, 'append-only: critique rows cannot be updated'); END;

CREATE TRIGGER critique_no_delete BEFORE DELETE ON critique
BEGIN SELECT RAISE(ABORT, 'append-only: critique rows cannot be deleted'); END;

CREATE TRIGGER rubric_score_no_update BEFORE UPDATE ON rubric_score
BEGIN SELECT RAISE(ABORT, 'append-only: rubric_score rows cannot be updated'); END;

CREATE TRIGGER rubric_score_no_delete BEFORE DELETE ON rubric_score
BEGIN SELECT RAISE(ABORT, 'append-only: rubric_score rows cannot be deleted'); END;

CREATE TRIGGER run_event_no_update BEFORE UPDATE ON run_event
BEGIN SELECT RAISE(ABORT, 'append-only: run_event rows cannot be updated'); END;

CREATE TRIGGER run_event_no_delete BEFORE DELETE ON run_event
BEGIN SELECT RAISE(ABORT, 'append-only: run_event rows cannot be deleted'); END;
