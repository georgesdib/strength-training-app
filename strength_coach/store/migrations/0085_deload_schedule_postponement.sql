-- 0085_deload_schedule_postponement -- an append-only re-anchor for the scheduled deload clock.
--
-- Keep this separate from athlete_profile.block_start_date: that date also anchors programme
-- context. A declared break after a postponement supersedes the shifted schedule as before.

CREATE TABLE scheduled_deload_postponement (
    postponement_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id    TEXT    NOT NULL UNIQUE,
    recorded_on     TEXT    NOT NULL,
    postponed_until TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (date(recorded_on) IS NOT NULL AND date(recorded_on) = recorded_on),
    CHECK (date(postponed_until) IS NOT NULL AND date(postponed_until) = postponed_until),
    CHECK (postponed_until > recorded_on)
);

CREATE INDEX idx_scheduled_deload_postponement_recorded
    ON scheduled_deload_postponement(recorded_on, postponement_id);

CREATE TRIGGER scheduled_deload_postponement_no_update
BEFORE UPDATE ON scheduled_deload_postponement
BEGIN SELECT RAISE(ABORT, 'append-only: scheduled_deload_postponement rows cannot be updated'); END;

CREATE TRIGGER scheduled_deload_postponement_no_delete
BEFORE DELETE ON scheduled_deload_postponement
BEGIN SELECT RAISE(ABORT, 'append-only: scheduled_deload_postponement rows cannot be deleted'); END;
