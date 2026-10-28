-- 0042_shadow_decision — append-only record of what a reactive signal would have done.
--
-- Shadow mode is only reviewable if the proposal and its inputs are durable. A prescription's
-- notes are recomputed, so they cannot hold this (DEC-SHADOW-01). Nothing here changes a
-- prescription; applied stays 0 until an explicit activation decision.

CREATE TABLE shadow_decision (
    decision_id      TEXT PRIMARY KEY,
    evaluated_on     TEXT NOT NULL,
    component        TEXT NOT NULL CHECK (component IN ('exposure', 'residual', 'substitution')),
    rule_id          TEXT NOT NULL,
    signal_json      TEXT NOT NULL DEFAULT '{}',
    catalogue_digest TEXT,
    config_digest    TEXT,
    proposed_json    TEXT NOT NULL DEFAULT '{}',
    reason           TEXT NOT NULL DEFAULT '',
    action           TEXT NOT NULL CHECK (action IN
                        ('none', 'trim_sets', 'suggest_substitution', 'advisory')),
    applied          INTEGER NOT NULL DEFAULT 0 CHECK (applied IN (0, 1)),
    prescription_id  TEXT REFERENCES prescription(prescription_id),
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_shadow_decision_date ON shadow_decision(evaluated_on, component);

CREATE TRIGGER shadow_decision_no_update BEFORE UPDATE ON shadow_decision
BEGIN SELECT RAISE(ABORT, 'append-only: shadow_decision rows cannot be updated'); END;
CREATE TRIGGER shadow_decision_no_delete BEFORE DELETE ON shadow_decision
BEGIN SELECT RAISE(ABORT, 'append-only: shadow_decision rows cannot be deleted'); END;
