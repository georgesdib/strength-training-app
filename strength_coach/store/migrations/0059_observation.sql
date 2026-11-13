-- 0059_observation — AFC-3 append-only longitudinal observations.
--
-- One row per rendered observation, keyed by a deterministic id over family, window, gate, n
-- and the AFC evidence id. Re-requesting the same observation is a no-op; changed evidence
-- appends a new row instead of rewriting the old one. Abstentions are never stored: a session
-- that cannot support a claim simply has no row.
--
-- Nothing in the training engine reads this table. DEC-AFC-04.

BEGIN IMMEDIATE;

CREATE TABLE observation (
    observation_id TEXT PRIMARY KEY,
    family         TEXT NOT NULL CHECK (family IN ('rir', 'incomplete_work', 'vbt')),
    window_start   TEXT NOT NULL,
    window_end     TEXT NOT NULL,
    gate           TEXT NOT NULL CHECK (gate IN ('signal', 'evaluation')),
    n              INTEGER NOT NULL CHECK (n >= 0),
    evidence_id    TEXT NOT NULL,
    payload_json   TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (window_start <= window_end),
    CHECK (length(payload_json) <= 65536)
);

CREATE INDEX idx_observation_family_created
    ON observation(family, created_at);

CREATE TRIGGER observation_no_update BEFORE UPDATE ON observation
BEGIN SELECT RAISE(ABORT, 'append-only: observation rows cannot be updated'); END;

CREATE TRIGGER observation_no_delete BEFORE DELETE ON observation
BEGIN SELECT RAISE(ABORT, 'append-only: observation rows cannot be deleted'); END;

COMMIT;
