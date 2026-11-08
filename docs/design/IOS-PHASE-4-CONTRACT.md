# iOS Phase 4 — reliable capture and offline support

**Status:** approved by the owner on 2026-11-08; implementation in progress. Chunk 1 (server
performed/finish timestamps) and Chunk 2 (durable snapshot/outbox foundation) are implemented;
client capture/replay chunks remain. This contract is
the authoritative Phase 4 specification. Phase 4 does not start offline prescriptions, offline
readiness scoring, plan editing or HealthKit imports.

## 1. Goal

After a workout has been started online with a server-issued plan, the iPhone must not lose
performed work during a network drop, server restart, app termination or a gym dead spot.

The phone may cache the active workout and queue:

- add set;
- form rating;
- finish.

The server remains authoritative. Queued work is labelled pending and is not represented as
server-accepted until its receipt is acknowledged.

## 2. Scope and exclusions

In scope:

- durable local active-workout snapshot;
- durable, ordered outbox for add set, form rating and finish;
- local temporary identities for offline sets;
- local cancellation of an unsynced add or form rating;
- queued finish with local finish timestamp;
- pending/synced/failed/conflict states;
- ordered, at-most-once replay using the existing server receipts;
- explicit conflict handling with no silent merge.

Out of scope:

- offline readiness entry or scoring;
- offline prescription request or workout start;
- offline plan editing (R8 stays online-only);
- offline HealthKit import;
- corrections/removals of already-synced sets (Phase 4 supports cancellation only before an
  unsynced operation is sent);
- background synchronization;
- a generic sync framework or a server-side queue table.

## 3. Owner decisions

Confirmed 2026-11-08:

1. Preserve the actual local finish time and duration; replay must not use the reconnect time.
2. Preserve each queued set's original performed timestamp for audit.
3. Allow cancellation of an unsynced locally-added set.
4. Finish locks the local workout; an unsent finish may be cancelled before any part of it is sent.
5. A cached in-progress workout may be used offline after relaunch; the server decides whether it
   is still active on reconnect.
6. Conflicts are visible and actionable: retry, keep local, or discard with confirmation. Never
   silently merge or attach work to another workout.
7. Strict FIFO per workout; stop on the first blocking failure. Form-rating failure is
   non-blocking and does not prevent finish from being sent.
8. Sync triggers: launch/foreground, network recovery while open, and manual retry. No background
   sync.
9. Form ratings are in scope. Readiness, plan edits, prescription/start and HealthKit remain
   online-only.
10. Physical acceptance is required before closure.

## 4. Local model

### 4.1 Active-workout snapshot

The client persists the active workout returned by the server, including the plan, logged sets,
forms and start time. The snapshot is displayed while the server is unreachable, clearly labelled
as cached.

- A cached workout does not authorize a new session.
- A cached plan cannot issue a fresh prescription.
- On reconnect, the server's active-workout read wins. If the workout ended elsewhere, the cached
  capture remains visible but cannot be sent to that workout.

### 4.2 Outbox

One outbox belongs to the paired server/device and the active workout. Each entry stores:

- client operation UUID;
- kind: `addSet`, `rateForm`, `completeWorkout`;
- original encoded request body;
- target workout id;
- local creation time;
- optional local set id or local form id;
- state: pending, synced, failed, conflict;
- last error/conflict code.

Ordering is the append order. An unsynced local add gets a negative client-local set id; it is
never presented as a server `set_id`. A local cancellation removes that pending add before it is
sent. Once an entry has been sent, it is resolved by the server response, never by local deletion.

Capacity: one active workout, at most 128 pending operations, 30-day retention and a 28-day replay
window, matching the server receipt window. The active workout snapshot and outbox use iOS file
protection and are excluded from backup.

### 4.3 Finish

A queued finish records the local end timestamp, session RPE (or explicit not recorded), duration
and notes. It is appended after all pending sets/forms. It locks further local set/form capture.

- The local workout remains "finished locally, awaiting server" until acknowledgement.
- An unsent finish may be cancelled before any network attempt; cancellation unlocks the workout.
- A finish that has been sent is never locally discarded; a definitive server conflict is shown for
  resolution.

## 5. Server changes

No queue table or migration is required for the outbox itself.

- `POST /api/ios/v1/workouts/<id>/sets` accepts optional `performed_at` (ISO-8601). The server
  validates it is not before `started_at` and not in the future, and stores it as the set's audit
  timestamp. Training calculations continue to use values, not the timestamp.
- `POST /api/ios/v1/workouts/<id>/complete` accepts optional `ended_at` (ISO-8601). The server
  validates it is between the start and now; replay later keeps the original end time and computes
  measured duration from start to that timestamp. A supplied `duration_min` remains an explicit
  manual duration and wins as today.
- Existing idempotency receipts cover replay. No new server queue, no generic sync route and no
  schema change outside any additive timestamp column if implementation proves one is required.
- Rejected replay uses the existing stable useful error codes; no automatic overwrite or merge.

## 6. Sync and conflict policy

- Replay in FIFO order with the original operation UUID and exact body.
- A 2xx acknowledges and removes the entry; transport/5xx retry with bounded backoff.
- A definitive 4xx removes a non-blocking form rating if it is unusable, while preserving the
  error as visible metadata; it does not block finish.
- A definitive failure on an add set or finish stops later replay and shows the operation as
  failed/conflict.
- If the server has no active workout, a different active workout, a completed/abandoned workout,
  or a changed plan that invalidates the target, the app must not guess. It keeps the local work
  visible and offers retry, keep/export and discard-with-confirmation.
- If the app relaunches offline, the cached workout/outbox is restored before any network read.
- If the server read succeeds, the server active-workout state wins for authorization; pending
  local work remains explicit until replayed.

## 7. Client states

The active workout shows:

- cached/pending banner when not server-confirmed;
- pending set/rating count;
- syncing, failed and conflict states;
- retry/discard actions with confirmation;
- finish-locally state when finish is queued.

No local pending item is displayed as a completed server session.

## 8. Tests and acceptance

Automated:

- outbox persistence, ordering, cap, retention, encryption/backup-exclusion settings;
- offline add/form/finish after relaunch;
- cancellation of unsynced add and unsent finish;
- ordered replay, at-most-once receipt replay, partial failure and conflict;
- performed_at and ended_at validation;
- no queued operation is silently dropped or attached to a different workout;
- online-only start/prescription/plan edit/HealthKit remain unavailable offline.

Physical acceptance:

- airplane mode / server stop with an active workout;
- add sets and a form rating, force-quit, relaunch and confirm local capture;
- reconnect and verify ordered, exactly-once server receipt;
- finish offline, reconnect, verify actual end time/duration and session materialization;
- visible conflict for an ended-elsewhere/other-active-workout case;
- no readiness/prescription/plan-edit/HealthKit path is presented as offline-capable.

Phase 4 is not closed until the physical acceptance is owner-confirmed.

## 9. Rollback

Disable the client offline capture surface and delete the local snapshot/outbox. The server's
additive timestamp handling can remain backward-compatible; no queued server rows exist. Existing
server-authoritative sessions and receipts remain valid.

## 10. References

- [IOS-CLIENT-PLAN.md](../IOS-CLIENT-PLAN.md) §Phase 4.
- [IOS-PHASE-2-CONTRACT.md](IOS-PHASE-2-CONTRACT.md).
- [IOS-R7-CONTRACT.md](IOS-R7-CONTRACT.md).
- [IOS-R8-CONTRACT.md](IOS-R8-CONTRACT.md).
