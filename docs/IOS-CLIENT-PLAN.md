# Native iPhone Client — Local-First Implementation Plan

**Status:** proposal only; not approved for implementation. This document describes a possible native companion and its prerequisites. No iOS project, API route, database migration, HealthKit integration, or production code is created by this plan.

**Constraint:** core app operation, readiness/prescription, capture, HealthKit import and sync must work offline and may communicate only with the owner's Python server on a trusted LAN. There is no general Internet fallback, cloud sync, analytics, telemetry or third-party endpoint. A separately configured Apple Intelligence option may send only the explicitly selected model request to Apple's Private Cloud Compute (PCC); this is an intentional, visible network exception, not part of local-server sync, and is off by default. HealthKit records never go to PCC by default; any future request that includes personal workout/health content requires a separate explicit, per-use consent and privacy review. iOS services such as Health-data sync, device backups, App Store distribution and OS updates remain separate system behavior. Exclude the app's own sensitive database from cloud backup and explain that Health/iCloud settings are user-controlled.

## 1. Recommendation

Build a small native SwiftUI client as a **thin, local-first interface to the existing Python application**. Keep Python authoritative for readiness calculation, workout selection, load/RIR/set decisions, validation, and stored prescriptions. The iPhone owns interaction, HealthKit permission/query code, a locally persisted cache protected by iOS Data Protection, and a durable outbox; it does not port domain calculations.

Use one native app, not a separate Health Bridge. Direct, read-only HealthKit access is opt-in, but once enabled supported HRV/resting-HR (and an available device readiness score, if explicitly supported) should populate the matching readiness inputs automatically with source, freshness and baseline coverage visible. Manual values take precedence per field; a later HealthKit refresh must not erase a manual override. HealthKit is optional and never blocks readiness or training. The feature-complete first release should include manual cardio, reviewed import of completed Apple Workout summaries with available cardio metrics, HealthKit-backed readiness inputs, and native post-workout review. Treat XML export as a possible one-time historical backfill only. Do not use Health Auto Export as a core dependency.

The **first vertical slice** should be: pair to the local server; fetch today's authoritative state; save a daily readiness check-in; request and review a server-generated prescription; start a session; log/remove/correct sets; finish with manual session RPE; then complete post-workout review on the phone, including form ratings and any chosen rubric marks; retain/reconcile local work safely. Add manual cardio entry. The next slice adds reviewed HealthKit cardio import and HealthKit HRV/RHR auto-fill into readiness with a test proving manual override precedence. Before the feature-complete first release, demonstrate these flows, local-server sync, deduplication and source-labelled display on the target iPhone. Apple Intelligence is a later opt-in capability, separate from this release gate.

**Release gate:** do not connect the iPhone to the present unauthenticated home-LAN HTTP API. Add an authenticated, versioned API facade, local-only destination enforcement, and a tested HTTPS/trust approach first. The current server's accepted no-auth/no-TLS risk (`LIM-57`) is not an adequate credential boundary for a native app holding health data.

## 2. Current-state repository assessment

### 2.1 What exists

| Area | Current source of truth | What an iPhone client can reuse |
|---|---|---|
| Architecture | `strength_coach/` Python package; SQLite in `data/coach.db`; numbered SQL migrations; browser client in `strength_coach/web/` | The existing Python services, validated APIs and database remain the only authority. The iOS project should be a separate `ios/` subdirectory. |
| Web/API | `strength_coach/web/server.py`; current contract in [`API.md`](API.md) | Existing routes already cover readiness, prescription preview, live workout lifecycle, manual sets, history, progress/outcomes, cardio and measurements. Add a versioned iOS facade rather than change existing routes used by the web UI. |
| Workout generation | `strength_coach/prescribe/`, `strength_coach/workout.py`, `strength_coach/features/readiness.py`, `readiness_score.py`, `lift_readiness.py`, `readiness_baseline.py`, `strength_coach/rules/` | Reuse by calling Python. Do not reproduce selection, readiness score, fatigue modifiers, load solver, rule checks, set budget, or session-type logic in Swift. |
| Readiness | `readiness_day`, append-only `readiness_entry`, `readiness_override`, readiness settings; `features/readiness_score.py`; `docs/READINESS.md` | The five subjective fields are sleep, energy, mood, soreness, stress (1–5; higher is better). HRV/RHR are optional device fields and affect the score only with the existing baseline requirements. Manual values override imported values per field. Context flags are display-only by default. No HealthKit source is currently part of the manual entry contract. |
| Prescription | `POST /api/prescribe`; `POST /api/workout/start`; append-only prescriptions and a frozen plan snapshot | Fetch a server-produced plan and warnings; preserve the returned plan/version/digest. Do not calculate a new plan on the phone. Existing workout start can accept a plan payload, so the iOS facade must verify the plan was issued by this server and was not altered. |
| Live strength capture | `strength_coach/workout.py`; `workout_session`, `workout_set`, `workout_event`; `/api/workout/<id>/sets`, `remove-set`, `update-set`, `end`, `abandon` | Existing set values are canonical exercise id, kg, repetitions, RIR and optional velocity. Set additions are append-only, a removed set is an event, completed sessions retain a snapshot, and multiple fragments may exist on one date. Add stable client event IDs for retry safety. |
| Cardio | `strength_coach/features/cardio.py`; `cardio_log` migration `0011`; `/api/cardio` | Current row stores date, open-vocabulary modality, duration seconds, average/max HR, distance, manual sRPE 1–10 and note. It has no HealthKit UUID, source/device, source timestamp, or imported-effort field. Summary is descriptive and shows WHO reference lines as context; there is no cardio prescription or fatigue model. |
| Measurements | `features/measurements.py`; `metric_definition` and append-only `measurement`; migration `0012`; periodic values include VO₂max, function and steps where configured | Reuse only metrics whose unit, direction and aggregation are already defined. `measurement.source` presently distinguishes `user`, `clinician`, `device`, not the individual HealthKit object/source. A provenance/dedup layer is needed before HealthKit imports can materialize measurements. |
| History/progress | `strength_coach/history.py`, `store/queries.py`, `GET /api/history`, `/api/progress`, `/api/outcomes`, `/api/measurements` | Use server summaries and pagination; do not create an independent analytics implementation in Swift. |
| Authentication/network | No user/session authentication; default home-network server binds `0.0.0.0` over HTTP (`LIM-57`). Existing security note says never expose publicly. | Add a separate device-token pairing/revocation path scoped to local API routes. Keep credentials in iOS Keychain and server-side hashes only. Introduce local HTTPS or a narrowly reviewed secure equivalent. |
| External model boundary | `NullLLM` is the default, but external LLM providers can be configured for selected web/CLI paths; `selection_llm` is accepted by existing prescription endpoints. | iOS training APIs must force deterministic/no-remote behavior. A later native AI feature may use Apple `SystemLanguageModel` on-device or explicitly enabled Apple PCC; neither is reachable through the Python prescription API. |
| Tests/docs | pytest suite, synthetic fixtures, API/browser tests, docs manifest and consistency checks | Preserve all existing tests. Add a versioned API contract, backend integration tests, Swift unit/UI tests, synthetic HealthKit payload fixtures, and offline/retry tests. |

### 2.2 Native value versus the existing mobile web UI

The current responsive web UI is already a serious phone surface. It includes readiness, prescription preview, a workout logger, history and the consolidated Longevity page. The previous iPhone audit improved cards, touch targets, navigation, accessibility and form validation. Therefore, a native app is **not justified merely to redraw the same pages**.

Native adds material value for: durable offline capture when the local server is unavailable; a first-class HealthKit permission/query path; local notifications only if later wanted without remote push; Keychain-backed pairing; faster, thumb-first workout capture; and explicit retry/sync state. It also adds a second UI to maintain, Xcode/signing requirements and an OS-specific testing burden. Keep administrative/configuration surfaces (exercise taxonomy, rules, LLM settings, policy YAML, profile/volume configuration, import/export administration and calibration controls) web/CLI-only in v1. The phone is for daily use, not a second administration console.

### 2.3 Existing decisions that constrain the design

- The methodology states that Python produces all numerical prescription outputs and scores; missing data is unknown, not zero; no automatic readiness-weight tuning; and no diagnosis or cardio prescription. The phone must not change these boundaries.
- Readiness accepts partial inputs, but a current/future workout requires either a score-ready assessment or an explicit acknowledgement that no readiness score will be applied. The app must surface that exact server decision. HealthKit may fill only supported physiological/device fields (such as HRV/RHR); it must not invent subjective sleep, energy, mood, soreness or stress ratings.
- The current cardio model is descriptive. The WHO 150–300 moderate or 75–150 vigorous minutes are a population reference, not an individualized target. A cardio record with no validated intensity must not be counted as moderate/vigorous minutes merely because its modality is “run” or “bike.”
- Manual readiness, training, measurement and workout events are append-only or corrected by superseding events. HealthKit import must preserve source and conflicts rather than overwriting user-entered data.
- `docs/METHODOLOGY.md` currently says sleep is outside the app's scope and cardio/measurements are context, not prescriptions. A read-only sleep panel is therefore not MVP; any later addition needs an explicit scope decision and must not become sleep coaching or an unreviewed readiness input.

## 3. Product scope

### 3.1 Must have for the first useful release

1. **Today/readiness:** show the server's local date, current readiness values/sources/score/status, context flags, freshness/baseline coverage, and missing data. Enter the five 1–5 subjective fields; import supported HRV/RHR and device readiness values from HealthKit when permission and samples are available. Distinguish manual and HealthKit values per field, let the user replace/override an imported field manually, and never let later import overwrite that override. Save partial check-ins without coercing blanks to zero; Python computes the score.
2. **Request workout:** ask Python for the date/session prescription; display plan, warnings, rule references, modifiers and readiness acknowledgement exactly as returned. User confirms before start. No Swift-side plan construction.
3. **Strength capture:** one card per exercise, set entry for repetitions/load/RIR and optional velocity, notes, timestamps, completion state, remove/correction events and undo where practical. Preserve selection and prefill sensibly. A set must be durable locally before the UI reports it saved.
4. **Finish and review:** end/abandon flow; manual session RPE 1–10 remains distinct from Apple effort; duration is measured or explicitly entered, not guessed. Provide a native post-workout review using the server's session sheet: per-exercise 1–5 form rating and notes, optional rubric item marks/confidence/note, session RPE, duration, and productivity. Show existing feedback/form context, allow skipping optional items, and submit through the existing authoritative services. The review is descriptive/calibration input and does not change the prescription. An offline session/review remains locally saved and visibly unsynced until acknowledged.
5. **Offline capture and sync:** persist changes locally, sequence them, retry transient failures and show pending/synced/failed states. If the server is unavailable, the app may log performed work but cannot request a fresh authoritative prescription or calculate a readiness score.
6. **Recent history and progress:** read-only recent workout history and the existing server summaries for weekly volume, RIR, tonnage, residuals, readiness and supported measurement history. Clearly label stale cached views.
7. **Cardio capture and HealthKit:** enter a manual cardio summary through the existing domain fields (modality, duration, HR, distance, manual sRPE, note); import completed HealthKit cardio-workout summaries and available linked HR/distance after per-type opt-in and user review. Preserve HealthKit's Apple-effort record separately from manual sRPE. This import is required for the feature-complete first release, but permission remains optional and missing HealthKit data never blocks manual capture.
8. **Local pairing/privacy:** pair to a single configured local Python server, persist a revocable bearer token in Keychain, explain HealthKit and local network permissions, and make local-only behavior testable.

