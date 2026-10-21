-- 0013_session_feedback — optional session RPE and session length, entered at review.
--
-- Why this exists: the export has no timestamps, so duration and session RPE cannot be
-- derived from sets. Volume load and hard-set counts can be derived; perceived effort
-- cannot, and session RPE is a validated internal-load measure for resistance training.
--
-- Why optional: no model reads it yet. It is captured for a future fatigue model and for
-- the athlete's own review; a missing value is unknown, never zero.
--
-- Append-only: a correction is a new row; the latest row per session wins at read time.

CREATE TABLE session_feedback (
    feedback_id  TEXT    PRIMARY KEY,
    session_id   TEXT    NOT NULL REFERENCES session(session_id),
    srpe         REAL    CHECK (srpe IS NULL OR (srpe >= 1 AND srpe <= 10)),
    duration_min REAL    CHECK (duration_min IS NULL OR (duration_min > 0 AND duration_min <= 600)),
    note         TEXT,
    recorded_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (srpe IS NOT NULL OR duration_min IS NOT NULL OR note IS NOT NULL)
);

CREATE INDEX idx_session_feedback_session ON session_feedback(session_id, recorded_at);

CREATE TRIGGER session_feedback_no_update BEFORE UPDATE ON session_feedback
BEGIN SELECT RAISE(ABORT, 'append-only: session_feedback rows cannot be updated'); END;
CREATE TRIGGER session_feedback_no_delete BEFORE DELETE ON session_feedback
BEGIN SELECT RAISE(ABORT, 'append-only: session_feedback rows cannot be deleted'); END;
