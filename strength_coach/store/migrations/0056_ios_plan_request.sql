-- 0056_ios_plan_request — the issued plan becomes a request-and-result row.
--
-- R7 makes prescription issue asynchronous: a request is queued, built by one bounded
-- dispatcher, and polled through GET /api/ios/v1/plans/current. That needs a status, two
-- separate deadlines (one for the build, one for starting) and a nullable prescription_id,
-- because the normal prescription is now written at start rather than at issue.
--
-- The rebuild is required: SQLite cannot relax the NOT NULL constraints on prescription_id,
-- plan_json, readiness_json and session_type in place. Every existing Phase 2 row is copied
-- with the mapping in docs/design/IOS-R7-CONTRACT.md §3.1: a legacy row was already built, so
-- it is 'ready'; expires_at is reused for both deadlines so a legacy plan neither gains nor
-- loses life; created_at stands in for the publish time because the real one was never
-- recorded. No legacy row is deleted, and prescription/receipt rows are untouched.
--
-- A corrupt legacy row aborts the whole rebuild (the CHECK/FK fails, db.migrate raises
-- MigrationError, and the transaction rolls back) rather than being silently dropped.

BEGIN IMMEDIATE;

CREATE TABLE ios_issued_plan_new (
    issued_plan_id          TEXT PRIMARY KEY,       -- uuid4 hex; also the request id
    device_id               TEXT NOT NULL REFERENCES ios_device(device_id),
    status                  TEXT NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued', 'building', 'ready', 'error', 'skipped')),
    requested_session_type  TEXT NOT NULL,          -- 'auto' or an explicit type
    session_type            TEXT,                   -- resolved type; NULL until ready
    settings_json           TEXT NOT NULL DEFAULT '{}',
    build_inputs_json       TEXT NOT NULL DEFAULT '{}',
    prescription_id         TEXT REFERENCES prescription(prescription_id),  -- set at start
    for_date                TEXT NOT NULL,          -- server-local YYYY-MM-DD
    plan_json               TEXT,                   -- exact plan; NULL until ready
    readiness_json          TEXT,                   -- validated readiness for workout.start
    readiness_ack           INTEGER NOT NULL DEFAULT 0 CHECK (readiness_ack IN (0, 1)),
    created_at              TEXT NOT NULL,          -- UTC ISO-8601
    building_started_at     TEXT,
    ready_at                TEXT,
    finished_at             TEXT,
    error_code              TEXT,
    error_message           TEXT,
    request_expires_at      TEXT NOT NULL,          -- created_at + plan_request_ttl_seconds
    plan_expires_at         TEXT,                   -- ready_at + issued_plan_ttl_seconds
    consumed_at             TEXT,                   -- set atomically with workout creation
    superseded_at           TEXT,                   -- newer request, or replaced live row
    workout_id              TEXT REFERENCES workout_session(workout_id),
    -- A workout link without consumption would mean the linkage was rewritten without the
    -- transaction that justifies it. Phase 2 never produced that state.
    CHECK (consumed_at IS NOT NULL OR workout_id IS NULL),
    -- A ready plan must carry everything start needs; a half-published row is a bug.
    CHECK (status <> 'ready' OR (
        plan_json IS NOT NULL AND readiness_json IS NOT NULL
        AND session_type IS NOT NULL AND plan_expires_at IS NOT NULL
    ))
);

INSERT INTO ios_issued_plan_new (
    issued_plan_id, device_id, status, requested_session_type, session_type,
    settings_json, build_inputs_json, prescription_id, for_date, plan_json,
    readiness_json, readiness_ack, created_at, building_started_at, ready_at,
    finished_at, error_code, error_message, request_expires_at, plan_expires_at,
    consumed_at, superseded_at, workout_id
)
SELECT
    issued_plan_id, device_id, 'ready', session_type, session_type,
    '{}', '{}', prescription_id, for_date, plan_json,
    readiness_json, readiness_ack, created_at, NULL, created_at,
    created_at, NULL, NULL, expires_at, expires_at,
    consumed_at, superseded_at, workout_id
FROM ios_issued_plan;

DROP TABLE ios_issued_plan;
ALTER TABLE ios_issued_plan_new RENAME TO ios_issued_plan;

-- One live, unstarted row per device, as before. A queued or building row is live too, which
-- is what makes a new request supersede an unfinished build.
CREATE UNIQUE INDEX idx_ios_issued_plan_live
    ON ios_issued_plan(device_id)
    WHERE consumed_at IS NULL AND superseded_at IS NULL;
CREATE INDEX idx_ios_issued_plan_device_created
    ON ios_issued_plan(device_id, created_at);
CREATE INDEX idx_ios_issued_plan_queue
    ON ios_issued_plan(status, request_expires_at);

COMMIT;