### 3.2 Should have after the vertical slice

- Read-only HealthKit imports for steps, HRV, resting HR, body mass and VO₂max, with per-type consent, observed-date coverage, timestamps, units and source/device provenance. HRV/RHR readiness values belong in the first useful release; steps/body mass/VO₂max remain later descriptive context unless needed sooner.
- Additional workout-linked heart-rate time-series/energy fields when actually useful; keep raw time-series on the phone by default and make no fatigue or dose model.
- A Longevity screen extension for observed cardio sessions/minutes by modality, clear data coverage, selected HealthKit trends and existing measurements, with no interpolated missing dates.
- Explicit Apple-workout-to-app-session association UX for cases where identity is clear to the owner; never silently merge an Apple summary into a strength session.

### 3.3 Later / gated

- Background HealthKit observer delivery; consider after foreground anchored-query sync is reliable. Background delivery is best effort, not a promise of immediate capture.
- Sleep-duration trend, only if the owner approves changing the current “sleep outside scope” boundary. Do not import sleep stages into a score or present a consumer sleep estimate as a clinical measure.
- Historical XML import, only for an explicit one-time backfill need. It is a full manual export, not an incremental feed.
- An optional Apple Intelligence assistant through the Foundation Models framework. Start, if approved, with an on-device-only `SystemLanguageModel` for bounded explanatory tasks; optionally allow a separately selected Apple PCC mode for stronger models when online. PCC is an explicit Apple network exception and is never a fallback unless the user has enabled it.
- Live iPhone cardio workout sessions, GPS/routes, Live Activities, external HR sensors, Apple Watch companion, HealthKit writes, HealthKit workout creation, Apple effort display, and complex analytics. These add lifecycle/device costs and are unnecessary to prove the workout-capture vertical slice.
- Additional administrative tools or editing training rules/configuration: web/CLI-only.

### 3.4 Explicit v1 exclusions

No general public/cloud backend or Internet fallback for core app features; no iCloud/app cloud sync; no analytics, telemetry, crash-reporting or vendor SDKs that phone home; no third-party exporter dependency; no Apple Intelligence in the initial release; no PCC unless explicitly enabled as the Apple-only AI network exception; no sending HealthKit values to any model by default; no offline prescription or readiness computation; no automatic Apple workout merge; no inferred sets/reps/loads; no converting Apple Workout Effort into manual sRPE; no HealthKit overwrite of a manual readiness value; no prescription/cardio-fatigue change; no sleep coaching, diagnosis or medical alerting; no public App Store product work as an MVP dependency.

## 4. Proposed client/server architecture

```mermaid
flowchart LR
  subgraph iPhone[Native SwiftUI app — local-first]
    UI[Today / Readiness / Workout / History / Longevity]
    HK[HealthKit reader — opt-in, read-only]
    DB[(iOS Data-Protection-protected local store)]
    OUT[Durable outbox + HealthKit anchors]
    API[Allowlisted local API client]
    AI[Optional Apple Foundation Models — on-device mode]
    UI --> DB
    UI --> HK
    UI --> OUT
    HK --> DB
    DB --> OUT
    OUT --> API
    UI --> AI
  end
  PCC[Apple Private Cloud Compute — explicit opt-in only]
  AI -. apple_pcc mode only .-> PCC
  subgraph LAN[Owner's trusted local network]
    TLS[Local HTTPS + device-token auth]
    IOS[Local iOS API facade]
    SVC[Existing Python domain services]
    SQLITE[(Existing SQLite coach.db)]
    TLS --> IOS --> SVC --> SQLITE
  end
  API -->|Only configured LAN origin; no public fallback| TLS
  WEB[Existing local web UI] --> SVC
  CLI[Existing CLI] --> SVC
```

**Network invariant:** the core iPhone API client accepts only the paired host and a local/private address or approved `.local` name; it rejects arbitrary URLs, public IPs, redirect-to-public responses and cellular/off-LAN fallback. The separately gated Apple PCC route is reachable only from an explicitly enabled AI feature after per-request confirmation; it is never used for core sync and is not a fallback. No view model calls `URLSession` directly; route all connections through auditable, mode-specific transports.

**Layering:** SwiftUI views → feature view models → use cases (`SaveReadiness`, `RequestPrescription`, `StartWorkout`, `AddSet`, `FinishWorkout`, `ReviewWorkout`, `SyncOutbox`, `ImportHealthKit`, optional `ExplainSession`) → repositories (`LocalStore`, `IOSAPIClient`, `HealthKitRepository`, optional `AppleModelRepository`). The client maps DTOs and validates presentation-level input; Python remains the authority for domain validity and all calculations.

Suggested project layout (not created yet):

```text
ios/StrengthCoach/
  App/                         application entry, navigation, dependency wiring
  Features/Today/              readiness summary and workout request
  Features/Readiness/          1–5 self-report and server score display
  Features/Workout/            start, set cards, edits, finish/abandon
  Features/History/            paginated history and workout detail
  Features/Progress/           read-only server analytics
  Features/Cardio/             manual entry and imported workout review
  Features/Longevity/          sourced trends, coverage and measurement cards
  Features/Settings/           local server pairing, permissions, privacy, sync queue
  Infrastructure/API/          DTOs, transport allowlist, auth, error mapping
  Infrastructure/Persistence/  local database, migrations, cache, outbox
  Infrastructure/HealthKit/    authorization, anchored queries, normalization
  Tests/                       unit, fixture, API-contract and UI tests
openapi/ios-v1.yaml             proposed authoritative OpenAPI 3.1 contract
```

Default to system frameworks only: SwiftUI, HealthKit, URLSession, Keychain and Core Data/SQLite-backed local persistence. Do not add a third-party SDK that makes network calls. If a package is proposed, record whether it performs network activity and pin/audit its code; package retrieval during development is separate from runtime traffic.

## 5. API contract proposal

### 5.1 Design rules

- New namespace: `/api/ios/v1/`. Leave `/api/*` behavior unchanged for the web UI and CLI.
- OpenAPI 3.1: `openapi/ios-v1.yaml` is the authoritative proposed contract; generate/validate the iOS DTOs or contract fixtures from it. Add backend contract tests to prove schemas and status codes. Do not duplicate schemas in prose after implementation.
- Adapter handlers in `strength_coach/web/server.py` should call existing features/domain/store functions. Put new sync/auth/import behavior in narrow modules such as `strength_coach/ios_sync.py` and `strength_coach/features/healthkit_import.py`; keep route handlers thin. No broad domain rewrite is needed.
- Authentication: `Authorization: Bearer <device-token>` for every route except one-time pairing. Require scoped, revocable tokens. Require `Idempotency-Key: <UUID>` for every mutation. Include `X-Client-Version` and an app/device installation UUID (non-secret) for diagnosis.
- Every mutating request is one SQLite transaction: validate, append domain event/import record, append idempotency receipt, and return acknowledgement. Same key + same canonical body returns the original result; same key + different body is `409 idempotency_conflict`.
- Common error shape for new routes only:

```json
{
  "error": {
    "code": "validation_error",
    "message": "One or more fields are invalid.",
    "fields": {"values.sleep": "must be an integer from 1 to 5"},
    "retryable": false,
    "request_id": "opaque-id"
  }
}
```

Expected codes: `unauthenticated` (401), `forbidden` (403), `not_found` (404), `validation_error` (400), `idempotency_conflict` / `stale_plan` / `workout_conflict` (409), `payload_too_large` (413), `rate_limited` (429 only if implemented), and `internal_error` (500). Never return paths, secrets, stack traces, SQL or private data in errors. Existing routes keep their current envelope for compatibility.

- Pagination is cursor-based in the new API: `limit` default 50, max 100; `next_cursor` is opaque and stable under concurrent inserts. Date query bounds are inclusive local dates. Use canonical units in storage/API: kg, repetitions, RIR, seconds, metres, bpm, milliseconds, mL/kg/min, ISO date, and RFC 3339 instants with offset.
- `bootstrap` returns the server's configured IANA timezone and local date. Preserve capture's local date, timezone and absolute timestamp separately; never derive a training date from a UTC string slice. Existing API documentation says server-local date/timezone semantics are authoritative today; offline travel and DST must be explicit in the new contract.

### 5.2 Route list

All listed routes except pairing require a valid device token. All mutations require an idempotency key. The following are new versioned facade routes; their shapes are proposals, not implemented endpoints.

