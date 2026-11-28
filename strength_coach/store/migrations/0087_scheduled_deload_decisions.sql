-- 0087_scheduled_deload_decisions -- persist event-scoped owner decisions.
--
-- A deferral is consumed by the issuance that proceeds without the scheduled deload.
-- Reconsideration is therefore eligible on the next distinct issuance, not after a timer.

BEGIN IMMEDIATE;

CREATE TABLE scheduled_deload_decision (
    decision_id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id                       TEXT    NOT NULL,
    schedule_anchor                TEXT    NOT NULL,
    window_starts_on               TEXT    NOT NULL,
    window_ends_on                 TEXT    NOT NULL,
    decision                       TEXT    NOT NULL
                                           CHECK (decision IN ('accepted', 'deferred', 'dismissed')),
    decided_at                     TEXT    NOT NULL,
    operation_id                   TEXT    NOT NULL UNIQUE,
    consumed_by_issuance_id        TEXT    NOT NULL,
    reconsider_after_issuance_id   TEXT,
    CHECK (date(schedule_anchor) IS NOT NULL AND date(schedule_anchor) = schedule_anchor),
    CHECK (date(window_starts_on) IS NOT NULL AND date(window_starts_on) = window_starts_on),
    CHECK (date(window_ends_on) IS NOT NULL AND date(window_ends_on) = window_ends_on),
    CHECK (window_ends_on >= window_starts_on),
    CHECK (
        (
            decision = 'deferred'
            AND reconsider_after_issuance_id = consumed_by_issuance_id
        )
        OR (decision <> 'deferred' AND reconsider_after_issuance_id IS NULL)
    )
);

CREATE INDEX idx_scheduled_deload_decision_event
    ON scheduled_deload_decision(event_id, decision_id);

CREATE TRIGGER scheduled_deload_decision_no_update
BEFORE UPDATE ON scheduled_deload_decision
BEGIN SELECT RAISE(ABORT, 'append-only: scheduled_deload_decision rows cannot be updated'); END;

CREATE TRIGGER scheduled_deload_decision_no_delete
BEFORE DELETE ON scheduled_deload_decision
BEGIN SELECT RAISE(ABORT, 'append-only: scheduled_deload_decision rows cannot be deleted'); END;

COMMIT;
