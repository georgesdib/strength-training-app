# iOS Phase 2 — Online Strength Workflow: implementation contract

**Status:** draft for owner approval, 2026-11-07. Documentation only; this contract creates no
code, route, migration or CLI by itself. Phase 1 is complete (see
[`IOS-PHASE-1-CONTRACT.md`](IOS-PHASE-1-CONTRACT.md) §13). Do not implement Phase 2 until the
owner approves this contract.

**Scope:** fixes the exact server surface, data model, client surface, tests, acceptance and
rollback for Phase 2 of [`IOS-CLIENT-PLAN.md`](../IOS-CLIENT-PLAN.md). The plan remains the
authority for the phase boundary; this document exists so the server repository and the separate
`StrengthApp` repository can be built against one written interface.

## 1. Phase 2 in one paragraph

A paired iPhone can write the owner's manual readiness, request a server-issued prescription, start
that prescription by id, log performed sets (including optional manual mean velocity), record
optional 1–5 form ratings, finish with a session RPE or an explicit “not recorded”, abandon a
workout, and read the existing progress summary. Every mutation is authenticated, idempotent and
validated by the existing Python services. The plan is immutable on the phone: the client never
supplies prescription content, never computes a readiness score or load, and never owns the
training decision. There is no offline queue, HealthKit, review/rubric screen, LLM control, sleep
feature or web-auth change in Phase 2.

## 2. Repositories and build order

- Server (this repository): migration, service/route logic, tests. Work continues on `iOS-app`;
  the owner merged the current state into `development` separately. Do not merge Phase 2.
- Client (`StrengthApp` repository): the read-only Phase 1 shell plus the Phase 2 readiness,
  prescription, workout, completion and Progress surfaces. Work on `main`.
- Order: server contract and tests first, then the client against a temporary local server. A
  change that crosses the boundary lands server-first; there is no atomic cross-repository commit.
- CI runs on `main` only. The local default suite, docs tests and `ruff` are the Phase 2 gate
  until the owner merges.

## 3. Network and credential model

- Reuse the Phase 1 credential exactly: one per-device bearer token, Keychain-only on the phone,
  SHA-256 digest at rest, revoked by the local CLI. No accounts, passwords, sessions, cookies or
  new auth mechanism.
- All Phase 2 routes are under `/api/ios/v1/` and require `Authorization: Bearer <token>`.
  Authentication runs before dispatch, as in Phase 1. `POST /api/ios/v1/pair` remains the only
  unauthenticated iOS route.
- Plain HTTP on the trusted home LAN only. No TLS, proxy, CA, certificate, port-forwarding, VPN or
  remote access. LAN traffic, including the token and workout data, is unencrypted; the deployment
  assumes a trusted network with no public exposure.
- No external call, analytics, telemetry, crash reporting, cloud database or Internet fallback.
  An iOS request can never enable or select an external LLM.
- The client talks only to the configured server origin. The redirect guard rejects any redirect
  whose scheme, host or effective port differs from the paired origin.

## 4. Server data model — migration `0053_ios_workflow.sql`

Additive tables only. Existing tables, routes, prescriptions, workouts, readiness, feedback and
review records are untouched.

### 4.1 `ios_issued_plan`

| column | notes |
|---|---|
| `issued_plan_id` | uuid4 hex, primary key |
| `device_id` | FK `ios_device(device_id)`; the plan is device-scoped |
| `prescription_id` | FK `prescription(prescription_id)`; the normal append-only prescription persisted at issue |
| `for_date` | server-local `YYYY-MM-DD`, always the issue date |
| `session_type` | resolved server session type |
| `plan_json` | exact plan snapshot shown to the client, including warm-ups/notes/resolver data |
| `readiness_json` | validated readiness values passed to `workout.start` |
| `readiness_ack` | 0/1; whether the owner explicitly acknowledged partial/unknown readiness |
| `created_at` | UTC ISO-8601 |
| `expires_at` | UTC ISO-8601; default 60 minutes after creation |
| `consumed_at` | UTC ISO-8601, nullable; set atomically with workout creation |
| `superseded_at` | UTC ISO-8601, nullable; set when a newer issue replaces this unstarted plan |
| `workout_id` | FK `workout_session(workout_id)`, nullable until start |

- A partial unique index allows at most one live, unstarted plan per device:
  `CREATE UNIQUE INDEX ... ON ios_issued_plan(device_id) WHERE consumed_at IS NULL AND superseded_at IS NULL`.
