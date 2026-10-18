-- 0002_rubric_mark — a human's rubric marks, append-only.
--
-- Calibration is a loop, not a one-off audit: every review adds rows, and the running
-- agreement report gets sharper as the set grows. A mark is never edited; a correction is a
-- new row, and the latest row per (session_id, item) is the one compared.
--
-- confidence records whether the marker actually remembers the session. A reconstructed mark
-- is kept for the record but excluded from the headline (DEC-EVAL-04).
--
-- rubric_version ties the mark to the rubric it was made against, so a future change to an
-- item's definition does not silently invalidate older marks.

CREATE TABLE rubric_mark (
    mark_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT    NOT NULL REFERENCES session(session_id),
    item           TEXT    NOT NULL,
    score          REAL    CHECK (score IS NULL OR (score >= 0 AND score <= 1)),
    confidence     TEXT    NOT NULL CHECK (confidence IN ('high', 'low', 'unknown')),
    rubric_version TEXT    NOT NULL,
    note           TEXT,
    marked_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_rubric_mark_session ON rubric_mark(session_id, item);
CREATE INDEX idx_rubric_mark_time    ON rubric_mark(marked_at);

CREATE TRIGGER rubric_mark_no_update BEFORE UPDATE ON rubric_mark
BEGIN SELECT RAISE(ABORT, 'append-only: rubric_mark rows cannot be updated'); END;

CREATE TRIGGER rubric_mark_no_delete BEFORE DELETE ON rubric_mark
BEGIN SELECT RAISE(ABORT, 'append-only: rubric_mark rows cannot be deleted'); END;
