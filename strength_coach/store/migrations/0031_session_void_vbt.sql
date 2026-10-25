-- 0031_session_void_vbt — whole-session void/unvoid and VBT overrides.
--
-- A void is an append-only event plus a mutable operational flag. Set/rep VBT overrides are
-- append-only values that can fill a missing number or supersede a device value.

ALTER TABLE session ADD COLUMN voided INTEGER NOT NULL DEFAULT 0;
ALTER TABLE session ADD COLUMN voided_at TEXT;
ALTER TABLE session ADD COLUMN void_reason TEXT;

CREATE TABLE session_void (
    event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES session(session_id),
    action     TEXT NOT NULL CHECK (action IN ('void', 'unvoid')),
    reason     TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_session_void_session ON session_void(session_id, event_id);
CREATE TRIGGER session_void_no_update BEFORE UPDATE ON session_void
BEGIN SELECT RAISE(ABORT, 'append-only: session_void rows cannot be updated'); END;
CREATE TRIGGER session_void_no_delete BEFORE DELETE ON session_void
BEGIN SELECT RAISE(ABORT, 'append-only: session_void rows cannot be deleted'); END;

CREATE TABLE vbt_override (
    override_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES session(session_id),
    set_id       INTEGER NOT NULL REFERENCES clean_set(set_id),
    rep_index    INTEGER,
    velocity_mps REAL NOT NULL CHECK (velocity_mps > 0),
    source       TEXT NOT NULL CHECK (source IN ('manual', 'device')),
    supersedes_id INTEGER REFERENCES vbt_override(override_id),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (rep_index IS NULL OR rep_index > 0)
);
CREATE INDEX idx_vbt_override_set ON vbt_override(set_id, rep_index, override_id);
CREATE TRIGGER vbt_override_no_update BEFORE UPDATE ON vbt_override
BEGIN SELECT RAISE(ABORT, 'append-only: vbt_override rows cannot be updated'); END;
CREATE TRIGGER vbt_override_no_delete BEFORE DELETE ON vbt_override
BEGIN SELECT RAISE(ABORT, 'append-only: vbt_override rows cannot be deleted'); END;