| Method and path | Request / response shape | Validation, idempotency and service mapping |
|---|---|---|
| `POST /pair/exchange` | Request `{pairing_code, installation_id, device_name}` → `{device_id, access_token, expires_at, server_identity}` | One-use, short-lived code generated from the server CLI; local-only; rate-limited; no open registration. Token shown once, stored in iOS Keychain, server stores only a hash. This is the only unauthenticated route. Revoke/rotate through local CLI. |
| `GET /bootstrap` | No body → `{api_version, server_version, server_time, local_date, timezone, catalogue_revision, capabilities, active_workout, health_import_types}` | Read-only. Returns feature/version availability only; no paths/config secrets or personal health data. Checks auth scope. |
| `GET /today?date=YYYY-MM-DD` | → `{date, readiness, active_workout, recent_summary, prescription_available}` | Read-only adapter over readiness/active-workout/read-summary queries. Use server date when date omitted. No new prescription side effect. |
| `GET /readiness/{date}` | → `{date, fields, sources, sample_times, score, category_scores, status, missing_fields, context_flags, recorded_at}` | Read-only. Preserve partial/unknown state and per-field source/freshness. Include the selected HealthKit value and manual-over-import decision. No iPhone-side score. |
| `POST /readiness` | Request `{date, values:{sleep?,energy?,mood?,soreness?,stress?,hrv_ms?,rhr_bpm?}, note?, context_flags?}` → `{readiness, score, sources, acknowledgement_required}` | Values are optional; subjective fields are integers 1–5; HRV/RHR are validated quantities. Manual values use source `manual` and override HealthKit values per field regardless of which was recorded later. HealthKit goes through the health import route with source metadata, never masquerading as manual. Repeated request returns prior response; correction is a new operation. |
| `POST /prescriptions` | Request `{date, session_type:"auto"|"squat"|"hinge"|"bench_squat"|"bench_hinge", allow_unknown_readiness:false, selection_options?}` → `{prescription_id, plan_token, plan_digest, generated_at, valid_for_date, session_type, items, warnings, readiness, rule_refs, engine_version}` | Server runs existing deterministic `/api/prescribe` service with LLM selection forcibly disabled. No client-supplied load/sets/RIR. `plan_token` binds exact returned JSON/digest, date, readiness snapshot and policy version for a later start; a stale/altered plan is rejected. A plan token is not an offline authorization to generate or change a prescription. |
| `GET /workouts/active` | → `{workout:null}` or `{workout:{id,date,status,plan,readiness,sets,events}}` | Read-only adapter over `workout.active`. Only one active fragment as current domain rule permits. |
| `POST /workouts` | Request `{plan_token, date, readiness_ack?, note?, client_workout_id}` → `{workout_id, prescription_id, started_at, status, plan_snapshot}` | Start existing workout lifecycle only with a server-issued plan token; validate current date, readiness gate/ack, policy version and no conflicting active workout. A repeated client UUID returns the original workout. Calls `workout.start`/existing start service; persists prescription/snapshot/provenance. |
| `POST /workouts/{id}/sets` | Request `{client_set_id, exercise_id, set_index, load_kg, reps, rir?, velocity_mps?, plan_item_index?, occurred_at}` → `{set_id, accepted_at, workout_revision}` | Canonical exercise id; load ≥0 subject to domain rules; integer reps >0; allowed RIR and optional velocity validated server-side; plan item must match frozen plan where supplied. Idempotent on operation key and stable client set UUID. Append set; no silent duplicate or overwrite. |
| `POST /workouts/{id}/sets/{set_id}/remove` | Request `{reason?}` → `{event_id, workout_revision, active_set:false}` | Append a removal event; never delete. Require active workout; duplicate operation returns prior event. |
| `POST /workouts/{id}/sets/{set_id}/correction` | Request `{load_kg, reps, rir?, velocity_mps?, reason}` → `{correction_event_id, corrected_set, workout_revision}` | Append correction; original value remains auditable. Reason required for sync reconciliation; duplicate operation returns prior correction. |
| `POST /workouts/{id}/complete` | Request `{ended_at, duration_source:"measured"|"manual", duration_s?, session_rpe?, session_rpe_not_recorded?, productivity?, notes?}` → `{workout_id, status:"completed", session_id?, ended_at, summary}` | Validate one of recorded sRPE 1–10 or explicit not-recorded; duration source honest; do not map Apple effort. Calls existing `workout.end` and materialization/critique pipeline. Idempotent completion. |
| `POST /workouts/{id}/form` | Request `{exercise_id, rating:1..5, note?}` → `{workout_revision, forms}` | Append an optional post-lift form rating for an exercise in the workout; rating remains the user's self-assessment and has no prescription effect. Corrections append/supersede via the established history path. |
| `GET /reviews/{session_id}` | → `{session, feedback, form_context, items:[{key,score,measurable,detail,question,anchors,existing}]}` | Wrap the existing session-review sheet and current form/prior-rating context. Server provides rubric information; the app must not calculate rubric scores. |
| `POST /reviews/{session_id}` | Request `{forms?:[{exercise_id,rating:1..5,note?}], scores, confidence, note?, session_rpe?, session_minutes?, productivity?}` → `{written, feedback, reviewed_workout, postprocess}` | Reuse current review service and append-only history form-correction path; user may add/correct per-exercise form self-ratings and selected rubric items, log optional feedback, and skip blank items. Idempotency/append-only handling must prevent retry duplicates. Review does not change training prescriptions. |
| `POST /workouts/{id}/abandon` | Request `{reason?}` → `{workout_id, status:"abandoned"}` | Append/record an explicit abandon; cannot silently convert completed session. Idempotent. |
| `POST /workouts/offline-import` | Request `{client_workout_id, performed_on, timezone, started_at, ended_at?, mode:"self_directed"|"cached_plan_context", cached_plan_digest?, sets:[...], manual_session_rpe?, notes?}` → `{import_id, status:"accepted"|"needs_review", unresolved_exercises, server_record_ids}` | Separate route for a workout captured while no online server workout exists. It is an import/manual session, not a server-prescribed live workout. Each set retains client UUID and timestamps. Unknown/ambiguous exercise or stale cached plan is quarantined/reviewed; never invent a prescription. Idempotent at workout and set level. |
| `GET /workouts/{id}` | → `{workout, plan_snapshot, modified_plan, sets, events, summary}` | Read-only detail. Do not expose raw DB paths. |
| `GET /history?from=&to=&cursor=&limit=` | → `{items:[...], next_cursor}` | Read-only; wraps paginated history/day-fragment query. Date filters inclusive in server/local-date semantics. |
| `GET /progress?from=&to=&window=` | → `{weekly_volume, rir, tonnage, residuals, readiness, measurements, coverage, generated_at}` | Read-only adapter over existing `/api/progress`, outcomes and readiness/measurement queries; no new calculations. Preserve missingness and source. |
| `GET /cardio?from=&to=&cursor=&limit=` | → `{items:[...], summary, coverage, next_cursor}` | Read-only; extend current cardio summary only with explicit source and intensity-known fields. WHO reference remains contextual. |
| `POST /cardio` | Request `{client_cardio_id, performed_on, timezone, modality, duration_s, avg_hr?, max_hr?, distance_m?, manual_srpe?, note?}` → `{cardio_id, source:"manual", accepted_at}` | Reuse `features.cardio`/cardio repository; validate current ranges and `avg_hr <= max_hr`. Manual sRPE is separate from any HealthKit score. Idempotent by client event ID. |
| `GET /measurements?metric_key=&from=&to=&cursor=&limit=` | → `{catalogue, entries, coverage, next_cursor}` | Read-only; exposes declared units/direction/method and exact observed records. No averaging across methods or interpolation. |
| `POST /healthkit/import-batch` | Request `{batch_id, device_id, timezone, records:[{external_id, kind, metric_key?, activity_type?, start_at, end_at?, value?, unit?, source_name?, source_bundle_id?, source_revision?, device_model?, aggregation?, deleted?, payload_digest}]}` → `{batch_id, accepted:[...], duplicates:[...], quarantined:[{external_id, code}], next_action}` | Strict allowlist of metric/activity types and payload cap; preserve source/time/unit/UUID where available; reject invalid units/ranges; dedupe by stable HealthKit object UUID + source; same UUID/different content creates an auditable superseding record or quarantine, not an overwrite. Apple effort is stored in its own field/type and never copied to manual sRPE. `deleted` creates a tombstone. Do not send raw HR time series by default. |
| `GET /healthkit/import-status?cursor=` | → `{last_batch, accepted_count, quarantined_count, coverage, next_cursor}` | Optional read-only reconciliation/status endpoint only if required; not a HealthKit anchor authority. HealthKit anchors stay on the iPhone and are advanced only after local staging succeeds. |

The `/healthkit/import-status` route is conditional; omit it if local per-batch acknowledgements and the server's observed-record query provide adequate recovery. Do not add a generic `/sync/all` or CRUD sync engine merely to save endpoint count.

### 5.3 Relevant current services and models

- Readiness: `features/readiness.py`, `features/readiness_score.py`, readiness queries/repositories, `readiness_day`, `readiness_entry`, `readiness_override`, `readiness_context`; add HealthKit provenance and deterministic source precedence without changing the existing HRV/RHR baseline rules.
- Prescription: `/api/prescribe` handler and existing deterministic prescribe/resolver/rules stack; append-only `prescription`/`prescription_item` and `prescription_modifier`.
- Workout: `strength_coach/workout.py`, `workout_session`, `workout_set`, `workout_event`; `strength_coach/history.py` for completed corrections.
- Cardio: `features/cardio.py`, `cardio_log` and queries; migration needed for source and external identity, or a separate import/link table.
- Measurements: `features/measurements.py`, `metric_definition`, `measurement`; migration needed for HealthKit import identity/provenance or a linked immutable source record.
- New infrastructure only: per-device token/pairing state, `ios_operation_receipt`, HealthKit source-record ledger, migration(s), and the API facade. Keep the new tables specific; don't create a generic replicated-object framework.

## 6. Data model and offline synchronization

### 6.1 Provenance and persistence

Keep existing app data and imported HealthKit data distinguishable. Proposed migration design (final columns require code/schema review before approval):

