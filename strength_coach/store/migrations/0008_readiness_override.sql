-- 0008_readiness_override — manual correction of a computed readiness score.
--
-- Overrides are per day and scope. The latest row for (effective_on, scope) wins. They are
-- append-only: correcting an override writes another row. Scope is 'global' or
-- 'category:<name>'. Value is 0.00-1.00, the same scale as the computed score.

CREATE TABLE readiness_override (
    override_id  TEXT    PRIMARY KEY,
    effective_on TEXT    NOT NULL,
    scope        TEXT    NOT NULL CHECK (scope = 'global' OR scope LIKE 'category:%'),
    value        REAL    NOT NULL CHECK (value BETWEEN 0.0 AND 1.0),
    reason       TEXT    NOT NULL,
    source       TEXT    NOT NULL DEFAULT 'user',
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_readiness_override_date ON readiness_override(effective_on, scope, created_at);

CREATE TRIGGER readiness_override_no_update BEFORE UPDATE ON readiness_override
BEGIN SELECT RAISE(ABORT, 'append-only: readiness_override rows cannot be updated'); END;
CREATE TRIGGER readiness_override_no_delete BEFORE DELETE ON readiness_override
BEGIN SELECT RAISE(ABORT, 'append-only: readiness_override rows cannot be deleted'); END;
