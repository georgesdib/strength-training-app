-- 0086_symptom_characters — describe a reading, without changing what it measures.
--
-- `symptom_log` keeps its 0-3 severity scale and the existing append-only triggers. This
-- migration adds description only:
--
--   * `side` is one optional value per reading (left / right / bilateral / central). It is
--     validated at the write boundary against config/symptoms.v1.yaml. SQLite cannot read
--     YAML, and copying the list into a CHECK here would create a second source of truth
--     that silently disagrees the first time a value is added.
--
--   * `symptom_character` attaches any number of character ids to one reading. A character is
--     a label the athlete chose, not a diagnosis and not a trigger: no rule, signal or deload
--     policy reads it (DEC-SYMPTOM-05). Kept in a child table rather than a delimited string
--     so the read path can group and filter without parsing.
--
-- Append-only: a correction is a new parent reading (latest wins per date/timing/region),
-- never an edit to this row or its characters.

ALTER TABLE symptom_log ADD COLUMN side TEXT;

CREATE TABLE symptom_character (
    log_id       INTEGER NOT NULL REFERENCES symptom_log(log_id),
    character_id TEXT    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (log_id, character_id)
);

-- The history view filters by character ("show what I logged as tingling"), so the child
-- table needs its own read index.
CREATE INDEX idx_symptom_character_id ON symptom_character(character_id);

CREATE TRIGGER symptom_character_no_update BEFORE UPDATE ON symptom_character
BEGIN SELECT RAISE(ABORT, 'append-only: symptom_character rows cannot be updated'); END;

CREATE TRIGGER symptom_character_no_delete BEFORE DELETE ON symptom_character
BEGIN SELECT RAISE(ABORT, 'append-only: symptom_character rows cannot be deleted'); END;
