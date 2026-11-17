-- 0064_cardio_corpus — canonical HealthKit activity: workouts, samples, links, status, checkpoint.
--
-- Why a new domain rather than columns on cardio_log: cardio_log is a manual, append-only note
-- that a session happened; this corpus is machine-observed activity. A HealthKit workout is not a
-- training session (DEC-CARDIO-01), so it is never merged into `session`; reconciliation is an
-- explicit append-only link, and an unmatched workout stays visible on its own.
--
-- Identity: one column, two sources (DEC-CARDIO-09). Rows promoted from an Apple Health export
-- carry a sha256 content key because the export has no sample UUIDs; rows from the app carry the
-- HealthKit object UUID. The timeline is split at history_cutoff (DEC-CARDIO-18), so the two
-- never have to reconcile.
--
-- Deletion is an event (DEC-CARDIO-04): a workout absent from a later query is a status row, never
-- a delete. Nothing here is device-scoped: the same workout re-uploaded from a re-paired phone must
-- collapse onto one key.

BEGIN IMMEDIATE;

CREATE TABLE external_workout (
    external_workout_id TEXT PRIMARY KEY,              -- uuid4 hex
    external_key        TEXT NOT NULL UNIQUE,          -- HK UUID, or sha256 over activity|start|end|bundle|duration
    origin              TEXT NOT NULL CHECK (origin IN ('export', 'healthkit')),
    activity_type       TEXT NOT NULL,                 -- raw HKWorkoutActivityType, retained verbatim
    started_at          TEXT NOT NULL,                 -- UTC ISO-8601
    ended_at            TEXT NOT NULL,
    timezone            TEXT,                          -- HKTimeZone when present; local-day attribution
    duration_s          INTEGER NOT NULL CHECK (duration_s > 0),
    source_name         TEXT NOT NULL,                 -- provenance, never identity
    source_bundle_id    TEXT,
    source_version      TEXT,
    device              TEXT,
    -- Summary statistics the metrics read. Canonical units: seconds, metres, kJ, bpm.
    avg_heart_rate      INTEGER CHECK (avg_heart_rate BETWEEN 30 AND 230),
    max_heart_rate      INTEGER CHECK (max_heart_rate BETWEEN 30 AND 250),
    active_energy_kj    REAL CHECK (active_energy_kj >= 0),
    distance_m          REAL CHECK (distance_m >= 0),
    avg_mets            REAL CHECK (avg_mets > 0),
    imported_at         TEXT NOT NULL,
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    CHECK (started_at < ended_at),
    CHECK (avg_heart_rate IS NULL OR max_heart_rate IS NULL OR avg_heart_rate <= max_heart_rate),
    CHECK (length(external_key) BETWEEN 16 AND 128),
    CHECK (length(metadata_json) <= 65536)
);

CREATE INDEX idx_external_workout_started ON external_workout(started_at);
CREATE INDEX idx_external_workout_activity ON external_workout(activity_type, started_at);

CREATE TABLE health_sample (
    sample_key          TEXT PRIMARY KEY,              -- HK UUID, or sha256 over kind|sampled_at|value|bundle
    external_workout_id TEXT REFERENCES external_workout(external_workout_id),
    kind                TEXT NOT NULL CHECK (kind IN ('heart_rate', 'cycling_power', 'running_power')),
    sampled_at          TEXT NOT NULL,                 -- UTC ISO-8601
    value               REAL NOT NULL,
    unit                TEXT NOT NULL,
    -- 'tail' is the post-workout window kept for heart-rate recovery; 'none' is a sample with no
    -- workout. A sample is associated or it is not — the two fields must agree.
    association         TEXT NOT NULL DEFAULT 'none'
                        CHECK (association IN ('workout', 'tail', 'none')),
    source_name         TEXT NOT NULL,
    source_bundle_id    TEXT,
    imported_at         TEXT NOT NULL,
    CHECK ((association = 'none' AND external_workout_id IS NULL)
        OR (association <> 'none' AND external_workout_id IS NOT NULL)),
    CHECK (kind <> 'heart_rate' OR (value BETWEEN 20 AND 260))
);

CREATE INDEX idx_health_sample_workout ON health_sample(external_workout_id, sampled_at);
CREATE INDEX idx_health_sample_kind ON health_sample(kind, sampled_at);