- Indexes support `device_id`, `expires_at` and quota/pruning queries. Expired/superseded rows
  are pruned opportunistically; no retention promise is made.
- A new issue marks the previous live plan `superseded_at = now` and inserts the new one in one
  transaction. “Previous live” includes an expired-but-never-started row, so the partial unique
  index is satisfied and the expired plan remains available for audit until pruning.
- The normal `prescription`/`prescription_item` rows are persisted at issue (see §8.2), so an
  issued plan is an auditable prescription even if it is never started. It is not a completed
  session and does not appear in history.

### 4.2 `ios_operation_receipt`

| column | notes |
|---|---|
| `device_id` | FK `ios_device(device_id)` |
| `operation_id` | client `Idempotency-Key` value, normalized; part of the primary key |
| `route` | canonical route string, e.g. `POST /api/ios/v1/workouts` |
| `request_hash` | SHA-256 of the canonical JSON body |
| `response_status` | stored HTTP status (2xx only) |
| `response_json` | stored response body |
| `created_at` | UTC ISO-8601 |
| `expires_at` | UTC ISO-8601; retention default 30 days |
| primary key | `(device_id, operation_id)` |

- Only successful 2xx responses are stored. Validation/conflict responses are not receipts and are
  re-evaluated on retry.
- `request_hash` is computed from the parsed body with sorted keys and compact separators, not
  from raw bytes, so a whitespace-only retry is the same request.
- Receipts are pruned opportunistically after `expires_at`. No secrets are stored; the body has no
  token or pairing code.

### 4.3 Config

Add `config/ios.v1.yaml` (committed, public, no secrets):

```yaml
# Phase 2 iOS facade. Set mutations_enabled false to fall back to Phase 1 read-only.
mutations_enabled: true
issued_plan_ttl_seconds: 3600   # 60-86400
receipt_retention_days: 30      # 1-365
```

- The loader validates the ranges and fails closed with a clear startup/route error if the file is
  malformed.
- `mutations_enabled: false` disables every Phase 2 mutation route with `503 ios_mutations_disabled`;
  reads remain available. This is the first rollback switch.
- The TTL and retention values are config, not code. The client does not read this file.

### 4.4 Additive/rollback properties

Dropping `ios_issued_plan` and `ios_operation_receipt` loses only pending plans and retry
receipts. Prescriptions, workouts, readiness entries, sessions and reviews already committed by a
started session remain valid; no existing table is altered.

## 5. Server routes

### 5.0 Common rules

- All routes below require the Phase 1 bearer token. Missing/unknown token `401`; revoked device
  `403`; authenticated unknown route `404`.
- Every mutation requires `Idempotency-Key: <uuid>`. Missing or malformed → `400` with
  `code: idempotency_key_required` / `idempotency_key_invalid`.
- Request bodies are JSON and capped by the existing `MAX_BODY_BYTES` and framing rules. The
  mutation schemas are **closed**: unknown fields → `400 unknown_field`. In particular a body may
  never contain `plan`, `items`, `prescription` or any prescription-content field.
- Response mutation bodies return the existing service payload; the facade does not calculate a
  training number.
- The existing error envelope is extended additively:
  `{"error": "...", "code": "...", "fields": {"field": "why"}, "details": {...}}`.
  `code` and `details` are optional; `fields` keeps the Phase 1 meaning. No paths, stack
  traces, tokens, codes or secret values appear.
- “Today” everywhere below means the **server-local calendar date**. No request accepts an
  arbitrary training date for a mutation.

### 5.1 `POST /api/ios/v1/readiness`

Writes the owner's manual readiness for the server-local today and returns the existing readiness
payload.

```json
{"values": {"sleep": 4, "energy": 3, "mood": 4, "soreness": 4, "stress": 3,
            "hrv_ms": 55, "rhr_bpm": 52, "bodyweight_kg": 80.2,
            "wearable_score": 72, "squat_readiness": 4,
            "bench_readiness": 3, "deadlift_readiness": 4},
 "note": "optional"}
```

- Accepted fields are exactly the current manual readiness inputs:
  `sleep`, `energy`, `mood`, `soreness`, `stress`, `squat_readiness`,
  `bench_readiness`, `deadlift_readiness`, `hrv_ms`, `rhr_bpm`, `bodyweight_kg`,
  `wearable_score`. Nutrition, hydration, body fat and grip are **not** readiness inputs
  (`DEC-READINESS-20`, `DEC-MEASURE-02`, `DEC-GRIP-01`); do not add them.