- `ios_device`: opaque device id, display label, hashed token, scopes, created/revoked timestamps, last-seen timestamp. No token plaintext.
- `ios_operation_receipt`: `(device_id, idempotency_key)` unique; operation type, canonical request digest, outcome, server record id(s), accepted timestamp and status. Store only what is needed to replay the exact acknowledgement; never store secrets or entire HealthKit payloads unnecessarily.
- `healthkit_record`: immutable normalized source record, `record_id`, `device_id`, HealthKit external UUID, record kind/metric/activity type, value/unit or summary, start/end instants, recorded/local date and timezone, source name/bundle id, source revision, device metadata, aggregation method, payload digest, imported/received timestamps, supersedes/tombstone fields and validation state. Unique external identity for duplicate protection. Retain only required normalized fields, not broad raw HealthKit payloads.
- Extend `cardio_log` with explicit source/external workout identity and source timestamp fields, or link `cardio_log` to `healthkit_record`; preserve append-only triggers and existing `/api/cardio` semantics. Keep `manual_srpe` in the existing field. Keep Apple `workoutEffortScore`/`estimatedWorkoutEffortScore` separate and source-labelled.
- For standard periodic measures, use `measurement` only if a `metric_definition` exists for the exact unit, direction and aggregation. Store `source='device'` and a link to `healthkit_record`. If a metric definition is absent, add it explicitly with the measurement review; do not turn an unknown unit into an existing metric.
- Materialize supported daily HealthKit HRV/RHR observations into the readiness merge so they fill those physiological readiness inputs automatically. Add an explicit `healthkit` source (or an equivalently precise provenance link) and migration; do not collapse the visible source label to generic `import`. Preserve sample timestamp, source/device, unit and aggregation. Deterministic per-field precedence is **manual > HealthKit > CSV import/other imported value**, independent of arrival order; an import can never erase a manual override. A later manual correction appends through the existing readiness-entry path and remains the selected value until the user explicitly clears/replaces it. Keep the 28-day/7-reading baselines and scoring weights unchanged. HealthKit cannot fill the five subjective 1–5 ratings; HealthKit has no generic, standard readiness score, so any source-specific score is excluded unless its scale and meaning are separately approved.
- Do not create a strength `workout_session` from an Apple `HKWorkout` alone. Apple records are workout summaries, not set-by-set app records. Keep them in a HealthKit/cardio import record until an explicit association or reviewed materialization path exists.
- A post-workout app review wraps existing human feedback and form/rubric pathways. It may store an athlete's form self-rating and rubric labels but must not ask an LLM to invent a form score from data that was not supplied or turn any review into an automatic prescription change.

### 6.2 Local outbox and status model

Persist every action locally before acknowledging it to the UI. Suggested operation record: `operation_id` (UUID), `device_id`, `workout_local_id`, monotonic per-workout `sequence`, type, canonical payload, payload digest, `captured_at_utc`, local date/timezone, state, attempts, next retry, last HTTP/code, `server_ack_id`, `created_at` and `updated_at`. Encrypt/protect the store at rest and exclude app-owned private data from iCloud/device cloud backup under the strict local-only policy.

States are explicit and user-visible:

1. `local` — transaction committed to the phone; not sent.
2. `pending` — eligible for local-server delivery.
3. `sending` — request in progress; safe to retry after interruption.
4. `acknowledged` — server returned and stored a durable receipt/record ID.
5. `rejected` — server returned a permanent validation/policy failure; local payload remains intact and editable through a new correction operation.
6. `needs_review` — conflict or ambiguous mapping requires the owner.

A local “completed” workout means the athlete finished capturing the session; it does **not** mean server sync is complete. UI must show `Saved on this iPhone · not synced`, `Synced`, or `Needs attention`, with last successful sync and error/action. Never clear a queue item simply because the request timed out.

### 6.3 Queue ordering, retries and conflicts

- Generate UUIDs on the phone for a workout, each set, cardio row, check-in operation and batch. Use per-operation idempotency keys. A duplicate response returns the same server identity; a reused key with different payload stops as a conflict.
- Order workout events by a persisted sequence: start (if server-started), sets, corrections/removals, finish. Preserve causal ordering; never send `finish` ahead of an unacknowledged set. HealthKit import batches are an independent queue so they cannot block a workout.
- Retry connect/timeouts and 5xx with bounded exponential backoff plus jitter; retry promptly when the app returns to foreground/on trusted LAN. Do not spin in background. Do not retry 400/401/403/404/409 blindly. Keep 401 data local and request re-pairing; split a 413 batch; pause 409 for review; keep 5xx retryable.
- Server responses acknowledge each operation independently. Partial batch results distinguish accepted, duplicate and quarantined rows. Batch truncation/timeout is safe because external IDs and batch IDs are idempotent.
- Store device capture time and server receive time separately. Never rewrite the original occurrence timestamp based on sync time. If the device clock is skewed or the timezone changed, preserve both offsets/timezone and show the discrepancy; never silently shift a record to a different training date.
- Readiness phone/web edits append. Preserve manual-over-import per-field semantics and show which value/source won. If two manual edits for the same field/date occur while one device is offline, append both and let the server's recorded-at merge rule determine the latest; display the merge result to the owner.
- If web and iPhone sessions conflict (for example, a workout was started/completed in both), do not merge or overwrite automatically. Return 409 with both server/local identifiers and offer explicit reconciliation (keep both fragments, discard one by explicit user action, or link only after confirmation). The existing training-day model supports multiple fragments; never collapse them.
- HealthKit duplicate samples with the same source UUID are duplicates. A changed/deleted sample becomes a superseding row/tombstone, not an in-place update. Distinct sources with overlapping steps or time ranges are not summed blindly; use a HealthKit aggregate query on phone for a daily aggregate and label it as an aggregate, or retain per-source samples and avoid a duplicate total.
- Ambiguous matching between a HealthKit workout and an app workout/cardio entry stays unmatched. Time overlap, duration and type can produce review candidates only; matching uses HealthKit UUID where available and requires user confirmation before linking. Do not auto-match by date alone.

### 6.4 Offline behavior and partial synchronization

- **Offline readiness:** the user can record a check-in with date/time provenance and see it as pending. The app cannot show a new authoritative score until the server returns one. Any previously cached score is labelled with its calculation date/source and is never recomputed locally.
- **Offline prescription:** a new plan cannot be requested. A cached plan may be shown as historical/context only. If the user trains from it while offline, the captured workout is marked `cached_plan_context` or self-directed and is not treated as a currently validated prescription until server reconciliation.
- **Offline workout:** the user can start a local capture and log sets/cardio. If a server-issued plan token and active workout were already acknowledged before disconnection, continue logging against that known snapshot. Otherwise save an offline/self-directed capture and import it through the dedicated reconciliation path. Do not invent default sets, loads, RIR or a prescription.
- **Partial sync:** server acknowledgements are per operation. If 3 of 5 sets are acknowledged, the phone retains and retries the other 2; it shows the server's acknowledged subset and pending count. Finish cannot be accepted server-side until all prior workout events are acknowledged or a specific offline-import transaction atomically accepts the entire capture.
- **App termination/reinstall:** Core Data/SQLite transaction commits before UI confirmation. On relaunch, resume pending operations from durable state. Device reinstall/revocation may strand a queue; provide a local export/backup option only if it can remain on-device/LAN, and document token revocation behavior. No silent purge or remote restore.
- **User correction:** never edit an acknowledged row in place. Generate a correction event referencing its server id. Keep permanent rejected payloads until the user explicitly resolves/exports/deletes them; an explicit delete must be documented and not delete server history.

## 7. HealthKit approach and metric plan

### 7.1 Compare integration options

| Option | Advantages | Costs/risks | Verdict |
|---|---|---|---|
| Native HealthKit in the main SwiftUI app | Direct on-device queries, narrowly requested permissions, source metadata, incremental anchored queries/deletions, and one app UX. Fits read-only health trends and optional completed-workout import. | Medium/high implementation and ongoing OS/device/authorization/testing burden. HealthKit does not supply the app's exercise-level sets/reps/load. A native workout session has additional iOS lifecycle and sensor constraints. | **Preferred later health-data path**, integrated into the main app; keep it optional. |
| Separate minimal SwiftUI Health Bridge | Could prototype HealthKit before the core app exists. | A second app, transfer format, permissions, duplicate handling and installation path; still needs secure local API/sync and does not solve core workout capture. | **Do not build separately** absent a demonstrated blocker to embedding HealthKit. |
| Health Auto Export or similar | Low initial effort to send selected HealthKit data to a configured REST endpoint. May support one-way direct-to-LAN exports. | Separate vendor app and possible paid automation; background cadence is not guaranteed, payload coverage (notably Apple effort) is not established, schema/source behavior may vary; selecting a LAN URL does not prove the app has no other outbound traffic. | **Not MVP.** Revisit only as an audited LAN-only import experiment; excluded if all exporter app traffic cannot be proven local. |
| Manual Apple Health XML | User-triggered historical export can be parsed on-device while offline; no continuous HealthKit query implementation is needed. | Full, potentially very sensitive export; manual every time; Apple's user guide documents XML export, not a stable third-party parser schema or incremental delta API. Not suitable for daily freshness or workout sync. | **Optional later backfill only**, never the core sync mechanism. |
| Hybrid: native daily capture + optional direct HealthKit + optional historical import | Best long-term fit: strong offline workout UX, Python authority and selected health context. | Must phase carefully or combines all integration/testing costs at once. | **Recommended overall, staged:** local native workflow first; direct HealthKit next; XML only if historical need is real. |

The exporter's public documentation describes REST POST to a configured endpoint and possible manual backfill, but it does not establish a total app-level egress lock or guaranteed Apple Workout Effort export. HealthKit's local-network permission is not an Internet egress firewall. Since the requirement is strict, do not rely on that tool until network behavior and every optional service are independently audited. Apple's XML export is an owner-initiated full export, not an app-facing incremental API.

### 7.2 Initial HealthKit metrics

Use least-privilege, per-type read permissions. “Available in HealthKit” means the type exists; it does not mean the owner has samples or that Apple Watch is present. HealthKit intentionally does not let an app distinguish denied read authorization from no matching data. Render `no data / permission may be unavailable / limited history / stale` as unknown rather than zero or “normal.” Ask permission only when the user turns on the corresponding feature. V1 does not write to HealthKit.

