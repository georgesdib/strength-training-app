-- 0045_session_productivity — add the optional 1-5 productivity item.
--
-- SQLite cannot alter the existing CHECK on session_feedback. A bare ADD COLUMN would allow
-- the column but still reject a productivity-only row, so this migration rebuilds the table.
-- Every existing row, id, timestamp, trigger and index is preserved; productivity is NULL for
-- pre-migration rows and is not a workload or prescription input.

DROP TRIGGER session_feedback_no_update;
DROP TRIGGER session_feedback_no_delete;

ALTER TABLE session_feedback RENAME TO session_feedback_old;

CREATE TABLE session_feedback (
    feedback_id  TEXT    PRIMARY KEY,
    session_id   TEXT    NOT NULL REFERENCES session(session_id),
    srpe         REAL    CHECK (srpe IS NULL OR (srpe >= 1 AND srpe <= 10)),
    duration_min REAL    CHECK (duration_min IS NULL OR (duration_min > 0 AND duration_min <= 600)),
    productivity INTEGER CHECK (productivity IS NULL OR (productivity >= 1 AND productivity <= 5)),
    note         TEXT,
    recorded_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (srpe IS NOT NULL OR duration_min IS NOT NULL OR note IS NOT NULL
           OR productivity IS NOT NULL)
);

INSERT INTO session_feedback
    (feedback_id, session_id, srpe, duration_min, productivity, note, recorded_at)
SELECT feedback_id, session_id, srpe, duration_min, NULL, note, recorded_at
FROM session_feedback_old;

DROP TABLE session_feedback_old;

CREATE INDEX idx_session_feedback_session ON session_feedback(session_id, recorded_at);

CREATE TRIGGER session_feedback_no_update BEFORE UPDATE ON session_feedback
BEGIN SELECT RAISE(ABORT, 'append-only: session_feedback rows cannot be updated'); END;
CREATE TRIGGER session_feedback_no_delete BEFORE DELETE ON session_feedback
BEGIN SELECT RAISE(ABORT, 'append-only: session_feedback rows cannot be deleted'); END;
