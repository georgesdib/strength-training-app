-- 0030_session_history — audited corrections for completed sessions.
--
-- clean_set stays append-only. An edit inserts a new clean_set row with supersedes_id pointing
-- at the old row; a removal inserts a tombstone with voided=1. Readers use the current row:
-- NOT EXISTS a child AND voided=0.

ALTER TABLE clean_set ADD COLUMN voided INTEGER NOT NULL DEFAULT 0;
ALTER TABLE session ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0;
ALTER TABLE session ADD COLUMN edited_at TEXT;

CREATE TABLE session_edit (
    edit_id     TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES session(session_id),
    edited_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    reason      TEXT,
    before_json TEXT NOT NULL,
    after_json  TEXT NOT NULL
);

CREATE INDEX idx_session_edit_session ON session_edit(session_id, edited_at);

CREATE TRIGGER session_edit_no_update BEFORE UPDATE ON session_edit
BEGIN SELECT RAISE(ABORT, 'append-only: session_edit rows cannot be updated'); END;
CREATE TRIGGER session_edit_no_delete BEFORE DELETE ON session_edit
BEGIN SELECT RAISE(ABORT, 'append-only: session_edit rows cannot be deleted'); END;