| Data | Likely HealthKit representation | Reliability and limitations | Recommendation/use |
|---|---|---|---|
| Daily steps | Quantity type `stepCount`; use a statistics aggregate per local day. | Depends on phone/watch wear and sources. Source overlap and day-boundary errors can double count; HealthKit aggregation is preferable to summing raw source samples. | Read-only descriptive trend; no readiness or cardio-dose effect. Import daily total with aggregation method, covered/partial-day state and source caveat. |
| Resting heart rate | `restingHeartRate` quantity; timestamped samples. | Only present when a source/device provides it; staleness and device/source differ. | Optional context. Keep distinct from manual readiness. Do not feed scoring until an explicit decision and tests. |
| HRV | `heartRateVariabilitySDNN` quantity, usually in ms. | Device/protocol and timing dependent; not a generic “recovery score.” | Optional context. If later connected to readiness, retain current 28-day/7-observation baseline requirements and run a shadow/data-quality review before score use. |
| Working heart rate | `heartRate` quantity; may be associated with workout. | Sampling density varies by device, workout and permissions; not necessarily available for every workout. Optical measurement can vary by condition/individual. | Cardio context. Store per-workout min/mean/max or summaries as needed; keep raw time series on phone by default. No HR zones or training impulse until method approved. |
| Sleep | `sleepAnalysis` category intervals (in-bed/asleep/stages). | Missing/incomplete; interval and stage estimates are not equivalent to clinical sleep measurement; overlaps and clock changes require care. | **Out of v1** because current methodology says sleep is outside scope. If later approved, show only observed duration/trend with provenance; do not score stage quality or prescribe sleep. |
| Apple Workouts | `HKWorkout`, `HKWorkoutActivityType`, workout-associated quantity samples/metadata. | A workout summary can include type, duration and available distance/energy/HR samples. It does not encode strength lifts, set/reps/load. Source and sensor data vary. | Cardio import and workout inventory; candidate links only. Do not automatically create a strength `workout_session`. |
| Traditional strength / functional strength | Activity types `traditionalStrengthTraining` and `functionalStrengthTraining`. | Category labels identify a workout class, not the exercises actually performed or any set details. | Display only as Apple workout categories; do not use to fabricate strength sets or compare completion to a Python prescription. |
| Workout Effort Score | `workoutEffortScore` / `estimatedWorkoutEffortScore`, with workout-effort relationship APIs on iOS 18+ (per current Apple docs). | May be absent; estimated values and user-entered ratings are distinct. Apple's 1–10 presentation does not prove equivalence to the app's manually reported session RPE (also 1–10). Third-party export support is unverified. | Store as separate Apple-origin field with estimated/manual status if present. Never populate `cardio_log.srpe` or `workout_session.session_rpe` automatically. |
| Body mass | `bodyMass` quantity. | May be manually entered, third-party, old or unit-normalized; source matters. | May map to existing `measurement` metric only through a declared metric definition and a provenance link. Never overwrite readiness/manual bodyweight. |
| VO₂max estimate / cardiorespiratory fitness | HealthKit VO₂max quantity where available. | Availability/device/activity dependent; an estimate is not a lab test. A recent living review found heterogeneous Apple Watch metric accuracy and only one small VO₂max validation study; the available study reported underestimation. | Display with “device estimate,” exact source/date and method; trend within same source cautiously. Do not diagnose, define clinical status, or use to alter training. |
| Active energy / distance | Workout summary quantities when provided; `HKWorkout` may have associated samples. | Consumer energy estimates can be imprecise; distance depends on activity/sensors. | Preserve only if useful; do not use energy expenditure for nutrition/calorie advice. Distance is a descriptive cardio metric. |

HealthKit access design: enable the HealthKit capability; supply accurate `NSHealthShareUsageDescription`; request read access for a single category/feature at a time; use a foreground snapshot/anchored query with a persisted per-type anchor; stage new samples/deletions locally before advancing the anchor; retain `HKObject.uuid`, `HKSourceRevision`, `HKDevice`, dates, units and query/aggregation provenance where available. Background observer delivery is a later optimization, not a reliability contract. Test denied/revoked/limited authorization, no samples, duplicate sources, deleted/edited samples, lock-state and device restart.

### 7.3 Workout Effort and matching rules

HealthKit exposes workout-effort relationship APIs and score identifiers starting with the iOS 18/watchOS 11 generation. Availability depends on OS, source/device, workout type and user action. Apple describes some cardio effort as estimated from heart rate, VO₂max and personal data, and lets the user adjust it. The app's existing cardio and strength end flows collect manual Borg CR10/session sRPE. Shared-looking scale range is not proof of construct equivalence.

Therefore:

- Store Apple recorded effort and estimated effort separately, including the exact identifier, source and whether estimated or user-entered.
- Keep manual cardio sRPE and strength-session RPE in their existing fields. Do not silently map, substitute, average, or compare Apple effort as though it were the same measure.
- If the owner wants to show both, label the source and allow a manually confirmed choice. Any future mapping needs a written scale/construct decision, sample review and tests; no score or prescription changes in this plan.
- Match Apple workout to an app record only with a stable HealthKit UUID link or an explicit owner confirmation after showing date/time/type/duration. Ambiguity remains unmatched. Time overlap is a candidate aid, not an automatic merge rule.

### 7.4 Longevity/Cardio page extension proposal

This plan proposes an **evidence-informed, descriptive** extension to the existing Longevity page, not a cardio prescription or a claim that consumer data predict an individual's lifespan. Reuse current cardio, measurements, readiness and source queries; show data coverage and source-quality notes beside every panel.

1. **Cardio exposure:** observed session count, total recorded minutes by ISO week and modality, source split (manual vs Apple Health), optional distance and available HR summaries. Do not treat unclassified recorded minutes as WHO moderate/vigorous minutes. Keep partial weeks and zero-coverage weeks visibly distinct from true zero activity. WHO's 150–300 minutes moderate or 75–150 minutes vigorous plus 2+ strength days remains a guideline reference, not an individual target or recommendation from this app.
2. **Cardiorespiratory fitness:** plot periodic VO₂max/test estimates as exact observed points, separate by method/device, do not connect different methods or interpolate; mark device estimates as estimates. Existing cardiorespiratory fitness/mortality evidence is largely observational, so present it as an important population-level marker, not a personal risk prediction.
3. **Steps:** show observed daily/weekly steps with days of data coverage and recent median/trend. The 2025 prospective meta-analysis found population-level nonlinear associations with inflection points around 5,000–7,000 daily steps for several outcomes; an erratum was later published. Do not repeat the original numerical risk reductions until the correction is reviewed, do not treat 7,000 or 10,000 as a universal personal prescription, and do not attribute cause to one user's trend.
4. **Readiness context:** show subjective values separately from HealthKit HRV/RHR, along with each source, selected value, freshness and the existing score status/baseline coverage. The existing HRV/RHR readiness scoring path may consume these imported fields under its current baseline/minimum rules. Manual values override imported values per field. Do not mix Apple Workout Effort with manual sRPE; no new metric or changed weight/threshold is introduced.
5. **Sleep:** omit from first release. Current [`METHODOLOGY.md`](METHODOLOGY.md) lists sleep outside app scope. If the owner later approves a descriptive duration trend, do not call it sleep coaching, infer sleep quality from stages, or use it in prescriptions by default.
6. **Presentation limits:** do not use “biological age,” “longevity score,” disease risk categories, causal “improved lifespan” copy, calorie advice or medical alerts. The dashboard is a record of observed measurements and guideline context, not diagnosis or treatment.

