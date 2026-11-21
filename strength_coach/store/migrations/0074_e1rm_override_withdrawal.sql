-- 0074_e1rm_override_withdrawal — append-only tombstone for a manual e1RM override.
--
-- A withdrawal is a dated record, not a delete: from effective_from onward the override no
-- longer supplies the load basis, and the engine falls back to the formula estimate. Dates
-- before that keep the override the prescription was built with.
--
-- The table is append-only for the same reason as e1rm_override: a prescription cites
-- e1rm_override:<id>, so deleting the override would leave that citation dangling. A later
-- override appended after a withdrawal wins by effective date and created_at; see
-- docs/DATA-MODEL.md.
--
-- Roll back by dropping the table; the lookup treats a missing row as no withdrawal.

CREATE TABLE e1rm_override_withdrawal (
    withdrawal_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id    TEXT    NOT NULL,
    effective_from TEXT    NOT NULL,
    reason         TEXT    NOT NULL CHECK (length(trim(reason)) > 0),
    source         TEXT    NOT NULL DEFAULT 'user'
                   CHECK (source IN ('user', 'clinician')),
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_e1rm_override_withdrawal_lookup
    ON e1rm_override_withdrawal(exercise_id, effective_from);

CREATE TRIGGER e1rm_override_withdrawal_no_update
BEFORE UPDATE ON e1rm_override_withdrawal
BEGIN SELECT RAISE(ABORT, 'append-only: e1rm_override_withdrawal rows cannot be updated'); END;
CREATE TRIGGER e1rm_override_withdrawal_no_delete
BEFORE DELETE ON e1rm_override_withdrawal
BEGIN SELECT RAISE(ABORT, 'append-only: e1rm_override_withdrawal rows cannot be deleted'); END;