- Values are validated by `readiness_utils.validate`; unknown fields and zero placeholders are
  rejected. Empty fields are omitted by the client, never sent as zero.
- Manual precedence is the existing manual-over-import rule: `readiness_feature.record_manual`.
  There is no readiness override, preset or context-flag write in Phase 2.
- Only the server-local today is written. No `date` field; backdating/future-dating is not exposed.
- Response `200`: the existing `GET /api/readiness/<today>` payload, including the score and
  settings/presets. The client may refresh `today` afterwards.
- Idempotency: a retry with the same key and body returns the stored response and appends nothing.

### 5.2 `POST /api/ios/v1/prescriptions`

Issues one server-built prescription and returns its issued-plan id. The client never sends plan
content.

```json
{"readiness_ack": false,
 "confirmations": {"deload": true, "drop": true}}
```

- `readiness_ack` is optional (default `false`). `confirmations` is optional and is only
  meaningful after the server returns `409 confirmation_required`.
- Only `session_type = auto` exists. There is no session-type override, minimum-session,
  technique-throttle, selection-apply, LLM or drop/deload *option* in the request; the server uses
  the existing auto scheduler and the existing safety decisions.
- Readiness gate: if the readiness status is `ready`, proceed. If it is `insufficient` or
  `unknown` and `readiness_ack` is false, return `409 readiness_required` with
  `details: {"status", "score", "basis", "can_acknowledge": true}` and create no plan. With
  `readiness_ack: true`, proceed exactly as the web’s explicit unknown-readiness path and include
  the warnings in the response.
- Deload/drop confirmation: reuse `deload_feature.reactive_decision`,
  `deload_feature.scheduled_decision` and the existing per-session drop-confirmation window.
  - A reactive deload is always applied as the existing safety rule and reported in warnings; it
    does not require a confirmation.
  - A scheduled deload or required drop decision that is not supplied returns
    `409 confirmation_required` with `details` (reason/day/window) and creates no plan. The client
    shows the server’s details and resends with `confirmations` and a **new** idempotency key.
    Declining a scheduled deload proceeds as the web does; declining a drop proceeds without the
    drop, as the web does. The iOS layer only transports the decision.
- Build and persist:
  - Call the existing deterministic prescription path (the same path the web uses) with the
    server-local today, auto session type, the stored readiness and the resolved deload/drop
    decisions. No new calculation.
  - Persist the normal `prescription` and `prescription_item` rows (and existing modifier
    provenance) exactly as the web start path does, then insert `ios_issued_plan` with the exact
    plan JSON, readiness values, `readiness_ack`, `for_date` and 60-minute expiry.
  - Supersede the previous live plan for this device in the same transaction.
- Response `200`:

```json
{"issued_plan_id": "…",
 "prescription_id": "…",
 "for_date": "2026-11-07",
 "session_type": "squat",
 "expires_at": "2026-11-07T18:00:00+00:00",
 "plan": { "items": [], "notes": {}, "issues": [], "…": "existing prescription JSON" },
 "readiness": { "status": "ready", "score": 0.82, "basis": "…", "overrides": {}, "context_flags": [] },
 "warnings": []}
```

- The `plan` is the existing prescription JSON; the client displays it and cannot alter it.
- Errors: `400` validation/unknown field; `409 readiness_required` or
  `confirmation_required`; `503 ios_mutations_disabled`.

### 5.3 `POST /api/ios/v1/workouts` — start by issued-plan id

Starts the workout from a server-issued plan. The request contains no plan content.

```json
{"issued_plan_id": "…"}
```

- Load the plan by `issued_plan_id` and `device_id`. Another device’s plan is `404`
  `plan_not_found`. Expired or superseded → `410 plan_expired`/`plan_superseded`.
- If an active workout already exists:
  - the same issued plan already produced it and it is in progress → return `200` with that
    workout (adopt; the plan is consumed);
  - a different plan is active → `409 workout_active` with `details.workout_id`; the client
    refreshes `today` and asks the owner whether to resume or abandon;
  - the plan is consumed and its workout is completed/abandoned → `410 plan_consumed` with
    `details.workout_id`.
- Otherwise call the existing `workout.start` with the stored plan, readiness values,
  `readiness_ack` as `allow_partial_readiness` and `prescription_id`. The client cannot submit
  a plan. Mark `consumed_at` and `workout_id` in the same transaction; a failure must leave no
  partial consumption or workout.
