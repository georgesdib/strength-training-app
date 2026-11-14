-- 0060_analytics_phase1 — derived-analytics revision ledger and build state.
--
-- Phase 1 of docs/design/DERIVED-ANALYTICS-ARCHITECTURE.md. No analytical data is materialised
-- here: the tables only record durable source revisions and the lifecycle of a family build.
--
-- analytics_revision is append-only and monotonically increasing. Every source mutation that can
-- change a derived family appends one row in the same transaction as the mutation; dependency and
-- methodology changes append a row with a config digest instead of a session.
--
-- analytics_build is the mutable lifecycle row per family: pending, running, ready, failed or
-- stale. A build may be published ready only when its processed revision, method version and
-- dependency fingerprint match the current database and code.

BEGIN IMMEDIATE;

CREATE TABLE analytics_revision (
    revision_id   INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN (
                      'workout_end', 'import', 'correction', 'void', 'unvoid',
                      'config', 'methodology')),
    session_id    TEXT,
    family        TEXT,
    config_digest TEXT,
    detail_json   TEXT NOT NULL DEFAULT '{}',
    recorded_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (kind NOT IN ('config', 'methodology') OR config_digest IS NOT NULL),
    CHECK (kind IN ('config', 'methodology') OR family IS NULL)
);

CREATE INDEX idx_analytics_revision_kind
    ON analytics_revision(kind, revision_id);

CREATE INDEX idx_analytics_revision_family
    ON analytics_revision(family, revision_id);

CREATE TRIGGER analytics_revision_no_update BEFORE UPDATE ON analytics_revision
BEGIN SELECT RAISE(ABORT, 'append-only: analytics_revision rows cannot be updated'); END;

CREATE TRIGGER analytics_revision_no_delete BEFORE DELETE ON analytics_revision
BEGIN SELECT RAISE(ABORT, 'append-only: analytics_revision rows cannot be deleted'); END;

CREATE TABLE analytics_build (
    family                 TEXT PRIMARY KEY,
    method_version         TEXT NOT NULL,
    dependency_fingerprint TEXT NOT NULL,
    status                 TEXT NOT NULL CHECK (status IN (
                               'pending', 'running', 'ready', 'failed', 'stale')),
    processed_revision     INTEGER NOT NULL DEFAULT 0 CHECK (processed_revision >= 0),
    source_revision        INTEGER NOT NULL DEFAULT 0 CHECK (source_revision >= 0),
    cursor                 TEXT,
    started_at             TEXT,
    finished_at            TEXT,
    last_published_at      TEXT,
    last_error             TEXT
);

COMMIT;
