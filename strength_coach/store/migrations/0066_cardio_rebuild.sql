-- 0066_cardio_rebuild — clear the corpus rows written by a duplicated upload, then re-derive.
--
-- Why a destructive reset: the phone's first sync applied the seven-day lookback to workouts as
-- well as samples, so three workouts that predate history_cutoff were uploaded again under their
-- HealthKit UUIDs. They now duplicate rows that the export already provided under content keys,
-- and their samples duplicate too.
--
-- The corpus is derived data: every row can be recreated from export.xml, and the only row that
-- cannot (the 17 Nov 2026 session uploaded from the phone) is re-sent by the app on its next sync.
-- This migration empties the tables so the promotion can rebuild them. The append-only triggers
-- are dropped and immediately restored inside this transaction: they are what forbid a DELETE, and
-- leaving them off would be a silent change to the table's contract.
--
-- This is not a precedent for editing history. It is a rebuild of reproducible derived rows after a
-- defect in the writer, recorded here so the empty corpus has an explanation.

BEGIN IMMEDIATE;

DROP TRIGGER external_workout_no_update;
DROP TRIGGER external_workout_no_delete;
DROP TRIGGER health_sample_no_update;
DROP TRIGGER health_sample_no_delete;
DROP TRIGGER workout_link_no_update;
DROP TRIGGER workout_link_no_delete;
DROP TRIGGER external_status_event_no_update;
DROP TRIGGER external_status_event_no_delete;

-- Order matters: the classification cache and the link events reference the workouts they
-- describe, so children go first.
DELETE FROM cardio_classification;
DELETE FROM workout_link;
DELETE FROM external_status_event;
DELETE FROM health_sample;
DELETE FROM external_workout;
DELETE FROM cardio_cache_state;
DELETE FROM cardio_sync_state;

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

COMMIT;