- Response `200`: the existing `workout.get` payload (plan, sets, forms, readiness snapshot,
  elapsed seconds, comparison). The client uses this to render/resume the workout.
- Idempotency: same key + same body returns the stored workout; a different body with the same key
  is `409 idempotency_conflict`. The set/start operations also use their own retry safeguards
  described below.

### 5.4 `POST /api/ios/v1/workouts/{id}/sets`

Appends one performed set. No update/remove route exists in Phase 2.

```json
{"exercise_id": "competition_squat", "load_kg": 140, "reps": 3, "rir": 2,
 "velocity_mps": 0.62, "set_index": 3, "plan_item_index": 0}
```

- Required: `exercise_id` and `reps`. Optional: `load_kg`, `rir` (0–6), `velocity_mps`
  (manual mean velocity; >0 when present; omit or 0 for not recorded), `set_index`,
  `plan_item_index`.
- The client sends the next `set_index` per exercise. The server uses the existing
  `workout.add_set`; a repeated set index is a no-op that returns the workout, so a lost response
  cannot append a duplicate. The `Idempotency-Key` is the second layer.
- Reuse the existing manual-set validation. `velocity_mps` maps to the existing `velocity`
  field; no per-rep table and no device import in Phase 2.
- The workout must be `in_progress`; otherwise `409 workout_not_active`. Unknown workout →
  `404 workout_not_found`. A completing/abandoning workout rejects the set.
- The client offers the plan’s exercises and exercises already logged; the server keeps the
  existing add-set rules (no new plan-edit behaviour).
- Response `200`: the existing `workout.get` payload with the new set and events.
- No `update-set`, `remove-set`, plan swap, set-count change or load/reps override is added.
  Those remain Phase 4 or web-only.

### 5.5 `POST /api/ios/v1/workouts/{id}/form`

Records the optional 1–5 post-lift form rating.

```json
{"exercise_id": "competition_squat", "rating": 4, "note": "optional"}
```

- `rating` is an integer 1–5; `note` optional. The exercise must be in the plan or already
  logged. The workout must be in progress. Reuse `workout.set_form_rating`.
- Response `200`: the existing workout payload with `forms`.
- This is optional human feedback only: no rubric score, calibration or training decision is
  computed by the client or by this route. The rubric/review screen is deferred.

### 5.6 `POST /api/ios/v1/workouts/{id}/complete`

Finishes the workout.

```json
{"session_rpe": 7, "not_recorded": false, "duration_min": 62.5, "notes": "optional"}
```

- Exactly one of `session_rpe` (1–10) or `not_recorded: true` is required; otherwise
  `400 session_rpe_required`. `duration_min` is optional and positive; when omitted the server
  uses its measured elapsed time. `notes` optional.
- Reuse `workout.end`. The server labels manual versus measured duration and materialises the
  session exactly once. A retry with the same idempotency key returns the stored response; a repeat
  with a different key sees the completed workout and must not materialise again.
- Response `200`: the existing completed `workout.get` payload. No summary screen is required in
  Phase 2; the completed session appears in Today/History and the existing progress/feedback
  services. Productivity is deferred.

### 5.7 `POST /api/ios/v1/workouts/{id}/abandon`

Abandons the in-progress workout.

```json
{}
```

- Reuse `workout.abandon`. No reason field in Phase 2. An already-abandoned/completed workout
  with a new key → `409 workout_not_active`; a retry with the same key returns the stored response.
- Response `200`: the existing workout payload with status `abandoned`.

### 5.8 `GET /api/ios/v1/progress?weeks=&date=`

Already implemented in Phase 1 and unchanged. Phase 2 adds the **client** Progress screen that
consumes it; no new server calculation, route or payload. Exact `progress_feature.dashboard`;
`weeks` 1–52, default 8; invalid query → `400 fields`.

### 5.9 Bootstrap capabilities

Phase 2 adds `readiness_write` and activates the write capabilities. The version stays `1`;
capabilities distinguish the phase:

```json
{"readiness": true, "readiness_write": true, "prescription": true,
 "workout_write": true, "healthkit": false, "offline": false}
```

- `readiness` remains the read capability. `readiness_write`, `prescription` and
  `workout_write` are false when `ios.mutations_enabled` is false.
- The client shows write UI only when the corresponding capability is true; otherwise it remains a
  read-only client with a clear server-disabled message. Do not infer capability from the app build.

