-- 0082_readiness_entry_open_field — storage follows the readiness registry.
--
-- The readiness registry can add an enabled metric without a code change, so readiness_entry
-- must store any validated field key instead of a closed CHECK list. Validation now lives in
-- the request/registry layer (enabled metrics plus bodyweight/wearable); this table only
-- guarantees the append-only history and the row shape. No rows are dropped.

BEGIN IMMEDIATE;

CREATE TABLE readiness_entry_new (
    entry_id    TEXT PRIMARY KEY,
    on_date     TEXT NOT NULL,
    field       TEXT NOT NULL,
    value       REAL NOT NULL,
    source      TEXT NOT NULL CHECK (source IN ('manual', 'import', 'preset')),
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    note        TEXT
);
INSERT INTO readiness_entry_new (
    entry_id, on_date, field, value, source, recorded_at, note
)
SELECT entry_id, on_date, field, value, source, recorded_at, note
  FROM readiness_entry;
DROP TABLE readiness_entry;
ALTER TABLE readiness_entry_new RENAME TO readiness_entry;
CREATE INDEX idx_readiness_entry_date ON readiness_entry(on_date, field, recorded_at);
CREATE TRIGGER readiness_entry_no_update BEFORE UPDATE ON readiness_entry
BEGIN SELECT RAISE(ABORT, 'append-only: readiness_entry rows cannot be updated'); END;
CREATE TRIGGER readiness_entry_no_delete BEFORE DELETE ON readiness_entry
BEGIN SELECT RAISE(ABORT, 'append-only: readiness_entry rows cannot be deleted'); END;

COMMIT;
