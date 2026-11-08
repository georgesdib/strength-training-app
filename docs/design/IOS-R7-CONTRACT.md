# iOS R7 — Asynchronous prescription request with workout settings

**Status:** **approved and implemented 2026-11-08.** Migration `0056`, the bounded dispatcher
(`web/ios_plan_worker.py`), the asynchronous issue route, `GET /api/ios/v1/plans/current` and the
start-transaction prescription are on `development`. §17 records where the implementation differs
from the plan below; everything else here is current behaviour.

**Why R7 exists.** Phase 2 issues a prescription by calling `build_prescription` synchronously
inside the request handler ([server.py](../../strength_coach/web/server.py) `_ios_prescription`).
With Settings → Resolver enabled the build takes **35–46 s** on the ODROID-C4
([`PERFORMANCE-PROFILE.md`](../PERFORMANCE-PROFILE.md) §2), while the Swift client times out every
request at **10 s**. The phone therefore reports a transport failure for a request the server
completes successfully ~30 s later, leaves a pending journal entry, and blocks further mutations
until it is replayed. R7 removes the blocking call and adds the workout settings the owner asked
for. It supersedes and absorbs the deferred R2 (unstarted issued-plan recovery).

## 1. Scope

In scope:

- Optional workout settings before issuing a plan: session type, the minimum-session fallback
  and an optional top-set/back-off versus straight-set request.
- A non-blocking `POST /api/ios/v1/prescriptions` that returns immediately and builds in the
  background.
- Durable request state in the database, pollable from the app, surviving app exit, server restart
  and a lost response.