### 5.10 Error and conflict map

| status | code | use |
|---|---|---|
| 400 | `validation_failed` / `unknown_field` / `idempotency_key_required` / `idempotency_key_invalid` / `session_rpe_required` | request validation |
| 401 | `authentication_required` | missing/unknown token |
| 403 | `device_revoked` | revoked device |
| 404 | `plan_not_found` / `workout_not_found` / `not_found` | unknown resource/route |
| 409 | `readiness_required` / `confirmation_required` / `workout_active` / `workout_not_active` / `idempotency_conflict` | resolvable conflict |
| 410 | `plan_expired` / `plan_superseded` / `plan_consumed` | issued plan no longer usable |
| 411/413/415 | existing | body handling unchanged |
| 503 | `ios_mutations_disabled` | server rollback switch |

- The client branches only on `code`; it shows `error` for the copy and `fields` inline.
- `details` may contain a workout id, readiness status/basis, or deload/drop reason. It never
  contains paths, stack traces, tokens or codes.
- 5xx remains a generic body; details stay in the server log.

## 6. Idempotency and retry rules

- The client generates one UUID per intended mutation and reuses it for every retry of that exact
  request. It generates a new UUID only when the request body changes (for example after a
  confirmation decision or a corrected readiness field).
- The server normalizes the key to lowercase and stores it in `ios_operation_receipt` with the
  device id, route, canonical body hash, status and response. Same device+key+route+hash → replay
  the stored 2xx response (`Idempotent-Replay: true`). Same key with a different route or body →
  `409 idempotency_conflict`. A missing key → 400; no mutation is processed.
- A network timeout is not a client failure: the app keeps the entered values, shows “not confirmed
  yet”, and retries with the same key. It never claims “saved” before a 2xx response.
- Receipts are pruned after 30 days. Issued plans/receipts are device-scoped; one device cannot use
  another device’s plan or receipt.
- Start also adopts the active workout as in §5.3; set also deduplicates by `set_index` as in
  §5.4. These are independent of the receipt and protect against a lost response and a new key.

## 7. Readiness semantics

- The client sends only non-empty fields, using the existing 1–5 and measurement scales; it never
  sends 0 for missing, never invents a score, and never writes a future/historical day.
- The server validates with `readiness_utils.validate`, records manual values with manual-over-
  import precedence, and returns the existing readiness payload including score, basis, overrides
  and settings. The client displays the server result; warnings and an unknown/insufficient status
  remain visible.
- A prescription may be requested only with a score-ready day or an explicit `readiness_ack` as
  in §5.2. The acknowledgement is recorded on the issued plan and is not a client-computed score.
- No presets, context flags, override writes or wearable/HealthKit import in Phase 2. HRV, RHR,
  bodyweight and wearable score are manual fields here; HealthKit provenance is Phase 3A.

## 8. Prescription and start semantics

### 8.1 Issue

- The server builds one auto-session prescription for the server-local today using the existing
  deterministic path, the existing readiness snapshot and the existing deload/drop decisions.
- The client never submits plan/items/prescription content. The route rejects such fields.
- The response is the exact plan the server stored; the client only displays it and starts by id.
- One live unstarted plan per device; a new issue supersedes the previous one. The plan expires
  after 60 minutes. Starting consumes it. Expiry/supersession never deletes the normal
  prescription row.

### 8.2 Persistence

- At issue, persist the normal `prescription`/`prescription_item` rows (and existing modifier
  provenance) exactly as the web start path does. The issued plan links to `prescription_id`.
- The issued plan stores the exact `plan_json` because the prescription tables do not retain
  warm-ups, notes or the resolver snapshot.
- Starting creates the workout with that `prescription_id`; the issued plan is marked consumed
  and linked to `workout_id` in the same transaction.

### 8.3 Start

- The client sends only `issued_plan_id`. The server fetches the plan; the client cannot supply a
  plan, items, loads or readiness values at start.
- The server checks the device, expiry, supersession, consumption and active workout as in §5.3.
  It never creates a second active workout.
- The workout snapshot is exactly the issued plan and readiness values; later prescription
  regeneration cannot rewrite what the client started.

## 9. Workout mutations

- Add set only. Fields and validation as in §5.4. Manual VBT is an optional positive mean
  `velocity_mps` per set; it is stored in the existing `workout_set.velocity` field and shown in
  the workout/history detail. No per-rep data, device import or velocity-loss scoring in Phase 2.
