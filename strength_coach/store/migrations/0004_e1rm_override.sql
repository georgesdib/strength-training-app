-- 0004_e1rm_override — a manual e1RM that outranks the computed estimate.
--
-- Why: a tested single, a post-layoff starting point, or a case where the formula disagrees
-- with reality. An override is athlete STATE, not prompt text (AGENTS.md §3.11), so the
-- deterministic layer can use it and cite it.
--
-- Append-only: changing an override inserts a new row. Selection is the latest row whose
-- effective window contains the prescription date; `expires_on` makes an override temporary,
-- which is what a post-layoff re-entry needs.

CREATE TABLE e1rm_override (
    override_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id    TEXT    NOT NULL,
    e1rm_kg        REAL    NOT NULL CHECK (e1rm_kg > 0),
    effective_from TEXT    NOT NULL,
    expires_on     TEXT,
    reason         TEXT,
    source         TEXT    NOT NULL DEFAULT 'user'
                   CHECK (source IN ('user', 'measured', 'clinician')),
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (expires_on IS NULL OR expires_on >= effective_from)
);

CREATE INDEX idx_e1rm_override_lookup ON e1rm_override(exercise_id, effective_from);

CREATE TRIGGER e1rm_override_no_update BEFORE UPDATE ON e1rm_override
BEGIN SELECT RAISE(ABORT, 'append-only: e1rm_override rows cannot be updated'); END;
CREATE TRIGGER e1rm_override_no_delete BEFORE DELETE ON e1rm_override
BEGIN SELECT RAISE(ABORT, 'append-only: e1rm_override rows cannot be deleted'); END;