CREATE TABLE workout_link (
    link_id             TEXT PRIMARY KEY,
    external_workout_id TEXT NOT NULL REFERENCES external_workout(external_workout_id),
    session_id          TEXT NOT NULL REFERENCES session(session_id),
    -- Links are events: 'unlink' names the link it retires, so the current state is the latest
    -- event per pair and no row is ever rewritten.
    action              TEXT NOT NULL CHECK (action IN ('link', 'unlink')),
    method              TEXT NOT NULL
                        CHECK (method IN ('explicit', 'interval_overlap', 'day_containment', 'manual')),
    band_version        TEXT NOT NULL,                 -- e.g. 'link_v1'
    confidence          REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    supersedes_id       TEXT REFERENCES workout_link(link_id),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((action = 'link' AND supersedes_id IS NULL)
        OR (action = 'unlink' AND supersedes_id IS NOT NULL))
);

CREATE INDEX idx_workout_link_workout ON workout_link(external_workout_id, created_at);
CREATE INDEX idx_workout_link_session ON workout_link(session_id, created_at);

CREATE TABLE external_status_event (
    event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    external_workout_id TEXT NOT NULL REFERENCES external_workout(external_workout_id),
    status              TEXT NOT NULL CHECK (status IN (
                            'absent_from_source', 'source_unavailable', 'access_unconfirmed',
                            'partial_result', 'confirmed_deleted', 'reappeared'
                        )),
    detail              TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_external_status_workout
    ON external_status_event(external_workout_id, event_id);

-- The single mutable row set in this domain: ingestion checkpoints (history_cutoff and the
-- anchored-query state). Deliberately not append-only — a checkpoint is operational state, not
-- history, and a stale anchor must be replaceable without inventing a new table.
CREATE TABLE cardio_sync_state (
    name        TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TRIGGER external_workout_no_update BEFORE UPDATE ON external_workout
BEGIN SELECT RAISE(ABORT, 'append-only: external_workout rows cannot be updated'); END;
CREATE TRIGGER external_workout_no_delete BEFORE DELETE ON external_workout
BEGIN SELECT RAISE(ABORT, 'append-only: external_workout rows cannot be deleted'); END;

CREATE TRIGGER health_sample_no_update BEFORE UPDATE ON health_sample
BEGIN SELECT RAISE(ABORT, 'append-only: health_sample rows cannot be updated'); END;
CREATE TRIGGER health_sample_no_delete BEFORE DELETE ON health_sample
BEGIN SELECT RAISE(ABORT, 'append-only: health_sample rows cannot be deleted'); END;

CREATE TRIGGER workout_link_no_update BEFORE UPDATE ON workout_link
BEGIN SELECT RAISE(ABORT, 'append-only: workout_link rows cannot be updated'); END;
CREATE TRIGGER workout_link_no_delete BEFORE DELETE ON workout_link
BEGIN SELECT RAISE(ABORT, 'append-only: workout_link rows cannot be deleted'); END;

CREATE TRIGGER external_status_event_no_update BEFORE UPDATE ON external_status_event
BEGIN SELECT RAISE(ABORT, 'append-only: external_status_event rows cannot be updated'); END;
CREATE TRIGGER external_status_event_no_delete BEFORE DELETE ON external_status_event
BEGIN SELECT RAISE(ABORT, 'append-only: external_status_event rows cannot be deleted'); END;

-- VO₂max is a periodic outcome, not daily state (DEC-CARDIO-06): it belongs in `measurement`
-- beside body-fat and steps, where metric_definition already declares direction, unit and
-- aggregation. These two columns are additive; no existing row is touched.
--
-- external_id exists because measurement_id is a fresh uuid per insert, so a re-import of 399
-- HealthKit VO₂max samples would otherwise duplicate silently. The partial unique index is the
-- same pattern as high_intensity_exposure (0024).
ALTER TABLE measurement ADD COLUMN external_id TEXT;
ALTER TABLE measurement ADD COLUMN measured_at TEXT;

CREATE UNIQUE INDEX idx_measurement_external
    ON measurement(external_id)
    WHERE external_id IS NOT NULL;

COMMIT;