- Optional form rating as in §5.5; no rubric/calibration.
- Complete/abandon as in §5.6/§5.7. Exactly-once materialisation; no second session on retry.
- No plan edits, exercise swap, set-count change, set update/remove, or load/reps overrides. Those
  remain web/CLI (and set correction is Phase 4). The phone records performed work only.
- Every mutation returns the full current workout; the client updates from the response and never
  treats local state as saved.

## 10. Swift client (`StrengthApp` repository, `main`)

### 10.1 Screens and navigation

- **Today:** existing server date/readiness/active-workout view plus:
  - “Log readiness” opens a readiness form sheet.
  - “Start workout” requests an issued plan and opens the prescription preview.
  - If a workout is active, a “Resume workout” card reopens it from `today.active_workout`.
- **Readiness form:** the current manual fields, grouped: core 1–5 scores; optional HRV/RHR/
  bodyweight/wearable; optional legacy per-lift labels; optional note. Empty fields are omitted.
  Save → server payload; show status/score/basis and warnings; no client score.
- **Prescription preview:** plan items, sets/reps/RIR/loads, estimated time, warnings and rationale
  references as returned. No editing. Explicit **Start**. If the server returns
  `confirmation_required`, show the server’s deload/drop details and accept/decline; resend with
  confirmations and a new idempotency key.
- **Active workout:** plan items and performed sets; add-set form with exercise, load, reps, RIR and
  optional mean velocity (m/s); optional 1–5 form rating; finish/abandon. Show a clear
  server-acknowledged state after each 2xx; on failure keep the entered values and offer retry with
  the same key. No edit/remove.
- **Completion:** RPE 1–10 or “not recorded”, optional duration prefilled from the server’s elapsed
  value, optional notes. Submit → server response; return to Today/History. No client summary
  calculation.
- **Progress:** new read-only screen using the existing `/progress` payload; default 8 weeks,
  selector 1–52; coverage, performance, volume, back symptom, attendance and the server’s note; no
  calculations. Empty/error/retry and pull-to-refresh.
- **History:** existing Phase 1 screen; refresh after completion; no edit actions.
- **Settings:** existing; show server URL, device, app version and Forget. Optionally show the
  bootstrap capabilities/version. No mutation toggle in the app; the server flag controls it.

### 10.2 API client and models

- Extend the one `IOSAPIClient` with: readiness write, issue prescription, start workout, add set,
  form rating, complete, abandon and progress. All mutations set `Content-Type: application/json`,
  `Authorization: Bearer` and `Idempotency-Key`; no mutation retries at the transport layer.
- Add strict DTOs for the issued plan, workout detail (plan/items/sets/forms), progress dashboard,
  readiness payload and error envelope. Unknown keys are ignored; missing/mistyped required keys are
  a decoding failure. Use the server’s canonical units and server-local dates.
- Map `401/403` to the existing unpair flow; map `400` fields inline; map `409` by `code`
  (readiness/confirmation/active/idempotency); map `410` plans to “expired/used”; map
  `503` to “server has iOS writes disabled”; 5xx stays generic.
- Gate all Phase 2 write UI on `bootstrap.capabilities`. If the server is older or the flag is
  false, remain read-only with a clear message.
- Keep the Phase 1 redirect hardening: no redirect outside the paired origin (scheme, host,
  effective port); the bearer token cannot be forwarded cross-origin.

### 10.3 Retry and saved-state rules

- One idempotency key per intended mutation; retain it across network retries. Never generate a new
  key merely because a request timed out.
- Do not clear the local form or show “saved” until the 2xx response. On an error, keep the values
  and show the server message/code. A definitive 409/410 is not retried automatically.
- The active workout is refreshed from `today` on foreground; there is no offline queue or local
  outbox. Cached reads may be shown only as clearly stale, never as a fresh prescription or
  completed session.

### 10.4 Manual VBT

- The add-set form exposes an optional “Mean velocity (m/s)” field. It must be >0 when present;
  empty means not recorded. It is the set mean, not per-rep data. The client displays the returned
  velocity alongside the set and never computes RIR, load or a velocity-loss score from it.
- No HealthKit, device CSV, per-rep entry or VBT analysis in Phase 2.

### 10.5 Progress

- The Progress screen consumes `GET /api/ios/v1/progress` exactly as returned. It does not
  recompute coverage, ratios, volume, attendance or symptoms in Swift.