- Polling that continues past 60 s and completes normally for a 90 s build.
- A `GET /api/ios/v1/plans/current` recovery read (this is R2's scope).
- Persisting the normal prescription rows at **start**, not at issue.

Out of scope: offline capture (Phase 4), HealthKit changes, rubric/review screen, editing a plan
during a workout (that is [R8](IOS-R8-CONTRACT.md)), LLM selection, and any change to the training
methodology.

## 2. Owner decisions (2026-11-08)

1. **Amend the Phase 2 contract** to admit session-type and minimum-session as client-supplied
   prescription inputs. The Phase 2 clause "only `session_type = auto` exists" no longer holds.
2. **Share the existing CPU slot.** R7 uses the same `_CPU_JOB_SLOTS = Semaphore(1)` the web
   forecast/preview/prescribe jobs use. No second slot, no new concurrency budget.
3. **Generation check on completion.** A build that finishes after its request was superseded must
   not publish its plan.
4. **Persist the prescription at start, not at issue.** An unstarted ready plan is a preview, not a
   prescription. This reverses Phase 2 §8.2.
5. **Job state lives in the database**, not in a module-level dict.
6. **Polling is not capped at 60 s.** 60 s is a UI copy threshold only; a 90 s build completes
   normally.
7. **Foreground resumption is required.** Leaving and returning to the app must find and load a
   ready plan.
8. **Validation coupling is surfaced, not hidden:** combining the accessories-only type with the
   minimum-session toggle returns the server's 400.
9. **One prescribe path.** The background worker calls the same `build_prescription` the web uses
   with `use_resolver=None`, so the resolver, deload/drop and readiness gates behave identically.
10. **Plan editing is R8**, specified separately, because it is a new write surface on a live
    workout rather than a reliability change.

## 3. Server data model — migration `0056_ios_plan_request.sql`

`ios_issued_plan` becomes the request-and-result row. A rebuild is required because the current
table ([`0053_ios_workflow.sql`](../../strength_coach/store/migrations/0053_ios_workflow.sql))
declares `prescription_id`, `plan_json`, `readiness_json` and `session_type` `NOT NULL`, and
SQLite cannot relax a `NOT NULL` constraint in place. The rebuild follows the established
`*_new` → copy → drop → rename → recreate-index pattern used by migrations 0006, 0026, 0029,
0038 and 0050.

```sql
CREATE TABLE ios_issued_plan_new (
    issued_plan_id          TEXT PRIMARY KEY,       -- uuid4 hex; also the request id
    device_id               TEXT NOT NULL REFERENCES ios_device(device_id),
    status                  TEXT NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued', 'building', 'ready', 'error',
                                              'skipped')),
    requested_session_type  TEXT NOT NULL,          -- 'auto' or an explicit type
    session_type            TEXT,                   -- resolved type; NULL until ready
    settings_json           TEXT NOT NULL,          -- accepted settings, canonical JSON
    prescription_id         TEXT REFERENCES prescription(prescription_id),  -- set at start
    for_date                TEXT NOT NULL,          -- server-local YYYY-MM-DD
    plan_json               TEXT,                   -- exact plan; NULL until ready
    readiness_json          TEXT,                   -- validated readiness for workout.start
    readiness_ack           INTEGER NOT NULL DEFAULT 0 CHECK (readiness_ack IN (0, 1)),
    created_at              TEXT NOT NULL,          -- UTC ISO-8601
    building_started_at     TEXT,                   -- slot acquired, build began
    ready_at                TEXT,                   -- plan published
    finished_at             TEXT,                   -- terminal: ready or error
    error_code              TEXT,                   -- e.g. resolver_build_failed
    error_message           TEXT,                   -- owner-safe copy; no paths or traces
    request_expires_at      TEXT NOT NULL,          -- created_at + plan_request_ttl_seconds
    plan_expires_at         TEXT,                   -- ready_at + issued_plan_ttl_seconds; NULL until ready
                                                    -- status='skipped' = never built (superseded or
                                                    -- expired while queued); error_code says which
    consumed_at             TEXT,                   -- set atomically with workout creation
    superseded_at           TEXT,                   -- newer request, or stale/interrupted
    workout_id              TEXT REFERENCES workout_session(workout_id)
);
```

Constraints and indexes:

- The existing partial unique index is recreated unchanged in predicate
  (`device_id` where `consumed_at IS NULL AND superseded_at IS NULL`), so a device still has at
  most one live row. A new request supersedes a live row whatever its status, including `queued`
  and `building`.
- Indexes on `(device_id, created_at)` and on `(status, request_expires_at)` for the startup sweep.
- No existing table is altered. `prescription`, `workout_session`, `session` and the readiness
  tables are untouched by this migration.

Config additions in `config/ios.v1.yaml` (committed, no secrets):

```yaml
plan_request_ttl_seconds: 900    # queued/building lifetime; 60-3600
```

**Two lifetimes, two columns, deliberately separate.** The Phase 2 table had one `expires_at`,
which cannot express "how long a build may take" and "how long a ready preview may sit" at the same
time:

| deadline | column | set when | value | what it bounds |
|---|---|---|---|---|
| build deadline | `request_expires_at` | at insert | `created_at + plan_request_ttl_seconds` (15 min) | how long a request may sit `queued` or `building` before it is a failure |
| startable deadline | `plan_expires_at` | at publish | `ready_at + issued_plan_ttl_seconds` (60 min, the existing Phase 2 value) | how long a **ready** preview may be started |

The clock does not stop when the build finishes: publishing a plan starts a fresh 60 minutes.
Expiry is checked against whichever deadline applies to the current status, so a plan built in
40 s and left alone expires 60 minutes after it became ready — not 15 minutes after it was
requested.

Worked example: Request workout at 09:00 → `request_expires_at` 09:15 → plan ready 09:00:45 →
`plan_expires_at` 10:00:45. Reopening the app at 09:40 shows the plan and Start works. Reopening at
10:10 shows no plan and Today returns to "Request workout".

### 3.1 Legacy data mapping — what the rebuild does to existing rows

Phase 2 wrote real rows into `ios_issued_plan` before R7 existed: there are no `status`,
`request_expires_at`, `plan_expires_at` or `settings_json` values to read. The rebuild does not
discard them; every existing row is copied with the mapping below. **No legacy `ios_issued_plan`
row is deleted by `0056`.**

| legacy condition | migrated `status` | other columns | may it become active again? |
|---|---|---|---|
| `consumed_at IS NOT NULL` (started) | `ready` | `consumed_at`, `workout_id`, `prescription_id`, `superseded_at` all copied unchanged | No — consumed stays consumed; the guarded publish and the start check both refuse it |
| unconsumed, not superseded, `expires_at > now` (live preview) | `ready` | `prescription_id` kept, `plan_expires_at = expires_at` so it expires exactly when it would have | Yes, until its original deadline |
| unconsumed, not superseded, `expires_at <= now` (expired) | `ready` | kept as-is; `plan_expires_at = expires_at` (already past) | No — expiry is checked first; it is inert and the next issue supersedes it as today |
| `superseded_at IS NOT NULL` (replaced) | `ready` | `superseded_at` copied unchanged | No — supersession is checked before anything else |
| any row whose `plan_json`/`readiness_json` are unserialisable or whose `prescription_id` has no `prescription` row | migration **aborts** | nothing is copied | n/a |

Rules applied to every copied row:

- `request_expires_at = expires_at` and `plan_expires_at = expires_at`. A legacy plan was already
  built, so its build deadline is history; reusing `expires_at` for both preserves the original
  behaviour exactly and never extends a plan's life.
- `ready_at = created_at` and `finished_at = created_at`. The true publish time was never recorded;
  inventing "now" would make an old plan look freshly built. `created_at` is the only honest value,
  and nothing reads `ready_at` for a legacy row except the audit display.
- `requested_session_type = session_type`, `session_type = session_type`, `settings_json = '{}'`.
  A legacy plan had no settings; the empty object records "none were chosen" rather than a default.
- `error_code`/`error_message` are null. No legacy row is `skipped`: every one of them produced a
  plan.
- `prescription_id` is copied verbatim for every row. It is only nullable for rows created **after**
  R7, where the prescription is written at start.

Preserved unchanged and **not** touched by the migration:

- `prescription` and `prescription_item` — every row keeps its existing `prescription_id` link.
  The migration neither duplicates nor deletes them. The "persist at start" rule of §8 applies only
  to requests created after R7.
- `ios_operation_receipt` — every receipt and stored response body survives untouched. A Phase 2
  receipt still replays its original `200` body (see the compatibility note in §4.1).
- `workout_session`, `session`, `clean_set`, readiness and review tables — no write at all.

Pre-flight validation, run inside the migration's transaction before any copy:

1. rows whose `prescription_id` has no matching `prescription` row (the FK would reject them) — fail
   with `MigrationError` naming the count and a sample id, rather than silently dropping the row;
2. rows whose `plan_json` or `readiness_json` is not valid JSON — same treatment;
3. rows where `consumed_at IS NULL AND workout_id IS NOT NULL` (a state Phase 2 never produced) —
   same treatment, because guessing the intent would rewrite history.

The policy is **fail loudly, never silently lose a plan**. A corrupt row means the database has a
problem worth seeing; a migration that quietly discards it would hide it.

Rollback of the rebuild is the §13.1 backup: the migration copies every row, so restoring the
pre-`0056` file restores the exact Phase 2 table, including rows R7 never produced.

## 4. Server behaviour

### 4.1 `POST /api/ios/v1/prescriptions` — now asynchronous

Body (closed schema; unknown fields rejected):

```json
{"readiness_ack": false,
 "confirmations": {"deload": true, "drop": true},
 "settings": {"session_type": "auto", "minimum_session": false}}
```

- `settings` is optional; omitted means `{"session_type": "auto", "minimum_session": false}`,
  i.e. today's behaviour.
- `session_type` accepts `auto`, `squat`, `hinge`, `bench_squat`, `bench_hinge`,
  `accessory`. `auto` resolves through `schedule.next_session_type` exactly as the web does.
- `minimum_session` maps to `minimum_session=True`; `minimum_target_minutes` and
  `minimum_include_main` may be added in the same object if the owner wants the full
  `MOD-MIN-001` surface. The default target comes from configuration
  ([`minimum-session.v1.yaml`](../../config/minimum-session.v1.yaml)).
- The server keeps every existing gate before writing the row: authentication, mutation switch,
  readiness score/acknowledgement, reactive deload, scheduled deload/drop confirmation. A gate
  failure returns the same 409s as today and creates nothing.
- Validation coupling is preserved and transported unchanged: an accessories-only minimum session
  without an explicit session type is the existing 400, with `fields` naming the problem.

Response `202 Accepted`:

```json
{"issued_plan_id": "…", "status": "queued", "for_date": "2026-11-08",
 "request_expires_at": "2026-11-08T09:15:00+00:00", "plan_expires_at": null,
 "retry_after_ms": 1000,
 "settings": {"session_type": "auto", "minimum_session": false}}
```

- No plan content, no readiness payload and no score: those arrive with the poll result.
- The mutation records an idempotency receipt for the 202 body, so a retry of the same key and body
  returns the same `issued_plan_id` and starts nothing.
- The route supersedes the device's previous live row (any status) and inserts the new row as
  `queued` in one transaction, then hands it to a worker thread.
- If a build is already running for this device, the new row still supersedes it; the running
  worker discovers this when it tries to publish (§4.4).

> **Compatibility with Phase 2 receipts.** A receipt stored before R7 holds a synchronous `200`
> body containing the plan. Replaying that key after R7 returns the stored body unchanged — the
> facade must not rewrite receipts. The client therefore accepts both shapes during the transition:
> a `200` carrying `plan` is treated exactly like a `ready` poll result (the legacy row is
> `ready`, §3.1), and a `202` starts the poll. Receipts expire within 30 days, so this is a
> transition, not a permanent dual protocol.

### 4.2 `GET /api/ios/v1/plans/current` — recovery and polling read

Returns the device's live row (not consumed, not superseded), whatever its status. This is the R2
scope: a relaunched app restores the preview without issuing a replacement.

**This route is authoritative.** It, not the Today payload and not anything cached in the app,
decides the current plan-request lifecycle. Whatever this call returns after launch or foreground
is what the UI must show (§6); a previously fetched Today or a locally retained preview can never
override it.

```json
{"issued_plan_id": "…", "status": "building", "elapsed_seconds": 47,
 "for_date": "2026-11-08",
 "request_expires_at": "2026-11-08T09:15:00+00:00", "plan_expires_at": null,
 "retry_after_ms": 2000,
 "settings": {"session_type": "auto", "minimum_session": false},
 "plan": null, "readiness": null, "warnings": [], "error": null}
```

- `status: ready` fills `plan`, `readiness` (status/score/basis/overrides/context flags) and
  `warnings`; the shape is the Phase 2 issue response, so the client's existing preview decoding is
  reused.
- `status: error` fills `error: {code, message}`.
- No live row → `{"status": "none"}` with 200. Not a 404: "nothing pending" is a normal state.
  This is also what a plan past `plan_expires_at` returns: expiry removes a plan from the live set
  without deleting the row, so an hour-old workout is gone from the app but still auditable.
- `plan_expires_at` is null until the plan is ready; after that it is the deadline that matters.
  The client stops polling at `request_expires_at` and stops offering Start at `plan_expires_at`.
- A row that was `skipped` (never built) is never the live row from the client's point of view:
  superseded rows fail the liveness filter, and expired rows fail the deadline check, so both
  present as `none`. The `skipped` status exists for the database and the tests, not the UI.
- Read-only; no idempotency key; a missed poll is harmless.

### 4.3 `POST /api/ios/v1/workouts` — start persists the prescription

Unchanged request (`{"issued_plan_id": "…"}`) and unchanged client contract, but the server no
longer points at a prescription stored at issue:

- Require `status = 'ready'`; `queued`/`building` → `409 plan_not_ready` with
  `details: {status, retry_after_ms}`. `error` → `410 plan_failed`. Expired/superseded/consumed
  keep their Phase 2 codes.
- In **one** transaction: persist the normal `prescription`/`prescription_item` rows from the
  stored `plan_json` via `prescription_persistence.store_plan`, call `workout.start` with that
  `prescription_id` and the stored readiness, then set `consumed_at`, `workout_id` and
  `prescription_id`. A failure leaves no partial consumption, no prescription row and no workout.
- **Legacy rows already have a prescription.** If `prescription_id IS NOT NULL` — which is every
  Phase 2 row (§3.1) — start reuses it and persists nothing. Writing a second prescription for a
  plan that already has one would duplicate append-only history. A null `prescription_id` is the
  signal that this is a post-R7 preview, and only then is the prescription written at start.
- The workout snapshot remains the issued plan; the client still cannot supply plan content.

### 4.4 Worker: one bounded dispatcher, two eligibility checks, guarded publish

**Bounded execution.** There is exactly **one** worker thread for the iOS plan queue: a
module-level dispatcher started lazily under a lock on the first `queued` request and reused for
the life of the process. The request handler never spawns a thread per request. With a 15-minute
request TTL and a slot that can be held for a full build, a thread-per-request design would
accumulate threads parked on `_CPU_JOB_SLOTS` — unbounded threads waiting on a bounded resource,
which is precisely the shape to avoid.

No `ThreadPoolExecutor`, no new queue abstraction, no second CPU budget. The dispatcher is a loop
over the database, and it still acquires the existing shared
`_CPU_JOB_SLOTS = threading.Semaphore(1)` before building, so the iOS queue competes with the web
forecast rather than bypassing it.

Loop (each iteration):

1. **Select** the oldest eligible row:
   `status='queued' AND consumed_at IS NULL AND superseded_at IS NULL AND request_expires_at > now`,
   ordered by `created_at`. FIFO across devices; this deployment has one.
2. **Wait** if none: block on a `threading.Event` that `POST` sets, with a two-second timeout. The
   timeout terminalises rows that expired or were superseded while nobody was looking, without a
   hot spin.
3. **Eligibility check #1 — before touching the CPU slot.** Re-read the row and terminalise without
   building when it is no longer eligible:
   - `superseded_at IS NOT NULL` → `status='skipped'`, `error_code='superseded'`,
     `finished_at=now`;
   - `request_expires_at <= now` → `status='skipped'`, `error_code='expired'`,
     `finished_at=now`;
   - `for_date != server-local today` → `status='error'`, `error_code='stale_date'`
     (the request crossed midnight; building "today's" plan against yesterday's date would be
     wrong).

   In every one of these cases the dispatcher returns to step 1 **without invoking the resolver**.
4. **Acquire** `_CPU_JOB_SLOTS` blocking, bounded by the row's remaining `request_expires_at`. A
   timeout is the expired case above. While waiting, the row stays `queued`; the client is told
   nothing, because the queue is the answer and there is no 409 "server busy" on this route.
5. **Eligibility check #2 — immediately before `build_prescription`.** The slot may have taken
   minutes, so the row is re-read again; any condition from step 3 now terminalises it, releases
   the slot and returns to step 1. The resolver is **never** invoked for a request that stopped
   being eligible while the dispatcher waited.
6. **Build and publish.** Set `status='building'`, `building_started_at=now`, call the shared
   prescription path, then publish with a guarded update:

   ```sql
   UPDATE ios_issued_plan
      SET status='ready', plan_json=?, readiness_json=?, session_type=?, ready_at=?,
          plan_expires_at=?, finished_at=?
    WHERE issued_plan_id = ? AND superseded_at IS NULL AND status = 'building';
   ```

   Zero rows changed means the request was superseded or expired **while building**: the result is
   discarded and never published. A build already in flight when a newer request arrives is allowed
   to finish its CPU work — Python cannot interrupt `build_resolved` — but it cannot publish. This
   is decision 3's generation check expressed as a conditional write, not a version column.
   Release the slot in a `finally`.

Other rules:

- A build exception sets `status='error'` with an owner-safe code and message and
  `finished_at=now`; no stack trace, path or token is stored. `ResolverBuildError` maps to
  `error_code='resolver_build_failed'` with the existing stage/message.
- The loop body is wrapped so an unexpected exception terminalises that row and the dispatcher
  survives. If the thread ever dies anyway, the next `POST` **or** `plans/current` read restarts it
  under the lock (`is_alive()` check), because the queue is the table and no request lives in the
  thread.
- **Startup sweep.** Nothing is published before step 6, and the build has no side effects, so on
  restart a row left `building` is reset to `queued` (`building_started_at=NULL`) and retried; a
  row left `queued` is simply picked up. Rows already past `request_expires_at` become
  `skipped/expired` immediately. This is better than marking orphans `error`: the work genuinely
  can be redone, and a restarted server should not manufacture a failure for a request that can
  still succeed.
- The dispatcher owns its own `db.Store` connection; it never reuses the request handler's.
- Bounded behaviour is testable: at most one dispatcher thread exists, and at most one build runs
  at a time because the slot is held for the whole build.

## 5. Polling contract

The client polls `GET /api/ios/v1/plans/current` until a terminal state. The server's
`retry_after_ms` is guidance, the client's own schedule is the contract:

| Elapsed | Interval | UI |
|---|---|---|
| 0–10 s | 1 s | spinner, "generating" |
| 10–60 s | 2 s | spinner, elapsed counter |
| 60 s–5 min | 5 s | "still generating (elapsed) — you can leave this screen" |
| 5 min–expiry | 10 s | same wording, no new failure state |

- **Nothing changes at 60 s.** It is a copy threshold, not a timeout. A 90 s build keeps polling at
  the 5 s cadence and renders the plan when it arrives.
- Stop conditions: `ready`, `error`, `none`, expiry (`410`/expired row), user leaves the screen,
  app backgrounds, or authentication fails (401/403 → existing unpair flow).
- The build ceiling is the server's `plan_request_ttl_seconds` (15 min default), not a client
  constant. Past `request_expires_at` the client stops polling and shows "the request timed out,
  try again". Reaching it means the build never finished; it is not the plan's lifetime.
- Each poll is a cheap read, so the existing 10 s request timeout is correct here and needs no
  override.

## 6. Leaving and returning: foreground recovery is authoritative

Yes — a ready plan is loaded after the app is closed and reopened, because nothing about the request
lives in memory on either side. The recovery rule is a single sentence: **after launch or
foreground, `GET /api/ios/v1/plans/current` decides what the app shows, and no local state may
override it.**

Reconciliation, on every launch and every foreground activation:

| server says | UI must |
|---|---|
| `ready` | show a **Workout ready** card on Today from this response's `plan`; Start enabled. Do not auto-present a preview sheet. |
| `queued` or `building` | show the generating card with the server's `elapsed_seconds`, and poll |
| `error` | show the error and a Retry action |
| `none` | show Today with "Request workout" |

- **No stale override.** A locally retained preview, a cached Today payload, or a journal replay
  from before termination may never be shown as the current plan. If any of them disagree with
  `plans/current`, the server wins and the local copy is discarded. A cached Today may still be
  displayed as stale for *other* panels under the Phase 1 rule, but the plan area renders only from
  the authoritative response.
- **Lost `POST` response.** If the request was created but its `202` never arrived, the next
  `plans/current` finds the row (`queued`/`building`/`ready`) and the app resumes as if it had the
  id. The R1 journal is a second layer, not the primary one: a replayed `202` that names a plan the
  server has since superseded is **ignored**, because `plans/current` reports the newer request.
  Reconciliation order is therefore plans/current first, journal second.
- **App termination during a build.** The request survives because it is a database row; reopening
  resumes the counter from `elapsed_seconds`, never from a local stopwatch.
- **Superseded or expired.** A superseded plan is not returned at all (liveness filter) and an
  expired one returns `none`, so the ready card and any Start affordance are removed on the next
  foreground. The app must not keep a Start button for a plan the server will refuse.
- **Active workout wins.** If Today reports an active workout, that card takes precedence over the
  ready card: the owner is mid-session, not choosing one. Starting a workout consumes the plan and
  opens the active workout screen directly; the ready card is not retained.
- **Workout timer recovery is unchanged.** The elapsed timer stays anchored to the server's
  `started_at` for the active workout; foregrounding must not reset it, and R5's ended-elsewhere
  detection still applies. R7 adds no second timer and no second recovery path.
- Because `elapsed_seconds` is server-computed, closing the app for two minutes and reopening shows
  the true age of the request; a plan that became ready while the app was closed is simply `ready`.
- The plan deadline keeps working while the app is away. `plan_expires_at` is 60 minutes after the
  plan became ready, so:
  - returning 20 minutes later → the plan is there and Start works;
  - returning 59 minutes later → still there;
  - returning **an hour later** → the plan has expired: `plans/current` reports `none`, Today
    falls back to "request workout", and the Start action is unavailable. The row is not deleted —
    `plan_json` is retained until pruning and the row is auditable — but it can no longer start a
    workout, because a prescription an hour old may describe a session the owner no longer wants,
    a readiness state that has changed, or sets already done on the web.
  - The client never offers Start on an expired plan; it refreshes and asks for a new one.

## 7. Invalidation

- Changing any setting and tapping Request workout always issues a **new** `POST` with a new
  idempotency key. The server supersedes the previous live row unconditionally, including one that
  is `queued` or `building`.
- The superseded build cannot be cancelled (Python cannot interrupt `build_resolved`); it finishes
  and is discarded by the guarded update in §4.4. The cost is one wasted build on a 4-core box —
  accepted, because cancelling would need cooperativity the resolver does not have.
- The client never edits a plan locally and never reuses a superseded `issued_plan_id`.

## 8. Persistence change and its consequences

- The Phase 2 rule "persist the normal prescription at issue so an issued plan is auditable even if
  never started" is **reversed**: prescription rows are written in the start transaction (§4.3).
- Consequences to state plainly:
  - An unstarted ready preview leaves no `prescription` row. It is a preview, not a prescription.
  - Parameter tweaking therefore cannot pollute the append-only prescription history; the earlier
    design would have written one prescription per tweak.
  - A plan's audit trail begins when the owner starts it. The `plan_json` in `ios_issued_plan` is
    retained until pruning, so a discarded preview is still explainable while it exists.
  - The workout's `prescription_id` is the persisted row created at start, so history, comparison
    and the rubric see exactly what was started.
- Rollback implication: dropping R7 loses previews, not prescriptions, because no prescription was
  written for an unstarted plan.

## 9. Settings, provenance and invariants

- The phone still never constructs a prescription. It chooses a **session type**, whether a
  **minimum session** is acceptable and an optional **top-set/back-off versus straight-set**
  request; loads, sets, reps, RIR, exercise selection and validation remain server-side. The
  resolver decides whether the requested structure is eligible.
- `settings_json` records exactly what was accepted, and the built plan carries the existing
  warnings; the preview shows them. A prescription must remain explicable after the fact.
- Readiness, deload, drop and conflict rules are unchanged; only the transport is.
- Session-type choice must not bypass the schedule's safety rules: the server still applies
  reactive deloads, and an explicit type is validated against the existing allowed set.

## 10. Swift client

- **Today:** "Request workout" opens a settings sheet (session type picker defaulting to Auto;
  main-lift structure defaulting to Server decides; minimum-session toggle and optional target
  minutes). The sheet shows the server's current readiness/confirmation warnings.
- **Generating card:** status, elapsed counter from the server, "you can leave this screen", the
  active settings, and a client-side "Stop waiting" that stops polling without claiming the request
  was cancelled.
- **Preview:** unchanged Phase 2 screen, fed by the poll result; **Start** still posts the issued
  plan id.
- **Foreground:** refresh Today, reconcile the current plan, resume polling (§6).
- No new local persistence: the request lives on the server, so a reinstall or a new device still
  sees the truth.

## 11. Tests

Server (`tests/test_ios_plan_requests.py`, temporary SQLite, live-server fixture):

- `POST` returns 202 with no plan content; the row is `queued`; a receipt replays the same id.
- Settings: default when omitted; explicit session type reaches `build_prescription`; minimum
  session maps to `MOD-MIN-001`; accessories-only without a type returns the existing 400; unknown
  fields rejected.
- Gates unchanged: readiness 409, scheduled deload/drop 409, reactive deload warning.
- Worker publishes `ready` with the exact plan; `plans/current` returns it; status transitions are
  one-way.
- Supersession during a build discards the stale result (guarded update affects no row); superseding
  a `queued` row works.
- CPU slot: a second request while one builds stays `queued` and later builds; no 409 to the client.
- Start requires `ready`; `queued` → 409 `plan_not_ready`; `error` → 410 `plan_failed`.
- Start writes prescription rows exactly once and links them; a retried start does not duplicate.
- **Legacy start:** a migrated Phase 2 row with `prescription_id` set starts without persisting a
  second prescription, and the workout links to the original `prescription_id`.

Worker and bounded execution (`tests/test_ios_plan_requests.py`, with `build_prescription` spied):

- **A superseded `queued` request never invokes the resolver.** Supersede the row, run one dispatcher
  tick, assert the spy recorded zero calls and the row became `skipped`/`superseded`.
- **An expired `queued` request never invokes the resolver.** Same shape, `error_code='expired'`.
- **Mid-wait supersession never invokes the resolver.** Hold `_CPU_JOB_SLOTS` with a fake job, queue a
  request, then supersede it and release the slot: eligibility check #2 fires, zero resolver calls.
- **A request outstanding at midnight** (`for_date != today`) becomes `error`/`stale_date` with zero
  resolver calls.
- **Bounded execution:** after queueing N requests, at most one dispatcher thread exists
  (`threading.enumerate` filtered by name) and at most one `build_prescription` is in flight
  (the spy asserts no overlap). Requests beyond the first wait in the database, not in threads.
- **Queue order:** two queued requests build oldest-first.
- **Dispatcher restart:** with the dispatcher stopped, a `POST` (and separately a
  `plans/current` read) restarts it and the queued row still builds.
- **Startup sweep:** a row left `building` by a dead process returns to `queued` and is retried;
  one already past `request_expires_at` becomes `skipped`/`expired`.
- **Guarded publish survives the race:** supersede during a slow build, let the build finish, assert
  the row stays without `plan_json` and no `ready` plan exists.

Migration `0056` (`tests/test_migration_0056.py`, building a database at the `0053` shape):

- A live unconsumed unexpired legacy plan becomes `ready` with `plan_expires_at = expires_at` and
  remains startable.
- A consumed legacy plan keeps `consumed_at`, `workout_id` and `prescription_id`, and cannot start
  again.
- A superseded legacy plan keeps `superseded_at` and never becomes live.
- An expired unconsumed legacy plan becomes `ready` but is inert: `plans/current` reports `none`
  and Start returns the expired code.
- `prescription` and `prescription_item` row counts and contents are identical before and after;
  no prescription is duplicated or deleted.
- `ios_operation_receipt` rows and response bodies are byte-identical before and after.
- The partial unique index still permits exactly one live row per device after the rebuild.
- Pre-flight failure: a legacy row whose `prescription_id` has no prescription aborts the migration
  with `MigrationError` and leaves the `0053` table intact.
- Rollback: restoring the pre-migration file reproduces the `0053` table exactly.
- Expiry is deadline-specific: a `queued`/`building` row past `request_expires_at` fails the
  request; a `ready` row past `plan_expires_at` reports `none` and `409 plan_expired` on Start.
  Publishing sets `plan_expires_at = ready_at + issued_plan_ttl_seconds`, so a 90 s build yields a
  full 60 minutes of startable time, not 58.5 minutes.
- No token, code, path or stack trace in any stored row, response or log; no plan content in logs.

**Acceptance scope.** Simulator and unit coverage close R7 (§14 decision 4). The build timing is
measured against a copy of the live database, never the live file (§14 decision 5), and the polling
table is re-checked against that measurement before the contract is closed.

Client (unit):

- Poll schedule advances 1 → 2 → 5 → 10 s and does not stop at 60 s; a 90 s scripted build ends
  `ready` and renders.
- Settings round-trip; a settings change issues a new key; superseded id is never reused.
- 409 `plan_not_ready` on Start is handled without losing the ready card.
- **Foreground reconciliation is authoritative:**
  - a **lost `POST` response** (request created, response never received) resolves to the
    generating card on the next foreground, then to the **Workout ready** card when the poll
    reports ready;
  - a **locally retained ready plan** that the server no longer reports is cleared, not shown;
  - a **cached Today payload** carrying a stale plan does not render a ready card or enable Start;
  - **supersession** (a newer request replaced the plan while the app was closed) shows the newer
    request, never the old one;
  - **expiry** removes the ready card and the Start affordance and returns Today to
    "Request workout";
  - a **journalled `202`** naming a superseded plan is ignored in favour of `plans/current`;
  - an **active workout** takes precedence over a ready card, and the elapsed timer is unchanged
    by foregrounding (the R5 recovery tests still pass).

## 12. Acceptance

1. With the resolver enabled, tapping Request workout returns immediately, shows a generating card,
   and delivers the plan after ~40–90 s without a transport error or a pending journal entry.
2. Choosing a session type and/or a minimum session reaches the built plan and appears in its
   provenance; an invalid combination returns the server's 400 and no request is created.
3. Changing settings supersedes the pending request; the superseded build is not published.
4. Force-quitting during a build and reopening the app resumes the counter; reopening after the
   build finished shows the plan.
5. Starting a ready plan writes exactly one prescription and one workout, linked, and a retried
   start creates neither a second prescription nor a second workout.
6. The web UI's forecast during an iOS build returns its existing "CPU-heavy job already running"
   behaviour, and the iOS client never sees a 409 for slot contention.
7. **Bounded execution:** queueing several requests creates no more than one dispatcher thread and
   never more than one concurrent build; a superseded or expired `queued` request is terminalised
   with zero calls into the resolver.
8. **Legacy data preserved:** every pre-`0056` `ios_issued_plan` row survives with the §3.1
   mapping, prescription and receipt rows are unchanged, and a corrupt legacy row aborts the
   migration instead of being dropped.
9. **Authoritative recovery:** after a lost `202`, a supersession or an expiry, launch and
   foreground show exactly what `plans/current` reports; no cached Today or retained preview
   overrides it; an active workout still takes precedence and its timer is unaffected.
10. Default suite, docs tests and `ruff` pass; existing Phase 2 behaviour for readiness, sets, form,
    completion and abandon is unchanged.

**Implementation status (2026-11-08).** Server criteria 1–3 and 5–10 are covered by
`tests/test_ios_workflow.py` and `tests/test_migration_0056.py`; the default suite, docs tests and
`ruff` pass. The client is implemented, **built and unit-tested on the iOS 27.2 simulator**
(iPhone 17): 94 tests, 0 failures, and the built app installs and launches to the pairing screen.
Criteria 4 and 9 are exercised by the client unit tests (foreground reconciliation, lost response,
supersession, expiry) rather than by a scripted live-server run.

The live UI smoke test **passed twice on 2026-11-08**, against throwaway servers on a non-default
port and temporary databases: pair → readiness → request workout → settings sheet → generating →
workout-ready card → start → add a VBT set → finish → Progress. The first run had the resolver **off**
(107.8 s); the second had it **on**, against a copy of the real database (90.9 s), so criterion 1
is demonstrated rather than assumed.

Measurements from the resolver-enabled run: `POST` returned `202` in 0.1 s and the plan was
ready 4 s after the request on the development host. The ODROID-C4 remains the server, where the
benchmark is 35–46 s; the polling table is sized for that, and a faster development machine is not
evidence about the deployed host (§14 decision 5).

The run also found a real bug: consuming the plan makes `plans/current` report `none`, and
refreshing on that cleared the prescription state and dismissed the then-current preview sheet mid-start. Fixed
by leaving the state alone while a workout is active. Migration `0056` was additionally applied to
a copy of the live database, preserving all five legacy plan rows with their prescription links,
consumption and supersession state. The physical-device pass is not required (§14 decision 4).

## 13. Rollback

- Set `ios.mutations_enabled: false` to return every mutation to 503 while reads stay available.
- Remove the route changes and the worker; revert `POST /api/ios/v1/prescriptions` to the
  synchronous Phase 2 behaviour if needed.
- Drop `ios_issued_plan` and delete the `0056` `schema_migration` row together
  (`IOS-CLIENT-PLAN.md` §13.2). This drops the R7 previews **and** the legacy Phase 2 issued plans
  that `0056` carried forward, so a rollback loses unstarted plans of both generations. Starting a
  legacy plan before the rollback leaves its workout and prescription untouched, because those were
  written by Phase 2, not by R7.
- No prescription, workout, readiness or session row is touched by a rollback: an unstarted post-R7
  preview never wrote one, and a legacy plan's prescription already existed.
- Take the §13.1 backup first: the rebuild copies the whole table, and restoring that file is the
  only way back if the rebuild itself misbehaved.
- Rolling back after `0056` has been applied and the process has queued rows: stop the server first.
  A dispatcher still running against a dropped table would only log errors, but it would also write
  to the table between the drop and the `schema_migration` delete.

## 14. Decisions taken and remaining open questions

Settled by the owner on 2026-11-08:

1. **Approval and order:** R7 is approved and is implemented first; R8 follows only after R7 is
   merged. Neither is implemented at the time of this record.
2. **Minimum-session surface:** ship the toggle plus the optional target minutes first;
   `minimum_include_main` and the accessories-only path stay specified but unexposed until there is
   a reason to add them.
3. **Slot fairness:** shared slot is accepted; revisit only if iOS builds start blocking the web
   forecast in practice.
4. **Acceptance scope:** simulator coverage plus the server and client unit tests close R7. A
   physical-iPhone acceptance pass is **not** required for R7 closure, unlike Phase 2 and Phase 3A.
   The device-shaped claim (tap, leave, return) is exercised on the iPhone 18 Pro simulator.
5. **The ODROID-C4 remains the server; timing is measured against it.** The 35–46 s resolver build
   is the deployment figure ([`PERFORMANCE-PROFILE.md`](../PERFORMANCE-PROFILE.md)), not a
   historical curiosity: the phone talks to the Odroid, so every design choice here is sized for a
   build that can take most of a minute, and the polling table is built for it. A benchmark run may
   copy `data/coach.db` to a temporary path and enable the resolver on **that copy**; the live
   database is never opened writable for a benchmark. A faster development machine is not evidence
   about the deployed host and must not be used to shorten the timeouts.

Still open:

1. **Ready-plan default lifetime.** `issued_plan_ttl_seconds` stays at the Phase 2 value of 60
   minutes, measured from `ready_at`. Raise it (for example to the end of the server-local day) if
   an hour turns out to be too short in real use; it is config, not code. The recommendation is to
   keep 60 minutes until the behaviour is observed, because a stale prescription is worse than a
   repeated request.
2. **Poll cadence tuning** after the first real 40 s and 90 s builds on the device.

## 15. Implementation plan and task breakdown

Server first, then client, in this order. Each task lands with its own tests; a task is not done
until the focused tests for it pass. Nothing here touches the prescription methodology, readiness
scoring, resolver behaviour or load selection (constraint: keep the scope unchanged).

| # | Task | Files | Done when |
|---|---|---|---|
| T1 | **Migration `0056`** — rebuild `ios_issued_plan` with the §3 schema and the §3.1 legacy mapping, pre-flight validation, and the `(status, request_expires_at)` index | `store/migrations/0056_ios_plan_request.sql` | `tests/test_migration_0056.py` passes; a real copy of the live database migrates and `PRAGMA quick_check` is ok |
| T2 | **Store helpers** — enqueue, select-oldest-eligible, terminalise (`skipped`/`error`), set building, guarded publish, reset `building`→`queued` on startup | `store/ios_workflow.py` | helper tests cover each conditional write and the guarded publish's zero-row case |
| T3 | **Bounded dispatcher** — the single module-level thread, the wait event, both eligibility checks, slot acquisition, startup sweep | `web/server.py` (or a small `web/ios_plan_worker.py` if the file grows) | worker tests (§11): zero resolver calls for superseded/expired/midnight requests; one dispatcher; one build at a time |
| T4 | **`POST /api/ios/v1/prescriptions`** — closed schema with `settings`, gate reuse, 202 body, 202 receipts, supersede-then-insert, signal the dispatcher | `web/server.py`, `web/ios_config.py` | route tests; idempotent 202 replay; capability flag still returns 503 when disabled |
| T5 | **`GET /api/ios/v1/plans/current`** — authoritative read, `none` for absent/expired, `retry_after_ms`, `elapsed_seconds` | `web/server.py` | read tests incl. expired → `none` and no cross-device leakage |
| T6 | **Start path** — require `ready`; reuse a legacy `prescription_id`; otherwise persist from `plan_json` in the same transaction | `web/server.py` | start tests: one prescription, one workout, no duplicate on retry, legacy row starts without a second prescription |
| T7 | **Capabilities and Today** — keep `prescription`/`workout_write`; add the plan summary to today so a cold launch can render without an extra call | `web/server.py` | today payload test; capability false hides the client write UI |
| T8 | **Client: request flow** — settings sheet, generating card with server elapsed, polling schedule, cancellation of polling on leave | `StrengthApp/Core/*`, `Features/Today`, `Features/Workout` | client unit tests for the poll schedule and settings round-trip |
| T9 | **Client: authoritative recovery** — reconcile on launch and foreground, plans/current over cache/journal, clear superseded/expired, preserve the workout timer | `StrengthApp/Core/AppModel.swift` | the foreground reconciliation tests in §11 |
| T10 | **Close-out** — docs status updates, `ROADMAP` §4.30, acceptance run on the simulator against a temporary DB with the resolver on | docs, `ROADMAP.md` | acceptance 1–10 demonstrated; default suite, docs tests and `ruff` pass |

Sequencing notes:

- T1–T3 must be merged before any client work: the client cannot poll a route that does not exist.
- T4 and T5 are one unit of review; a 202 with no read route is unusable.
- T6 changes an existing accepted route, so the Phase 2 start tests are re-read, not rewritten: the
  only new branch is the legacy `prescription_id`.
- T8/T9 are client-only and can proceed against a temporary server once T4–T7 are merged.
- Take the §13.1 backup immediately before applying T1 to the live database, not before the branch
  is written.

## 16. Documentation consistency review (2026-11-08)

Checked every public document that mentions the iOS prescription path. Found and resolved:

| stale claim | where | resolution |
|---|---|---|
| "hands it to a worker thread" — implied one thread per request | this contract §4.1/§4.4 | replaced by the single bounded dispatcher (§4.4) |
| Startup sweep "marks orphaned rows `error`/`interrupted`" — contradicted the queue-is-the-table design | this contract §4.4, §11 | reset to `queued` and retried instead |
| One `expires_at` serving two meanings | this contract §3 | split into `request_expires_at` and `plan_expires_at` |
| `POST /api/ios/v1/prescriptions` returns the plan synchronously | `docs/API.md` route table and the "Issued plans" bullet | marked as current behaviour with the R7 change called out |
| `ios_issued_plan` column list without status or deadlines | `docs/DATA-MODEL.md` §20 | pending-change note added, pointing at §3 and §3.1 |
| "The prescription is stored at issue" | `docs/IOS-CLIENT-PLAN.md` §6 increment table | R7 row added with the new persistence rule |
| "R2 deferred" | plan §4.30 and this contract | R2 marked absorbed by `plans/current` |
| "specified, not implemented" for R7 | plan status header, §11 next task, manifest, roadmap | all say approved 2026-11-08, not started |

Deliberately **not** changed: the Phase 2 contract's accepted prose. It keeps its historical text
with inline "superseded by" markers, because rewriting an accepted contract would destroy the record
of what was agreed.

Remaining known inconsistency, accepted: `docs/DATA-MODEL.md` §20 and `docs/API.md` describe the
Phase 2 shape until T1 and T4 land. Both carry an explicit pending-change note, so no reader can
mistake the description for current behaviour.

## 17. Implementation record (2026-11-08)

Where the shipped code differs from the specification above, and why. Everything else is current
behaviour.

| area | spec | implemented | why |
|---|---|---|---|
| storage | status, settings, two deadlines | adds `build_inputs_json` | The client's deload/drop confirmations and readiness acknowledgement must be frozen at request time; the build runs seconds later in another thread. |
| pre-flight | "name the count and a sample id" | a CHECK/FK failure that `db.migrate` surfaces as `MigrationError` | SQLite cannot raise a custom message with a row count from a migration; the invariant is enforced and the rebuild rolls back, which is the property that matters. |
| startup sweep | reset `building` to `queued` | same | Nothing is published before the guarded publish, so a retry is safe. |
| settings validation | accessory coupling returns 400 at request time | accessory sessions surface as a build error (`error_code = resolver_build_failed`) | The coupling lives inside `build_prescription`, which also decides whether the resolver is enabled; pre-validating it here would duplicate a rule. |
| worker tests | `tests/test_ios_plan_requests.py` | `tests/test_ios_workflow.py` | They share the live-server fixture and the same concerns; a second file would duplicate the fixture. |
| acceptance | simulator pass | built, unit-tested (71) and exercised live against a throwaway server | The live UI flow passed; the resolver was off, so its timing is still the ODROID benchmark rather than a measurement on this host. |

Client surface added: `PlanSettings`, `PlanRequestAck`, `PlansStateResponse`, `PlanProgress`;
`IOSAPIClient.planState`; `AppModel` polling with the 1/2/5/10 s schedule, foreground
reconciliation and the `generating` state; a Today settings sheet, generating card and Stop
waiting. The client's own unit tests were updated to the new API and fixtures.

## 18. References

- [`IOS-CLIENT-PLAN.md`](../IOS-CLIENT-PLAN.md) — phase boundary, invariants, rollback gates.
- [`IOS-PHASE-2-CONTRACT.md`](IOS-PHASE-2-CONTRACT.md) — the surface this amends.
- [`API.md`](../API.md), [`DATA-MODEL.md`](../DATA-MODEL.md) — current route and schema reference.
