-- 0035_declared_break — holiday, deload and test weeks that must not advance the cycle.
--
-- A declared break freezes the trained-week cycle and the erector ramp for its duration
-- (ROADMAP 4.6, DEC-CONTINUITY-04). It changes no load, RIR or set: the gap rules still apply
-- when training resumes. Rows are append-only; a mistake is cancelled by a new row that names
-- the row it cancels, never by an update or a delete.

CREATE TABLE declared_break (
    break_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    starts_on        TEXT    NOT NULL,
    ends_on          TEXT    NOT NULL,
    reason           TEXT    NOT NULL,
    note             TEXT,
    cancels_break_id INTEGER REFERENCES declared_break(break_id),
    recorded_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (ends_on >= starts_on)
);
CREATE INDEX idx_declared_break_dates ON declared_break(starts_on, ends_on);

CREATE TRIGGER declared_break_no_update BEFORE UPDATE ON declared_break
BEGIN SELECT RAISE(ABORT, 'append-only: declared_break rows cannot be updated'); END;
CREATE TRIGGER declared_break_no_delete BEFORE DELETE ON declared_break
BEGIN SELECT RAISE(ABORT, 'append-only: declared_break rows cannot be deleted'); END;