### 10.6 Storage/security

- Reuse Phase 1 Keychain token storage and non-secret UserDefaults. Never store the token, a
  pairing code, an issued plan secret or a receipt in UserDefaults/logs.
- No analytics, telemetry, crash reporting, third-party endpoint or Internet fallback.
- “Forget this device” remains local-only; server revocation remains CLI-only.

## 11. CLI and parity

- No new CLI commands in Phase 2. The existing `strength-coach readiness`, `workout`,
  `history` and `run` commands operate on the same Python services and remain the fallback;
  the owner can inspect/finish an iOS-started workout with them.
- The `ios` command group remains `pair`, `devices` and `revoke`. Issued plans and receipts
  are internal; there is no new public CLI surface and no web UI for them.
- The web/CLI routes and behaviours are unchanged. The iOS facade is additive.

## 12. Tests

### 12.1 Python — new `tests/test_ios_workflow.py` (live-server fixture, temporary SQLite)

- Readiness: valid write persists and returns the existing payload; manual-over-import precedence;
  unknown/zero fields 400; empty body 400; today-only (no date field); idempotent replay appends
  nothing; unauthenticated 401; revoked 403.
- Prescription issue: auto session type; readiness required/ack; scheduled deload/drop
  confirmation required and resend; reactive deload warning; 60-minute TTL; supersession; one live
  plan per device; normal prescription rows persisted; exact plan JSON returned; client plan content
  rejected; unknown fields 400; config flag off 503.
- Start: issued-plan id only; other device 404; expired 410; superseded 410; consumed+active adopts;
  consumed+completed 410; active other 409; retry same key; no second workout; workout snapshot and
  `prescription_id` link; no plan content accepted.
- Add set: append-only; manual VBT stored; set_index retry no-op; idempotent replay; invalid
  reps/RIR/velocity 400; completed/abandoned 409; response payload; no update/remove routes.
- Form: 1–5; plan/set membership; completed 409; idempotent.
- Complete: RPE or explicit not-recorded; duration manual/measured; retry materialises once; history
  shows the session; abandon; completed/abandoned transitions.
- Idempotency: same key/body replay; different body/route 409; receipt expiry/pruning; device
  scoping.
- Progress: unchanged Phase 1 route; payload equality; invalid weeks/date 400.
- Secrets: no token/code in logs, error bodies or receipts; no plan content in logs.
- Regression: existing `/api/*` and CLI behaviour unchanged; all existing tests pass.

### 12.2 Swift

- `IOSAPIClient`: request/decoding for readiness, issue, start, set (including manual VBT), form,
  complete, abandon and progress; `Idempotency-Key` presence; 401/403/409/410/503 mapping;
  capabilities gating; no plan content in any request.
- `AppModel`: readiness → issue → start → add set → finish; retry reuses the key and keeps local
  values; no “saved” before 2xx; confirmation/active/expired branches; Progress decode; forget/auth
  flows unchanged.
- The Phase 1 unit suite (29 tests, including same-origin redirect coverage) plus the new tests.
- Optional live UI smoke test: full happy path against a temporary local server, including one
  manual-VBT set and the Progress screen; skipped unless a Phase 2 LiveConfig is generated. Not a
  release gate.
- Plain app builds may use `CODE_SIGNING_ALLOWED=NO`; simulator tests need normal ad-hoc signing
  for Keychain, as in Phase 1.

### 12.3 Existing gates

Default `pytest`, `tests/test_docs_manifest.py`, `tests/test_docs_consistency.py` and
`ruff check .` must pass. Existing readiness, prescription, workout, history, feedback, docs and
Swift Phase 1 tests must remain unchanged and green.

## 13. Acceptance criteria

1. A paired iPhone can save today’s readiness (core + optional fields), with manual precedence and
   server-returned score/basis/warnings.
2. It can request an auto prescription, see the immutable plan preview, start it by issued-plan id,
   and no plan content is sent by the phone.
3. It can add performed sets (including optional manual mean velocity), see server-acknowledged
   state, and cannot fabricate a “saved” state.
4. It can complete with RPE or explicit not-recorded and see the session in History; a retry does
   not create a second session.
5. It can abandon an active workout; it can resume an active workout after relaunch via `today`.
6. It can record optional 1–5 form ratings; no rubric scoring is performed.
7. It can read the existing Progress dashboard; no client calculation exists.
8. Expired/superseded/consumed plans, another device’s plan, readiness gate and confirmation
   branches return the documented codes; the client shows the right next action.