Evidence basis: WHO adult aerobic activity guidelines already appear in `REFERENCES.md` (#81). A 2025 systematic review of daily steps included 57 prospective studies (31 in meta-analysis), found dose-response associations, and had a September 2025 correction; this plan intentionally avoids citing uncorrected numerical risk estimates. A 2026 living systematic review of Apple Watch measurement accuracy found accuracy varies by metric/condition and the VO₂max evidence was sparse; display device estimates cautiously. Existing references #79–80 cover cardiorespiratory fitness and mortality. New citations are added to [`REFERENCES.md`](REFERENCES.md) when this proposal is staged.

## 8. Local-first privacy and security

### 8.1 Boundary and threats

Threats proportionate to one owner: another device on Wi-Fi reading/writing health data; stolen phone or exposed bearer token; wrong/public API host or redirect; a configured remote LLM being called indirectly; importing a duplicate/invalid HealthKit record; and sync interruption creating a false “saved” state. The database and iPhone are personal; there is no multi-user or public service scope.

- Bind the API to the private LAN only and enforce host/firewall rules. Do not port-forward or use a public tunnel, VPN relay, hosted proxy or cloud sync; Tailscale is not needed and is excluded by the stated local-only constraint. Apple PCC is the one permitted, feature-specific network exception if the owner enables it in the AI setting; it is never a workout/HealthKit sync destination.
- Add one-time CLI pairing. A device token is random, scoped and revocable; hash it at rest server-side; store it in Keychain; never put it in source control, URL, logs or crash reports. Use an expiry/rotation or explicit revocation flow.
- Require TLS to the paired local service. Before implementation, spike certificate trust on iPhone (owner-installed private CA or a narrowly pinned local certificate) and renewal/rotation. Do not globally disable App Transport Security or accept arbitrary self-signed certificates. If a secure LAN transport cannot be deployed reliably, stop and decide on a documented alternative before sending health data.
- Declare `NSLocalNetworkUsageDescription`; include `NSBonjourServices` only if Bonjour discovery is actually selected. Apple requires user approval for local-network access and allows it to be denied/revoked. The prompt does not restrict Internet egress; the app must enforce its own host allowlist and fail closed.
- Use only explicit local server URLs; no arbitrary base URLs from QR/link redirects. Verify scheme, host, resolved addresses, port and redirect destinations. Do not send bearer credentials to a changed host. User can manually update the endpoint through pairing.
- No analytics, telemetry, ads, external crash reporter, remote configuration, third-party model provider, link-preview fetch, push service or vendor SDK that contacts a non-local endpoint. Apple Intelligence is disabled by default and, if later enabled, uses a selectable `on_device` or `apple_pcc` mode. PCC mode makes a clearly disclosed Apple server request only for an AI task the user invokes; no automatic fallback, HealthKit values, workout history or user notes are included unless separately reviewed and confirmed for that request. Local logs redact authorization headers, HealthKit object identifiers where unnecessary, notes and exact health values.
- All core functionality must work with the Internet disconnected. Pairing, workout capture, HealthKit import, persistence and local sync must not rely on App Store, DNS outside local resolution or external authentication. On-device AI can work offline when Apple's model is available. PCC AI requires Internet and is unavailable offline; it must fail closed rather than switch modes. iOS's own Health/iCloud backup/sync behavior is outside app code; disclose it and exclude the app's own sensitive store from cloud backup.
- Minimal HealthKit scope, transparent permission copy, no write access in v1, no broad raw export retention. Process XML only on-device and exclude the source export from backups/temporary retention.

### 8.2 Optional Apple Intelligence and deterministic boundary

The initial release has no LLM feature. A later, separately approved native feature may offer a user-configurable setting with three modes: `disabled` (default), `on_device` (Apple `SystemLanguageModel`), or `apple_pcc` (Apple's server-hosted Private Cloud Compute model). PCC is the only app-initiated non-local inference endpoint permitted by this proposal. Show the selected provider before use; never silently fall back between modes. The current Python checkout can be configured with a non-local OpenAI-compatible provider even though `NullLLM` is the default. The new iOS routes must therefore:

1. omit `selection_llm` and all model settings from their input schema;
2. set the deterministic/no-LLM behavior explicitly, not merely trust the current default;
3. reject or ignore client attempts to set a remote-model flag;
4. ensure prescription generation, readiness, HealthKit import and sync never call a configured external provider; native AI requests are separate user-initiated calls from iOS to the selected Apple model;
5. add a regression test with a sentinel outbound client that fails the test if a mobile API request invokes any remote provider.

The local Python server must have no external URL fetch in the mobile workflow. No request to the local server may indirectly cause Internet traffic. PCC traffic is an explicit, separate user choice from the phone, and core app features remain usable with that choice disabled.

Use Apple Foundation Models only for bounded language tasks such as explaining a completed session or summarizing user-selected local history in plain language. Never use a model for readiness calculation, workout selection, load/sets/RIR, medical interpretation, rubric/form scores or training-policy changes. The athlete enters form ratings and review marks themselves; an optional model may draft neutral text for the athlete to accept or edit. Check model availability at runtime and provide a useful unavailable/offline state. `SystemLanguageModel` runs on-device but requires a supported Apple Intelligence device, OS and region. PCC is a separate server model with its own availability/entitlement/quota and is not offline. Version prompts and evaluate behavior across OS/model changes. For PCC, show exactly what context will be sent and obtain explicit consent before including any health/workout data; default to a minimal user-selected summary with identifiers removed. Never send raw HealthKit samples.

## 9. iOS client details

- **Minimum iOS:** recommend iOS 18 as a provisional baseline so the app can use the current workout-effort HealthKit APIs when available, while still treating that data as optional. Confirm the owner's device before locking the target. If the actual phone is older, set the minimum to its supported version and omit iOS 18-only effort features; core capture does not require them.
- **Persistence:** Core Data/SQLite-backed local store with schema migrations and transactionally committed outbox. Choose file protection based on gym/background use; exclude app-owned database from iCloud backup under the stated boundary. Avoid persisting raw HealthKit payloads/time series unless a user-visible feature requires them.
- **Navigation:** Today, Workout, History, Progress, Health & Longevity, Settings/Sync. Keep a visible “Start/Continue today's session” action. In an active workout, logger first, planned target inline, exercise/set selection preserved, one-hand targets and safe-area support. Show sync state in Today and Settings.
- **State:** observable feature view models/repositories with explicit loading/empty/partial/stale/offline/error states. The domain server response is authoritative; local state is a capture/cache, not an alternative result. Readiness shows source and sample freshness per field; manually edited fields are visibly marked as overrides.
- **Transport:** one `LocalOnlyTransport` for the paired local API, with short timeouts and explicit reachability; serialize dates/units; certificate validation/pinning decision; no redirect to non-paired host; no automatic external links. If PCC is later enabled, isolate it behind a distinct `AppleModelTransport` using Apple's Foundation Models API for PCC, only after user action/consent; it must not alter the API host allowlist, accept a model URL from the server, or be used for sync. Do not poll aggressively. Try on foreground and manual sync.
- **HealthKit:** read-only first, separate toggle/consent per data class, anchored queries, local anchors stored only after samples/deletions are durable in the local outbox. Import supported HRV/RHR observations into matching readiness fields with source, timestamp, device and aggregation shown; keep the app's existing 28-day baseline/minimum-readings score rules. Manual readiness wins per field regardless of later imports. Subjective ratings are never inferred. No server sync until user has enabled both HealthKit import and local sync. Query least data required; no automatic HealthKit writes.
- **Post-workout review:** native review sheet uses the server's review DTO and submit path. Support optional per-exercise 1–5 form self-ratings/notes, rubric scores and confidence, session RPE, duration, productivity and note. Save locally before submission, show the submitted/unsynced state, preserve blank/skipped values, and do not generate form scores or training changes with an LLM.
- **Apple Intelligence (later):** persisted user preference `disabled | on_device | apple_pcc`, default `disabled`; only AI features use this setting. `on_device` checks `SystemLanguageModel` availability. `apple_pcc` is a conspicuous online Apple endpoint selection and never a fallback; present a per-request context preview before any health/training details are sent.
- **Logging:** local rotating diagnostics with request id/status but no secrets, notes, raw values or HealthKit sample UUIDs by default. User can export logs to local file for support; no remote crash uploads.
- **Distribution:** begin with private Xcode install on the owner's iPhone. TestFlight/App Store or ad hoc distribution requires a separate Apple developer-account and signing decision; no public store listing is required for personal use. Confirm HealthKit entitlement and signing requirements for the chosen account before Phase 1.

## 10. Testing and acceptance criteria

### Backend/API

- OpenAPI validation and response-schema tests for every `/api/ios/v1/` route, status, auth scope and error code; verify existing web/API tests and route behavior remain unchanged.
- Pairing tests: one-time expiry/use, token hash-at-rest, scope checks, revocation, rotation and rate limit; no token in logs.
- Idempotency tests: duplicate same request returns same IDs; same key/different body is 409; transaction failure writes neither domain row nor receipt.
- LLM egress test: configure a stub external provider and assert iOS route requests never invoke it; try forged `selection_llm=true` and fail closed.
- Offline import, DST/timezone, clock skew, duplicate event, simultaneous web edit, already-active/completed workout, partial sync and conflict tests against a temporary SQLite database.
- HealthKit import tests use synthetic fixture records: all allowed types, missing optional fields, invalid units/ranges, duplicate UUIDs, same UUID changed payload, tombstones, duplicate sources/overlapping step samples, unknown type, unknown provenance and partial-batch response.
- Verify append-only invariants, manual-over-import precedence, cardio average <= max, and no Apple effort copied into manual sRPE.
- Run existing readiness/workout/cardio/measurement/history/manifest/consistency tests unchanged. Do not weaken old tests.

### iOS

- Unit tests for DTO coding, date/units conversion, private-host allowlist, redirect rejection, idempotency key reuse, queue ordering/backoff, partial acknowledgement, stale-plan labels, HealthKit normalization, aggregation, source display and local-date/DST behavior.
- Local-store tests for process kill/relaunch mid-write, migration, duplicate operation, queue never discarded, HealthKit-anchor commit ordering and file-protection/backup flags.
- HealthKit fixture tests for no authorization, limited history, no samples, missing HR, absent WES, several sources, workout deletion, HealthKit HRV/RHR readiness fill, later-sample/manual-override precedence, source timestamp and baseline eligibility, sleep interval overlap (if later enabled), and unavailable type/OS version. Use a physical iPhone/Watch where needed; simulator cannot prove sensor or background behavior.
- UI tests for readiness partial/missing and sourced HealthKit/manual values; stress scale labels; prescription warning acknowledgement; one-handed set entry; undo/remove; post-workout form rating, rubric/feedback review and retry; offline workout; reconnect/partial sync/rejection; stale server plan; unlinked Apple workout; data coverage; and VoiceOver/accessibility/safe areas.
- Network egress tests: run a local test server and disable public Internet; inspect app traffic with a firewall/packet capture or proxy. Core features and AI `disabled`/`on_device` modes contact only the paired LAN origin (on-device inference itself is local); test public URL, DNS-rebinding-like result, public redirect, cellular/off-LAN, local permission denied/revoked, server down and certificate mismatch. Separately verify `apple_pcc` is disabled by default, is invoked only after explicit user selection and per-request confirmation, and never becomes an implicit fallback.
- Review-flow tests: unsynced post-workout feedback survives restart/retry; duplicate review submission does not create duplicate marks or feedback; form ratings remain self-reported and server review cannot cause a prescription change.
- Release gates: all existing Python tests green; focused new tests green; Xcode build with minimum supported OS; a manual iPhone pass; HealthKit privacy copy and app-initiated network audit recorded before any private install beyond developer testing.

## 11. Phased implementation plan

Every phase is independently reviewable. The items below name likely files; confirm exact paths and repository conventions at implementation time. Each phase needs its own approval, tests, acceptance checklist and rollback point. Do not start any phase until the owner approves this plan.

### Phase 0 — Decisions and local transport spike

**Goal:** prove that the chosen iPhone and the existing LAN server can pair securely without any non-local app traffic, and settle non-reversible choices.

**Likely files:** `docs/IOS-CLIENT-PLAN.md`, new short ADR/decision in `docs/DECISIONS.md` only after owner approval; no production code in this phase unless separately approved.

**Steps:** confirm iPhone OS, Mac/Xcode availability, private installation path, server host/address, LAN firewall and the no-internet requirement; prototype local HTTPS certificate trust and one-time local pairing in a disposable test; audit App Transport Security/local-network permission behavior; test server configured with a remote LLM and prove mobile requests cannot cause egress; choose whether the native client can be built/tested in this environment.

**Tests/acceptance:** iPhone reaches the local test server with Internet disabled; public redirects/hosts are rejected; certificate mismatch fails closed; token is not logged; local permission denial produces a clear recoverable state. Document the TLS/pairing choice and explicit runtime boundary.

**Risk/dependency:** if TLS cannot be made reliable on the actual home network or no Mac/Xcode path exists, stop before adding API credentials/HealthKit. **Rollback:** discard prototype/decision branch; no existing system changes.

### Phase 1 — Versioned API facade, pairing, and idempotent writes

**Goal:** prepare an authenticated local API without changing current web routes or training rules.

**Likely files:** `strength_coach/web/server.py`, new iOS API/auth/sync modules, `strength_coach/store/migrations/0052_ios_*` (number checked against current HEAD), `docs/API.md`, `openapi/ios-v1.yaml`, synthetic API tests under `tests/`.

**Steps:** define OpenAPI DTO/error envelope; implement one-time CLI pairing and scoped device tokens; add the `/api/ios/v1/` facade; implement operation receipts and start-plan token/digest verification; implement deterministic prescription wrapper with remote LLM disabled; add private-network host/TLS enforcement/config; cap mobile payload sizes lower than the general 64 MiB route limit.

**Tests/acceptance:** OpenAPI and route contract tests pass; paired tokens authenticate and revoke; all writes are idempotent/transactional; the existing API and web UI are unchanged; with a remote LLM configured, no iOS route calls it; no route returns local paths or secrets.

**Risk/dependency:** access control and direct routing are security-sensitive; do not expose a new listener before TLS/auth tests pass. **Rollback:** leave old `/api/*` routes intact, disable the new namespace, revert only the additive migration after backup-compatible review.

### Phase 2 — Native shell, local store, and pairing

**Goal:** install a native app that securely pairs and reads current server state, with no HealthKit request yet.

**Likely files:** new `ios/StrengthCoach/` SwiftUI app, app tests, Xcode project settings; no change to Python numerical logic.

**Steps:** set supported OS and capability declarations; implement navigation and server pairing; add Keychain token storage, strict endpoint allowlist, Core Data/SQLite store, server/cache status and read-only Today/History views; implement error mapping and a manual sync action; verify the full app boots without an Internet connection.

**Tests/acceptance:** cannot contact a public host; token never appears in user defaults/logs; LAN permission denied/server unreachable has a clear state; cache labels timestamp/age; no HealthKit prompt until the user enables it; no external SDKs or outbound services.

**Risk/dependency:** depends on Phase 0/1 TLS/auth. **Rollback:** uninstall app and revoke device token; database remains untouched.

### Phase 3 — Readiness → server prescription → online workout vertical slice

**Goal:** complete the primary daily strength workflow against existing Python services.

**Likely files:** iOS `Features/Readiness`, `Features/Workout`, API repositories/DTOs; backend route/service tests and OpenAPI; possibly `workout.py` only for narrow idempotency hooks.

**Steps:** implement editable five-field subjective readiness with partial/missing semantics; display imported HRV/RHR values when present, expose source/freshness and allow per-field manual override; call readiness endpoint and render the server-computed score/source/status; request prescription from server and show warnings; require server readiness acknowledgement when needed; start with a verified plan token; log sets, form self-ratings, undo/correct, finish/abandon; provide native post-workout review for form ratings, selected rubric marks/confidence, session RPE, duration, productivity and notes; show the server critique/summary; keep all feedback optional and RPE manual.

**Tests/acceptance:** same inputs produce the same server output as web/CLI; no iOS numerical engine; missing readiness remains missing; later HealthKit refresh cannot replace a manual field; source and timestamp are shown; subjective fields remain manual; server confirms every saved set, form rating, review and completion; duplicate taps/retries do not duplicate review marks/feedback; current web workflow remains unchanged.

**Risk/dependency:** concurrency with web user edits; require explicit 409 reconciliation. **Rollback:** disable iOS routes; current Python/browser workflows remain live.

### Phase 4 — Durable offline workout capture and reconciliation

**Goal:** make workout capture reliable when the local server is unavailable, without pretending prescriptions can be generated offline.

**Likely files:** iOS local outbox, `SyncCoordinator`, offline-import API, operation-receipt migration/repository, tests.

**Steps:** persist actions before UI confirmation; order set events; add bounded retry/backoff; implement state transitions/acknowledgements and durable restart recovery; implement offline/self-directed import path and explicit stale cached-plan context; add clock-skew/timezone handling; show conflict and quarantine review.

**Tests/acceptance:** terminate app at every point in start/set/end/sync and recover; disconnect after any subset of events; partial acknowledgements remain safe; no silent deletion; manual corrections append; ambiguous cross-device workout stays separate; no new prescription when offline.

**Risk/dependency:** this is the critical data-integrity phase and depends on idempotent server contracts. **Rollback:** stop sync and retain queue; user can continue viewing/capturing locally or revoke device token without losing data.

### Phase 5 — Manual cardio capture and HealthKit cardio-workout import

**Goal:** support the user's cardio workflow and complete reviewed HealthKit ingestion, including HRV/RHR readiness fill, without changing the existing scoring policy.

**Likely files:** iOS `Features/Cardio`, `Infrastructure/HealthKit`; migration/repository for HealthKit record provenance and optional cardio source links; `features/cardio.py`/queries only for source-aware summary; `tests/test_cardio.py` plus HealthKit/API fixtures; `docs/LONGEVITY-REVIEW.md`.

**Steps:** expose manual cardio logging via existing fields; add read-only HealthKit authorization; read completed workouts and associated HR/distance/duration; import supported HRV/RHR samples to readiness with source-specific metadata and a documented per-day aggregation rule; normalize in local store; preview source/activity/time before workout import; send only explicitly allowed normalized summaries to local server; add external UUID dedup/tombstone handling; keep Apple effort separate and display-only; implement deterministic precedence `manual > HealthKit > other import` per field and source labels.

**Tests/acceptance:** import same workout twice → one record; absent HR/distance/effort remain absent; Traditional/Functional Strength types do not generate set data; manual sRPE is unchanged; unmatched workouts stay unmatched; imported HRV/RHR appears as sourced readiness input and qualifies for the existing baseline only under current minimum rules; a manual value remains selected after a newer HealthKit sample arrives; no subjective fields are inferred; import never invokes an LLM or changes scoring weights/prescription policy. Test on the actual phone and a contributing Watch/source if available.

**Risk/dependency:** HealthKit coverage depends on the owner's device/sources; cardios without a watch are still loggable manually. **Rollback:** disable HealthKit import toggle/API while leaving manual cardio and workout capture intact; do not delete accepted historical rows.

### Phase 6 — Additional HealthKit metrics and Longevity display

**Goal:** add selected read-only context after the cardio slice has reliable provenance.

**Likely files:** iOS `Features/Longevity`; HealthKit query/aggregation service; additive `healthkit_record`/measurement/readiness import migrations and tests; `docs/LONGEVITY-REVIEW.md`, `docs/REFERENCES.md`, `docs/API.md`, `docs/DATA-MODEL.md`.

**Steps:** implement steps aggregate and coverage; body mass/VO₂max and other approved observations; display source/method/device/date; add the proposed card/weekly metric panels; keep HRV/RHR connected to the Phase 5 readiness inputs under existing scoring rules; consider sleep only after an explicit scope decision. Preserve a strict no-change-to-prescription gate.

**Tests/acceptance:** all metrics missing/partial/stale/limited cases render as unknown; multi-source daily step totals are not double-counted; measurement protocols stay separate; manual readiness/measurements win; no gaps interpolated; only the currently approved HRV/RHR rules influence the server's existing readiness score; no other metric changes load or sets; evidence copy remains non-causal and non-clinical.

**Risk/dependency:** exact metric availability and meaning vary by device/source; requires Phase 5 provenance model and owner scope decision for sleep/readiness use. **Rollback:** hide cards and stop new import without mutating past observations.

### Phase 7 — Optional Apple Intelligence assistant

**Goal:** add a bounded language assistant only if useful, without weakening local-only core behavior or server-authoritative training decisions.

**Steps:** add a disabled-by-default user setting with explicit `on_device` and `apple_pcc` choices; start with on-device explanation/summarization; check framework/model availability; design PCC as a separate online request path with clear Apple disclosure and a per-request context preview/consent; never automatically switch between modes; expose only minimal user-selected context; evaluate against fixed examples and provide a deterministic no-model state.

**Tests/acceptance:** with `disabled`, no model request occurs; on-device mode contacts no network and gracefully handles unsupported device/OS/region/model-not-ready; PCC mode is called only after explicit enablement and per-task confirmation, is visibly identified, and fails when offline without fallback; no HealthKit raw data or identifiers are sent; model output cannot write readiness, prescriptions, set values, form ratings, rubric scores or settings. Test prompt/model-version changes and update evaluation fixtures.

**Risk/dependency:** Apple Foundation Models availability and quality vary with OS, device, locale and system model version; PCC requires connectivity and is explicitly outside strict local-only execution. **Rollback:** set provider to `disabled`; no training or capture path depends on a model.

### Phase 8 — Optional XML history backfill and/or background delivery

**Goal:** pursue only if a concrete historical gap or repeated manual refresh problem remains.

**Likely files:** separate iOS importer and fixture tests; temporary-file handling; no change to normal online/offline workflows.

**Steps:** for XML, prototype against a synthetic/redacted export fixture; import only selected types, show full preview/count/date/provenance, confirm before commit, and delete temporary source according to policy. For background refresh, separately assess observer delivery/lock behavior and only then add an OS background task.

**Tests/acceptance:** no XML leaves the device/cloud; repeated import idempotent; parser rejects unknown schema and reports quarantine; no unrecognized data silently dropped; background delay does not break workout sync or mark HealthKit data current.

**Risk/dependency:** XML schema is not a stable documented import contract; background scheduling is best effort. **Rollback:** leave feature disabled; core app does not depend on it.

## 12. Main risks and controls

| Risk | Severity | Control / stop condition |
|---|---|---|
| Current server is unauthenticated HTTP on the LAN | Critical | No iPhone HealthKit traffic until local TLS + scoped pairing token + revocation are tested. |
| Indirect external LLM calls from the local Python server | Critical | iOS endpoints force no-LLM; outbound sentinel test with remote config; no model field in DTOs. |
| User expects offline prescription generation | High | Explicitly deny that feature; offline capture is allowed, fresh prescription/readiness requires Python server. |
| Lost/duplicated workout events | High | Durable local DB, client UUID, server receipt, event ordering, crash/retry tests and visible acknowledgements. |
| App/web conflicting edits | High | Append-only reconciliation, HTTP 409 with explicit review; never automatic overwrite/merge. |
| HealthKit permission/data gaps mistaken as zero | High | Per-type opt-in, missingness states and permission epistemic caveat; only supported HRV/RHR enter the existing readiness path, and no subjective ratings are inferred. |
| HealthKit refresh erases or outranks a manual readiness value | High | Explicit per-field manual > HealthKit > other-import precedence independent of arrival order; test later HealthKit updates and keep both values/provenance auditable. |
| Apple strength workout mistaken for set log | High | Import only workout summary/category; no inferred exercise, load or repetitions. |
| Apple effort mistaken for manual sRPE | High | Separate columns/types and labels; no default mapping. |
| PCC treated as part of the offline/local-only core | High | Disabled-by-default explicit `apple_pcc` mode; visible provider and request preview; no silent fallback; core remains offline; no HealthKit data sent without separate consent. |
| Strict local-only promise invalidated by dependency/redirect | High | Single local transport for core features, no remote SDKs, host allowlist, ATS/TLS design, packet-capture/offline gate; isolate and audit the PCC AI exception. |
| Third-party exporter silently communicates elsewhere | High | Exclude from MVP; audit every app-initiated connection before any optional use. |
| Device OS, HealthKit, or Xcode availability unknown | Medium/high | Confirm owner's device and Mac/signing before Phase 0; do not commit to unsupported builds. |
| Longevity page overstates observational evidence | Medium | Descriptive counts/coverage only; cite WHO and updated reviews; no personal risk or causal claims. |
| Scope creep into sleep, training policy, or admin tooling | Medium | Keep exclusions explicit; separate approval for methodology/prescription-affecting changes. |

## 13. Open questions and recommended defaults

These decisions can be made at approval time; they need not block the plan itself. The first four are Phase 0 blockers.

| Decision | Recommended default | Alternatives | Consequence |
|---|---|---|---|
| Minimum iOS version | iOS 18 provisional, with core flows independent of Workout Effort API | Lower target matching phone; higher target for latest APIs | iOS 18 enables the documented effort API generation; older versions mean omitting it, not changing core requirements. Confirm device before build. |
| Swift project location | `ios/StrengthCoach/` inside this repository; `openapi/ios-v1.yaml` at root | Separate private repository | Same branch/PR keeps API/client/docs together; separate repo changes versioning and release workflow. |
| Local server host/deployment | Existing trusted home-LAN host, manually paired address/name, explicit private-network firewall | mDNS/Bonjour discovery; USB/manual export if LAN cannot be secured | Fixed address is simplest; Bonjour needs service declarations and discovery UX; no public tunnel/VPN due policy. |
| Auth and transport | One-time CLI pairing, scoped revocable token, server-stored hash, local TLS with deliberate trust/pinning | Trusted-network plain HTTP with separately approved authenticated encryption | Recommend TLS. HTTP or custom crypto can expose credentials/data and needs explicit security review; no non-loopback token use before settled. |
| Offline conflict policy | Append-only events; server ack per op; 409/manual reconciliation; offline-only workouts import as self-directed | Block capture when offline | Recommended behavior preserves gym capture without falsely claiming prescribed completion; requires offline-import service. |
| First-release HealthKit metrics | Include direct, read-only import of completed workout summaries and available cardio HR/distance; permission remains opt-in per type; steps/HRV/RHR/body mass/VO₂max can follow | Defer all HealthKit until after a manual-cardio-only release | Recommended because HealthKit cardio context is part of the stated app purpose; manual capture still works when access is declined or unavailable. |
| Readiness fields in v1 | Five subjective fields stay manual; HealthKit HRV/RHR populate existing physiological fields; manual value wins per field | Keep HRV/RHR display-only | Reuse current baseline/minimum and weights; don't infer subjective ratings or add a generic device readiness score. |
| Steps and body mass | Opt-in later read-only trends; steps descriptive, mass uses existing declared measure | Exclude until requested | Adds Longevity context but not required for workout capture. Preserve units/source and missing days. |
| Sleep | Exclude from v1; reconsider only as a descriptive duration trend after a methodology scope decision | Include sleep interval query in HealthKit phase | Current method says sleep is outside product scope; including it changes that boundary. No sleep-quality coaching. |
| Workout Effort mapping | Keep Apple estimated/manual effort as separate source; never auto-map to app sRPE | Explicit manual confirmation for a derived display/analysis | Same 1–10 display is not proof of same construct; automatic substitution can corrupt existing cardio calibration. |
| Automated vs manual HealthKit sync | Foreground/manual “Sync Health” for MVP; anchored query; background delivery later | OS observer/background refresh from first release | Foreground is easier to validate; background is best-effort and lock-state limited. |
| XML historical import | Exclude until the owner identifies a specific historical gap | Add local-only XML import later | Avoid a large sensitive-file parser without recurring value. |
| Apple Intelligence mode | `disabled` by default; later allow explicit `on_device` or `apple_pcc` selection | Keep feature disabled permanently | `SystemLanguageModel` is an on-device option (iOS 26+ in current Apple docs); PCC is a separate Apple server option (iOS 27+ in current Apple docs) and requires connectivity. PCC is the only permitted app-network exception; no silent fallback and user confirms context per request. |
| Distribution | Private Xcode install first; TestFlight only if the owner wants it and accepts its account workflow | Ad hoc/App Store distribution | Distribution/signing and HealthKit entitlement eligibility depend on Apple account; verify before implementation. |
| Admin functionality | Web/CLI only | Move selected settings to native app later | Avoid duplicating unstable configuration and safety-control surfaces. |
| HealthKit-to-server data set | Only selected normalized summaries, not raw time-series by default | Keep all HealthKit data only on phone | The local server remains local, but minimizing transferred sensitive data reduces exposure and schema burden. |
| Longevity page scope | Add sourced cardio/steps/fitness trends descriptively; sleep gated; no new score | Keep current UI and add only source labels | New panel should not appear until it has coverage and method labels. |

## 14. First task after approval

Start with **Phase 0 only**: confirm the target iPhone/iOS and available Mac/Xcode setup; identify the local server host; and build a disposable local pairing/TLS spike with Internet disabled. At the same time, write the exact no-egress acceptance test for an iOS request when the Python server has a remote LLM configured. Do not begin the HealthKit import or production iOS UI until that gate passes and the user approves Phase 1.

## 15. Evidence and technical references

### Apple platform/security documentation

- [HealthKit data types](https://developer.apple.com/documentation/healthkit/data-types) — quantity/category/workout type catalog.
- [Authorizing access to health data](https://developer.apple.com/documentation/healthkit/authorizing-access-to-health-data) — per-type permissions, limited history and the fact that an app cannot determine whether read permission was denied.
- [Reading data from HealthKit](https://developer.apple.com/documentation/healthkit/reading-data-from-healthkit) and [HealthKit queries](https://developer.apple.com/documentation/healthkit/queries) — sample, statistics and anchored-query patterns.
- [HKWorkout](https://developer.apple.com/documentation/healthkit/hkworkout) and [HKWorkoutActivityType](https://developer.apple.com/documentation/healthkit/hkworkoutactivitytype) — workout summary/container and traditional/functional strength categories.
- [HKWorkoutEffortRelationship](https://developer.apple.com/documentation/healthkit/hkworkouteffortrelationship), [HKWorkoutEffortRelationshipQuery](https://developer.apple.com/documentation/healthkit/hkworkouteffortrelationshipquery) and [workoutEffortScore identifier](https://developer.apple.com/documentation/healthkit/hkquantitytypeidentifier/workouteffortscore) — current HealthKit effort relationship/type; not evidence of equivalence to this app's manual sRPE.
- [Protecting user privacy](https://developer.apple.com/documentation/healthkit/protecting-user-privacy) — HealthKit privacy/storage obligations.
- [Foundation Models framework](https://developer.apple.com/documentation/foundationmodels) and [SystemLanguageModel](https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel) — Apple-supported on-device model interface and runtime availability requirements.
- [Detecting available Apple Foundation Models](https://developer.apple.com/documentation/foundationmodels/detecting-available-apple-foundation-models) and [Adding server-side intelligence with Private Cloud Compute](https://developer.apple.com/documentation/foundationmodels/adding-server-side-intelligence-with-private-cloud-compute) — distinguishes the on-device model from PCC, which uses network access and has separate availability/entitlement requirements.
- [TN3179: Understanding local network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy) and [`NSLocalNetworkUsageDescription`](https://developer.apple.com/documentation/bundleresources/information-property-list/nslocalnetworkusagedescription) — local-network permission. It is not an Internet egress firewall.
- [App Transport Security](https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity) — HTTPS defaults and security implications of exceptions.
- [Apple Support: Share your data in Health on iPhone](https://support.apple.com/guide/iphone/share-your-health-data-iph5ede58c3d/ios) — user-initiated full XML export; does not promise an app-facing stable incremental format.
- [Apple Watch User Guide: Start a workout](https://support.apple.com/guide/watch/start-a-workout-apdd16e8761a/watchos) and [watchOS 11 effort feature announcement](https://www.apple.com/newsroom/2024/06/watchos-11-brings-powerful-health-and-fitness-insights/) — effort rating context and estimated cardio effort; keep distinct from app manual sRPE.

### Longevity evidence

- WHO 2020 adult activity recommendations and existing cardiorespiratory fitness references remain in [`REFERENCES.md`](REFERENCES.md) (#79–81).
- Ding D, et al. [Daily steps and health outcomes in adults](https://doi.org/10.1016/S2468-2667(25)00164-1), *Lancet Public Health*, 2025;10:e668–681, with [published correction](https://doi.org/10.1016/S2468-2667(25)00199-9). The public-facing plan does not repeat point estimates until the correction is reviewed.
- Lambe R, et al. [The accuracy of Apple Watch measurements: a living systematic review and meta-analysis](https://doi.org/10.1038/s41746-025-02238-1), *npj Digital Medicine*, 2026;9:63. Accuracy varied by metric and measurement conditions; VO₂max evidence was sparse.
- Lambe R, et al. [Investigating the accuracy of Apple Watch VO₂max measurements](https://doi.org/10.1371/journal.pone.0323741), *PLOS ONE*, 2025;20:e0323741. Small validation study; treat the estimate as a within-source trend, not a clinical fitness test.
- Third-party option evaluation: [Health Auto Export REST API](https://help.healthyapps.dev/en/health-auto-export/automations/rest-api), [supported data](https://help.healthyapps.dev/en/health-auto-export/getting-started/supported-data), [workout JSON](https://help.healthyapps.dev/en/health-auto-export/export-format/workouts), [automation limitations](https://help.healthyapps.dev/en/health-auto-export/automations), and [privacy policy](https://healthyapps.dev/health-auto-export/privacy-policy). These describe export capability but do not prove a strict whole-app egress allowlist.

## Related repository documents

- [`ROADMAP.md`](../ROADMAP.md) §4.29 — proposal status and implementation phase tracking.
- [`API.md`](API.md) — current unversioned API; remains authoritative for existing routes.
- [`DATA-MODEL.md`](DATA-MODEL.md) — current schemas and append-only rules.
- [`READINESS.md`](READINESS.md) and [`METHODOLOGY.md`](METHODOLOGY.md) — canonical readiness and decision boundaries.
- [`LONGEVITY-REVIEW.md`](LONGEVITY-REVIEW.md) — current cardio and longevity evidence. (There is no standalone `docs/CARDIO.md` tracked on this branch.)
- [`WEB-UI.md`](WEB-UI.md) and archived [`UI-MOBILE-AUDIT.md`](archive/UI-MOBILE-AUDIT.md) — current responsive UI and prior phone audit.
- [`PRIVACY.md`](PRIVACY.md), [`OPEN-QUESTIONS.md`](OPEN-QUESTIONS.md), [`REFERENCES.md`](REFERENCES.md), and [`manifest.yaml`](manifest.yaml).

## Completion state

This is a proposal and documentation-only change. It does not alter the Python backend, current web UI, CLI, rules, migrations, training data or prescription logic. Implementation remains gated on owner approval.
