-- 0020_maintenance_review — periodic review reminders and their decisions.
--
-- A review is a human acknowledgement, not an automatic programme change. Rows are
-- append-only; the latest row per task is the current state. `snoozed_until` is used only by
-- the snooze action and never by a schedule calculation.

CREATE TABLE maintenance_review (
    review_id     TEXT PRIMARY KEY,
    task_key      TEXT NOT NULL,
    action        TEXT NOT NULL CHECK (action IN ('completed', 'snoozed')),
    decision      TEXT CHECK (decision IS NULL OR decision IN
                              ('kept', 'changed', 'insufficient', 'not_applicable')),
    note          TEXT,
    reviewed_on   TEXT NOT NULL,
    snoozed_until TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (action = 'completed' AND decision IS NOT NULL AND snoozed_until IS NULL)
        OR
        (action = 'snoozed' AND decision IS NULL AND snoozed_until IS NOT NULL)
    )
);

CREATE INDEX idx_maintenance_review_task
    ON maintenance_review(task_key, reviewed_on, review_id);

CREATE TRIGGER maintenance_review_no_update BEFORE UPDATE ON maintenance_review
BEGIN SELECT RAISE(ABORT, 'append-only: maintenance_review rows cannot be updated'); END;
CREATE TRIGGER maintenance_review_no_delete BEFORE DELETE ON maintenance_review
BEGIN SELECT RAISE(ABORT, 'append-only: maintenance_review rows cannot be deleted'); END;
