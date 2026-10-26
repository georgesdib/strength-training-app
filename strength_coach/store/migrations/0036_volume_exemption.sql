-- 0036_volume_exemption — the sets a safety or recovery rule removed from a week.
--
-- The weekly volume budget must not re-add volume that readiness, deload, a spinal trim or a
-- constraint removed (DEC-VOLUME-06). The prescription table carries no notes column, so the
-- amount and its source are recorded here, one row per prescription/pattern/source. Append-only:
-- a correction is a new row, never an update or a delete.

CREATE TABLE volume_exemption (
    exemption_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    prescription_id TEXT    NOT NULL REFERENCES prescription(prescription_id),
    effective_on    TEXT    NOT NULL,
    pattern         TEXT    NOT NULL,
    sets            INTEGER NOT NULL CHECK (sets > 0),
    source          TEXT    NOT NULL,
    recorded_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_volume_exemption_week ON volume_exemption(effective_on, pattern);

CREATE TRIGGER volume_exemption_no_update BEFORE UPDATE ON volume_exemption
BEGIN SELECT RAISE(ABORT, 'append-only: volume_exemption rows cannot be updated'); END;
CREATE TRIGGER volume_exemption_no_delete BEFORE DELETE ON volume_exemption
BEGIN SELECT RAISE(ABORT, 'append-only: volume_exemption rows cannot be deleted'); END;
