-- Phase 2 iOS online strength workflow: issued plans and idempotency receipts.
--
-- The plan is built and persisted on the server; the phone starts it by id only and never
-- supplies prescription content. The normal prescription/prescription_item rows are written at
-- issue (see server.py), so an issued plan is auditable even if it is never started.
--
-- Additive only. Existing training, readiness, prescription, workout and review tables are
-- untouched. Rollback drops these two tables; prescriptions/workouts already committed by a
-- started session remain valid.

CREATE TABLE ios_issued_plan (
    issued_plan_id   TEXT PRIMARY KEY,          -- uuid4 hex
    device_id        TEXT NOT NULL REFERENCES ios_device(device_id),
    prescription_id  TEXT NOT NULL REFERENCES prescription(prescription_id),
    for_date         TEXT NOT NULL,             -- server-local YYYY-MM-DD
    session_type     TEXT NOT NULL,
    plan_json        TEXT NOT NULL,             -- exact plan shown to the client
    readiness_json   TEXT NOT NULL,             -- validated readiness values for workout.start
    readiness_ack    INTEGER NOT NULL DEFAULT 0 CHECK (readiness_ack IN (0, 1)),
    created_at       TEXT NOT NULL,             -- UTC ISO-8601
    expires_at       TEXT NOT NULL,             -- UTC ISO-8601
    consumed_at      TEXT,                      -- set atomically with workout creation
    superseded_at    TEXT,                      -- set when a newer issue replaces this plan
    workout_id       TEXT REFERENCES workout_session(workout_id)
);

-- One live, unstarted plan per device. Expired rows are superseded on the next issue before the
-- insert, so an expired-but-unstarted plan cannot block a new one.
CREATE UNIQUE INDEX idx_ios_issued_plan_live
    ON ios_issued_plan(device_id)
    WHERE consumed_at IS NULL AND superseded_at IS NULL;
CREATE INDEX idx_ios_issued_plan_device_created
    ON ios_issued_plan(device_id, created_at);
CREATE INDEX idx_ios_issued_plan_expires
    ON ios_issued_plan(expires_at);

CREATE TABLE ios_operation_receipt (
    device_id        TEXT NOT NULL REFERENCES ios_device(device_id),
    operation_id     TEXT NOT NULL,             -- normalized Idempotency-Key
    route            TEXT NOT NULL,
    request_hash     TEXT NOT NULL,             -- SHA-256 of canonical JSON body
    response_status  INTEGER NOT NULL,
    response_json    TEXT NOT NULL,
    created_at       TEXT NOT NULL,             -- UTC ISO-8601
    expires_at       TEXT NOT NULL,             -- UTC ISO-8601
    PRIMARY KEY (device_id, operation_id)
);

CREATE INDEX idx_ios_operation_receipt_expires
    ON ios_operation_receipt(expires_at);
