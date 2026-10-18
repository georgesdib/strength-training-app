-- 0005_symptom_log_append — allow more than one entry per day/timing.
--
-- 0003 gave symptom_log a UNIQUE (logged_on, timing) constraint. That contradicts the
-- append-only rule: a correction, or a second reading on the same day, would have to edit the
-- existing row. SQLite cannot drop a constraint in place, so the table is rebuilt.
--
-- Selection is latest-row-wins, same as every other append-only table.

CREATE TABLE symptom_log_new (
    log_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_on           TEXT    NOT NULL,
    timing              TEXT    NOT NULL
                        CHECK (timing IN ('pre_session', 'post_session', 'next_morning')),
    region              TEXT    NOT NULL,
    level               INTEGER NOT NULL CHECK (level BETWEEN 0 AND 3),
    settled_within_48h  INTEGER CHECK (settled_within_48h IN (0, 1)),
    note                TEXT,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

INSERT INTO symptom_log_new (
    log_id, logged_on, timing, region, level, settled_within_48h, note, created_at
)
SELECT log_id, logged_on, timing, region, level, settled_within_48h, note, created_at
  FROM symptom_log;

DROP TABLE symptom_log;
ALTER TABLE symptom_log_new RENAME TO symptom_log;

CREATE INDEX idx_symptom_date ON symptom_log(logged_on);

CREATE TRIGGER symptom_log_no_update BEFORE UPDATE ON symptom_log
BEGIN SELECT RAISE(ABORT, 'append-only: symptom_log rows cannot be updated'); END;
CREATE TRIGGER symptom_log_no_delete BEFORE DELETE ON symptom_log
BEGIN SELECT RAISE(ABORT, 'append-only: symptom_log rows cannot be deleted'); END;
