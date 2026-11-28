-- 0088_constraint_supersession — let a constraint change, or end, without editing it.
--
-- `athlete_constraint` stays append-only (its no-update and no-delete triggers are unchanged).
-- A rule that changed, or an injury that resolved, is recorded as a *new* row that points at
-- the one it supersedes:
--
--   * `supersedes_constraint_id` — the row this one replaces, NULL for an original.
--   * `retired` — 1 marks a tombstone: the chain ends here and it contributes no rule. A
--     retirement with no replacement (an injury that settled) needs no invented successor,
--     which is why it is a flag rather than a "replaced by" reference.
--
-- A row is current when it is not retired and no other row supersedes it. Every pre-0088 row
-- is `retired = 0` with no successor, so nothing in an existing database changes meaning.
--
-- The partial unique index makes a chain linear: one row can be superseded once. A second
-- successor to the same row is a fork the read path could not resolve, so it is refused here
-- rather than guessed at later.
--
-- Read-time resolution uses the athlete's declared dates (`since`, `settled_on`), not the
-- write timestamp. A constraint recorded today that says `since: 2026-11-28` leaves an
-- earlier date alone; one with no `since` is read as always in force (DEC-STATE-04).

BEGIN IMMEDIATE;

ALTER TABLE athlete_constraint ADD COLUMN supersedes_constraint_id INTEGER
    REFERENCES athlete_constraint(constraint_id);

ALTER TABLE athlete_constraint ADD COLUMN retired INTEGER NOT NULL DEFAULT 0
    CHECK (retired IN (0, 1));

CREATE UNIQUE INDEX idx_constraint_superseded_once
    ON athlete_constraint(supersedes_constraint_id)
    WHERE supersedes_constraint_id IS NOT NULL;

COMMIT;
