-- 0003_athlete_state — DATA-MODEL section 11: goals, constraints, suitability, metrics, symptoms.
--
-- Why this exists: user goals, injuries and preferences must be STATE, not prompt text. A hard
-- constraint stored here vetoes a proposed exercise deterministically, whatever an agent says
-- (AGENTS.md §3.11). Until this migration, an empty relationship was indistinguishable from
-- "no constraint", which is exactly the ambiguity section 3.11 forbids.
--
-- Naming: the spec calls the table `constraint`, which is a reserved SQL keyword, so it is
-- `athlete_constraint` here. The rename is recorded in DATA-MODEL section 11.2.
--
-- All five tables are append-only: a profile change, a re-rating of an exercise, or a
-- correction to a constraint is a NEW row. Queries read the latest row.

CREATE TABLE athlete_profile (
    profile_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    effective_from          TEXT    NOT NULL,
    effective_to            TEXT,
    primary_goal            TEXT    NOT NULL
                            CHECK (primary_goal IN ('strength', 'hypertrophy', 'body_comp',
                                                    'pain_free', 'longevity', 'competition')),
    goal_rank               TEXT    NOT NULL DEFAULT '[]',
    focus_lifts             TEXT    NOT NULL DEFAULT '[]',
    competition_date        TEXT,
    sessions_per_week_target INTEGER,
    max_session_minutes     INTEGER,
    -- Week 1 of the current block, as the athlete declared it. Never inferred (DEC-RAMP-01);
    -- a reset inserts a new row and restarts the ramp at week 1 (DEC-RAMP-02).
    block_start_date        TEXT,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE athlete_constraint (
    constraint_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                TEXT    NOT NULL
                        CHECK (kind IN ('injury', 'contraindication', 'mobility', 'asymmetry')),
    region              TEXT    NOT NULL,
    severity            TEXT    NOT NULL
                        CHECK (severity IN ('hard_exclude', 'caution', 'monitor')),
    forbidden_patterns  TEXT    NOT NULL DEFAULT '[]',
    forbidden_exercises TEXT    NOT NULL DEFAULT '[]',
    rom_limit           TEXT,
    since               TEXT,
    settled_on          TEXT,
    evidence            TEXT,
    source              TEXT    CHECK (source IN ('user', 'clinician')),
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE exercise_suitability (
    exercise_id TEXT    NOT NULL,
    rated_on    TEXT    NOT NULL,
    can_do      INTEGER NOT NULL CHECK (can_do IN (0, 1)),
    will_do     INTEGER NOT NULL CHECK (will_do IN (0, 1)),
    feels_bad   INTEGER NOT NULL CHECK (feels_bad IN (0, 1)),
    note        TEXT,
    source      TEXT    CHECK (source IN ('user', 'observed')),
    PRIMARY KEY (exercise_id, rated_on)
);

CREATE TABLE metric_definition (
    metric_key        TEXT PRIMARY KEY,
    label             TEXT NOT NULL,
    scale_min         REAL,
    scale_max         REAL,
    -- Mandatory: the documented trap is "stress 5 = good". A metric with no declared direction
    -- is rejected rather than assumed to be higher-is-better.
    higher_is_better  INTEGER NOT NULL CHECK (higher_is_better IN (0, 1)),
    aggregation       TEXT NOT NULL CHECK (aggregation IN ('mean', 'max', 'best_of_3', 'last')),
    unit              TEXT,
    source            TEXT,
    active_from       TEXT
);

CREATE TABLE symptom_log (
    log_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_on           TEXT    NOT NULL,
    timing              TEXT    NOT NULL
                        CHECK (timing IN ('pre_session', 'post_session', 'next_morning')),
    region              TEXT    NOT NULL,
    level               INTEGER NOT NULL CHECK (level BETWEEN 0 AND 3),
    settled_within_48h  INTEGER CHECK (settled_within_48h IN (0, 1)),
    note                TEXT,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (logged_on, timing)
);

CREATE INDEX idx_athlete_profile_from ON athlete_profile(effective_from);
CREATE INDEX idx_constraint_severity   ON athlete_constraint(severity);
CREATE INDEX idx_suitability_exercise  ON exercise_suitability(exercise_id, rated_on);
CREATE INDEX idx_symptom_date          ON symptom_log(logged_on);

CREATE TRIGGER athlete_profile_no_update BEFORE UPDATE ON athlete_profile
BEGIN SELECT RAISE(ABORT, 'append-only: athlete_profile rows cannot be updated'); END;
CREATE TRIGGER athlete_profile_no_delete BEFORE DELETE ON athlete_profile
BEGIN SELECT RAISE(ABORT, 'append-only: athlete_profile rows cannot be deleted'); END;

CREATE TRIGGER athlete_constraint_no_update BEFORE UPDATE ON athlete_constraint
BEGIN SELECT RAISE(ABORT, 'append-only: athlete_constraint rows cannot be updated'); END;
CREATE TRIGGER athlete_constraint_no_delete BEFORE DELETE ON athlete_constraint
BEGIN SELECT RAISE(ABORT, 'append-only: athlete_constraint rows cannot be deleted'); END;

CREATE TRIGGER exercise_suitability_no_update BEFORE UPDATE ON exercise_suitability
BEGIN SELECT RAISE(ABORT, 'append-only: exercise_suitability rows cannot be updated'); END;
CREATE TRIGGER exercise_suitability_no_delete BEFORE DELETE ON exercise_suitability
BEGIN SELECT RAISE(ABORT, 'append-only: exercise_suitability rows cannot be deleted'); END;

CREATE TRIGGER metric_definition_no_update BEFORE UPDATE ON metric_definition
BEGIN SELECT RAISE(ABORT, 'append-only: metric_definition rows cannot be updated'); END;
CREATE TRIGGER metric_definition_no_delete BEFORE DELETE ON metric_definition
BEGIN SELECT RAISE(ABORT, 'append-only: metric_definition rows cannot be deleted'); END;

CREATE TRIGGER symptom_log_no_update BEFORE UPDATE ON symptom_log
BEGIN SELECT RAISE(ABORT, 'append-only: symptom_log rows cannot be updated'); END;
CREATE TRIGGER symptom_log_no_delete BEFORE DELETE ON symptom_log
BEGIN SELECT RAISE(ABORT, 'append-only: symptom_log rows cannot be deleted'); END;
