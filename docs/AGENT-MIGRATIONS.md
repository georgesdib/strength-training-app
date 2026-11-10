# Agent migrations — strength-training-app

Rules for schema changes and append-only records. Read ../AGENTS.md and
AGENT-WORKFLOWS.md first.

## 1. Core rules

- Prescriptions, critiques, calibrations, rule versions and workout events are append-only.
  Correct by appending a new row with a pointer; never update/delete history.
- Migration files are numbered, ordered and checksummed by strength_coach.store.db.
  Never edit an already-applied migration; add the next number.
- A migration must preserve all existing data. If SQLite forces a table rebuild, copy every
  legacy row with an explicit mapping and add a check that aborts on corrupt legacy data.
- Never run a migration against the live database as part of an agent task without explicit
  owner approval. Use a temporary database for tests.
- Never use destructive database/filesystem/Git operations without approval.
- Do not expose private data, live DB paths, pairing codes or tokens in migration tests or docs.

## 2. Schema design

- New tables are additive and namespaced to the domain.
- Use NOT NULL/CHECK/FK constraints where the domain requires them.
- Foreign keys should preserve audit history; avoid cascades that delete history.
- Add indexes for the read path: workout, event time, event type, set identity, device.
- Use triggers to enforce append-only tables where the schema promises it.
- Store device occurrence time separately from server receipt time when replay is possible.
- Keep canonical performed sets in their existing table; do not duplicate them from telemetry.
- New config/table semantics need a domain reason in docs, not only SQL comments.

## 3. Transactions and failure

- Multi-statement writes use strength_coach.store.db.transaction.
- A failed write leaves no partial state.
- Migration runner ordering/checksum failures must abort, not skip.
- Batch ingestion is all-or-nothing unless the API explicitly documents partial acceptance.
- Idempotency identities are unique and conflicts are explicit.

## 4. Tests a migration needs

At minimum, when the change warrants it:
1. Build a database at the previous schema, insert representative existing rows, apply the
   new migration, and assert old rows and counts are unchanged.
2. Assert new constraints/triggers/indexes exist and enforce their contract.
3. Assert a corrupt legacy row aborts the rebuild rather than disappearing.
4. Exercise the read path that depends on the new table.
5. Verify no e1RM, volume, prescription or existing API behaviour changed unless intended.

Run the focused migration test first, then the narrow dependent tests. Do not run the full
suite for a docs-only change.

## 5. Review checklist

- Is the migration number the next free number?
- Does it preserve every existing row?
- Are append-only promises enforced or explicitly documented?
- Are indexes justified by a query?
- Is original occurrence time separate from receipt time?
- Are rollback/forward-compatibility implications documented?
- Are private/live data excluded from tests?
- Is the API contract updated if the schema is exposed?

## 6. Rollback

Prefer forward-only migrations. If a rollback is necessary, document the exact inverse and
data-loss implications before executing it. Never silently drop columns/tables that hold
training history.
