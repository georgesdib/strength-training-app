# iOS R7 — Asynchronous prescription request with workout settings

**Status:** **approved by the owner on 2026-11-08; implementation not started.** Documentation only:
this contract still creates no code, route, migration or CLI by itself. Implementation begins only
after this committed document is the reference.

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

- Optional workout settings before issuing a plan: session type and the minimum-session fallback.
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
                            CHECK (status IN ('queued', 'building', 'ready', 'error')),
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

### 4.2 `GET /api/ios/v1/plans/current` — recovery and polling read

Returns the device's live row (not consumed, not superseded), whatever its status. This is the R2
scope: a relaunched app restores the preview without issuing a replacement.

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
- The workout snapshot remains the issued plan; the client still cannot supply plan content.

### 4.4 Worker and generation check

- The worker acquires the shared `_CPU_JOB_SLOTS` semaphore **blocking**, with a bounded wait of
  the row's remaining `expires_at`. While waiting, the row stays `queued`; there is no 409 "server
  busy" to the client, because the queue is the answer.
- On acquisition it sets `status = 'building'`, `building_started_at`. It then builds through the
  shared path and publishes with a guarded update:

  ```sql
  UPDATE ios_issued_plan
     SET status='ready', plan_json=?, readiness_json=?, session_type=?, ready_at=?, …
   WHERE issued_plan_id = ? AND superseded_at IS NULL AND status = 'building';
  ```

  Zero rows changed means the request was superseded or expired while building: the result is
  discarded, never published. This is the decision-3 generation check, expressed as a conditional
  write rather than a separate version column.
- A build exception sets `status='error'` with an owner-safe code and message; no stack trace,
  path or token is stored. Expected resolver failures (`ResolverBuildError`) map to
  `error_code = 'resolver_build_failed'` with the existing stage/message.
- **Startup sweep:** on server start, rows left `queued`/`building` whose thread died with the
  process are marked `error` (`error_code = 'interrupted'`) or superseded, so a poll can never hang
  forever on a worker that no longer exists.
- The worker owns its own `db.Store` connection; it never reuses the request handler's.

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

## 6. Leaving and returning to the app

Yes — a ready plan is loaded after the app is closed and reopened, because nothing about the request
lives in memory on either side.

- On launch and on every foreground activation the client refreshes Today, which includes the
  current plan summary, and then:
  - `ready` → the preview screen with the returned plan;
  - `queued`/`building` → the generating card resumes with `elapsed_seconds` from the server, not a
    local stopwatch;
  - `error` → the error with a Retry action;
  - `none` → normal Today.
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

- The phone still never constructs a prescription. It chooses a **session type** and whether a
  **minimum session** is acceptable; loads, sets, reps, RIR, exercise selection and validation
  remain server-side.
- `settings_json` records exactly what was accepted, and the built plan carries the existing
  warnings; the preview shows them. A prescription must remain explicable after the fact.
- Readiness, deload, drop and conflict rules are unchanged; only the transport is.
- Session-type choice must not bypass the schedule's safety rules: the server still applies
  reactive deloads, and an explicit type is validated against the existing allowed set.

## 10. Swift client

- **Today:** "Request workout" opens a settings sheet (session type picker defaulting to Auto;
  minimum-session toggle and optional target minutes). The sheet shows the server's current
  readiness/confirmation warnings.
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
- Startup sweep marks orphaned `queued`/`building` rows `error`/`interrupted`.
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
- Foreground with a ready plan opens the preview; with a building plan resumes the counter from
  `elapsed_seconds`; with an error shows retry; with none shows Today.
- Settings round-trip; a settings change issues a new key; superseded id is never reused.
- 409 `plan_not_ready` on Start is handled without losing the preview.

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
7. Default suite, docs tests and `ruff` pass; existing Phase 2 behaviour for readiness, sets, form,
   completion and abandon is unchanged.

Accepted on 2026-11-08: criteria 1–6 are demonstrated on the iPhone 18 Pro simulator against a
temporary SQLite database with the resolver enabled. No physical-device pass is required for R7
closure (§14 decision 4).

## 13. Rollback

- Set `ios.mutations_enabled: false` to return every mutation to 503 while reads stay available.
- Remove the route changes and the worker; revert `POST /api/ios/v1/prescriptions` to the
  synchronous Phase 2 behaviour if needed.
- Drop `ios_issued_plan` and delete the `0056` `schema_migration` row together
  (`IOS-CLIENT-PLAN.md` §13.2). Ready previews are lost; no prescription, workout, readiness or
  session row is touched, because an unstarted preview no longer writes one.
- Take the §13.1 backup first: the rebuild copies the whole table.

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
5. **Timing measurement uses a copy of the live database.** A benchmark run may copy
   `data/coach.db` to a temporary path, enable the resolver on **that copy**, and time the build;
   the live database is never opened writable for a benchmark. The historical 35–46 s figure comes
   from the ODROID-C4 ([`PERFORMANCE-PROFILE.md`](../PERFORMANCE-PROFILE.md)); the current host is
   faster, so the elapsed time is re-measured before the polling table is tuned, and the numbers in
   §1 are treated as an upper bound rather than a current fact.

Still open:

1. **Ready-plan default lifetime.** `issued_plan_ttl_seconds` stays at the Phase 2 value of 60
   minutes, measured from `ready_at`. Raise it (for example to the end of the server-local day) if
   an hour turns out to be too short in real use; it is config, not code. The recommendation is to
   keep 60 minutes until the behaviour is observed, because a stale prescription is worse than a
   repeated request.
2. **Poll cadence tuning** after the first real 40 s and 90 s builds on the device.
