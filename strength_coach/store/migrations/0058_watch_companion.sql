-- 0058_watch_companion — Phase 6.1: watch devices, execution target, ownership and idle.
--
-- Additive only. Existing rows become phone devices, phone-targeted plans and legacy
-- workouts with a NULL owner (the pre-ownership permissive behaviour). No row is deleted
-- and no training, prescription or receipt row changes.
--
-- The issued-plan live index becomes target-scoped: a plan requested by the phone for the
-- watch must be visible to the watch, and the watch is the row's executor. device_id stays
-- the requester for audit; target_device_id is the executor.

BEGIN IMMEDIATE;

ALTER TABLE ios_device
    ADD COLUMN kind TEXT NOT NULL DEFAULT 'phone'
    CHECK (kind IN ('phone', 'watch'));
ALTER TABLE ios_device
    ADD COLUMN parent_device_id TEXT REFERENCES ios_device(device_id);
ALTER TABLE ios_device
    ADD COLUMN credential_epoch INTEGER NOT NULL DEFAULT 0;

-- At most one active watch per parent phone; a revoked watch does not block its replacement.
CREATE UNIQUE INDEX idx_ios_device_active_watch
    ON ios_device(parent_device_id)
    WHERE kind = 'watch' AND revoked_at IS NULL;
CREATE INDEX idx_ios_device_parent
    ON ios_device(parent_device_id);

ALTER TABLE ios_issued_plan
    ADD COLUMN target_device_id TEXT REFERENCES ios_device(device_id);
ALTER TABLE ios_issued_plan
    ADD COLUMN execution_target TEXT NOT NULL DEFAULT 'phone'
    CHECK (execution_target IN ('phone', 'watch'));

-- Legacy plans were requested by, and executed on, the same device.
UPDATE ios_issued_plan
SET target_device_id = device_id
WHERE target_device_id IS NULL;

DROP INDEX idx_ios_issued_plan_live;
CREATE UNIQUE INDEX idx_ios_issued_plan_live
    ON ios_issued_plan(COALESCE(target_device_id, device_id))
    WHERE consumed_at IS NULL AND superseded_at IS NULL;

ALTER TABLE workout_session
    ADD COLUMN owner_device_id TEXT REFERENCES ios_device(device_id);
ALTER TABLE workout_session
    ADD COLUMN plan_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE workout_session
    ADD COLUMN last_activity_at TEXT;

-- Existing in-progress and finished sessions get the only activity time they have.
UPDATE workout_session
SET last_activity_at = started_at
WHERE last_activity_at IS NULL;

CREATE INDEX idx_workout_idle
    ON workout_session(status, last_activity_at);

COMMIT;