9. Idempotency: same key/body replays, different body/route conflicts, retries never duplicate a
   set, workout, completion or materialised session.
10. No token/code appears in logs, error bodies, receipts or the Logs page; no external network.
11. Existing web/CLI routes and stored training behaviour are unchanged; the config flag off leaves
    reads working and mutations cleanly unavailable.
12. The full default suite, docs tests and `ruff` pass; the Swift unit tests pass; a live UI smoke
    test passes on the iPhone 18 Pro simulator against a temporary SQLite database; the owner
    completes one normal session and the device acceptance pass on the physical iPhone.

## 14. Rollback

- First switch: `ios.mutations_enabled: false`. Reads (bootstrap/today/history/progress) remain
  available; every Phase 2 mutation returns `503 ios_mutations_disabled`; the client shows a
  read-only/disabled message.
- Remove the Phase 2 routes and config; the existing web/CLI routes continue.
- Drop `ios_issued_plan` and `ios_operation_receipt`. Pending plans and retry receipts are lost;
  prescriptions and workouts already committed by a started session remain valid and auditable.
- Existing `ios_device`/`ios_pairing_code` and Phase 1 reads remain. Do not change any existing
  training, readiness, prescription, workout or review row as part of rollback.
- **Back up first.** `0053` is applied to the one live `data/coach.db`; take the consistent backup
  described in [`IOS-CLIENT-PLAN.md`](../IOS-CLIENT-PLAN.md) §13.1 with the server stopped before
  applying or dropping anything.
- **Drop the tables and their `schema_migration` row together.** Dropping only the tables leaves
  `0053` recorded as applied, so `migrate()` skips it forever and a later re-enable has no tables
  and no way to recreate them. Use the paired statement in
  [`IOS-CLIENT-PLAN.md`](../IOS-CLIENT-PLAN.md) §13.2, which includes `ios_operation_receipt`,
  `ios_issued_plan` and the matching `schema_migration` row.
- Client rollback: return to the Phase 1 read-only screens or discard the Phase 2 build; the token
  and pairing remain.

## 15. Decisions

Owner-approved for this contract (2026-11-07):

1. **Manual VBT is included**: optional mean `velocity_mps` per set, >0 when present, stored in
   the existing set velocity field. No per-rep data or VBT analysis.
2. All other recommendations are accepted: full current manual readiness form, readiness
   acknowledgement, auto-only prescription with server safety confirmations, 60-minute single-use
   issued plan, one live plan per device, normal prescription persisted at issue, active-workout
   adoption/today-only, no plan editing, add-set only, RPE/not-recorded, optional form ratings,
   Progress screen, idempotency header with 30-day receipts, conflict codes, device scoping and the
   mutation flag.
3. Corrected against the live code: nutrition, hydration, body fat and grip are **not** readiness
   inputs (`DEC-READINESS-20`, `DEC-MEASURE-02`, `DEC-GRIP-01`). The accepted readiness fields
   are the ones in §5.1.
4. Deferred: rubric/review screen, productivity rating, per-rep VBT, HealthKit, offline queue and
   reconciliation, Apple Intelligence/PCC, sleep features and web authentication. Each needs its
   own later approval.

Settled defaults for this contract: 60-minute issued-plan TTL; 30-day receipt retention; 8-week
Progress default with 1–52 selection; one active issued plan per device; 503 for disabled
mutations. These are config/contract values, not new training rules.

## 16. References

- [`IOS-CLIENT-PLAN.md`](../IOS-CLIENT-PLAN.md) — phase boundary, invariants, rollback gates.
- [`IOS-PHASE-1-CONTRACT.md`](IOS-PHASE-1-CONTRACT.md) — accepted Phase 1 interface and
  completion record.
- [`API.md`](../API.md) — existing routes, body limits, error behaviour, date semantics.
- [`READINESS.md`](../READINESS.md), [`READINESS-SCORE.md`](../READINESS-SCORE.md) — readiness
  merge, manual precedence, score status and override rules.
- [`DATA-MODEL.md`](../DATA-MODEL.md) — append-only records, workout/session tables and schema
  conventions.
- [`WORKOUT-GENERATION.md`](../WORKOUT-GENERATION.md) — deterministic prescription pipeline.
- [`PRIVACY.md`](../PRIVACY.md) — public/private boundary and no personal data in the repository.
