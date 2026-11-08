# HTTP API

The local server exposes the same core functions as the CLI. This is the API reference;
page behaviour and UI surfaces are in [WEB-UI.md](WEB-UI.md).

---

## Routes

| route | purpose |
|---|---|
| `GET /api/overview` | dashboard data |
| `GET /api/progress?date=&weeks=` | descriptive attendance aggregate, weekly average volume, sRPE coverage, recent performance-ratio observations and observed weekly RIR/tonnage/residual series (`weekly`, `missing_weeks`) |
| `GET /api/outcomes?weeks=&date=` | read-only strength, volume, attendance, readiness, cardio, measurement and symptom summaries |
| `GET /api/performance/e1rm?exercise_id=&from=&to=` | raw e1RM observations, rolling median, breaks and descriptive summary |
| `GET /api/performance/dose?from=&to=&group_by=session` | descriptive session dose |
| `GET /api/performance/ratios?relationship_id=&from=&to=` | configured ratio current value and paired history |
| `GET /api/performance/relationships` | merged relationship configuration, source provenance and revision |
| `POST /api/performance/relationships` | add a validated local relationship; requires the current revision |
| `POST /api/performance/relationships/{id}/update\|delete\|reset` | edit, hide or reset a local relationship override; requires the current revision; stale revisions return 409 |
| `GET /api/monitoring-analysis?as_of=` | read-only dose, lagged associations, coverage and calibration transparency; no path disclosure |
| `GET /api/settings/monitoring` | read-only monitoring/config inventory, canonical/local/default/code provenance, Phase 5A period and lock, complete effective-inventory revision; no paths or athlete data |
| `POST /api/import` | `{training: {name, text}, readiness: {name, text}}` -> import report |
| `POST /api/prescribe` | `{date, session_type?, apply_selection?, selection_confirmed?, selection_llm?, minimum_session?, target_minutes?, minimum_include_main?, allow_unknown_readiness?}` -> prescription; `session_type=auto` uses the rolling rule; unknown readiness requires the explicit flag |
| `POST /api/workout/start` | `{date, plan, readiness, readiness_ack?, note?}` -> live workout; a score-ready assessment or explicit acknowledgement is required; partial readiness stays partial |
| `GET /api/workout/active` | active workout, or `{workout: null}` |
| `GET /api/workout/<id>` | workout detail |
| `GET /api/workout/<id>/summary` | completed-workout descriptive summary; 404 unknown, 409 in progress |
| `GET /api/form-trend?weeks=N&date=N` | descriptive current/baseline form trend |
| `POST /api/workout/<id>/form` | `{exercise_id, rating 1-5}` -> optional post-lift form rating |
| `POST /api/workout/<id>/sets` | `{exercise_id, load_kg, reps, rir, velocity?, plan_item_index?}` -> add manual set; explicit plan-item identity is validated against the frozen exercise; omitted identity resolves only a unique item |
| `POST /api/workout/<id>/remove-set` | `{set_id}` -> append a removal event |
| `POST /api/workout/<id>/end` | `{session_rpe?, not_recorded?, duration_min?, productivity?, notes?}` -> completed |
| `POST /api/workout/<id>/update-set` | `{set_id, load_kg, reps, rir, velocity}` -> append correction event |
| `POST /api/workout/<id>/import` | `{text, rep_text?, apply}` -> parse/preview/apply workout CSV; optional per-rep table; no date column |
| `POST /api/workout/<id>/import/undo` | undo the latest import batch, including rep detail |
| `GET /api/history?limit=&offset=&start=&end=` | paginated session-fragment history |
| `GET /api/history/days?limit=&offset=&start=&end=` | paginated training days with their fragments |
| `GET /api/exercise-history?exercise_id=&limit=&offset=&on_or_before=` | read-only completed-session history for one exercise, grouped by session; limit counts sessions and defaults to 5 |
| `GET /api/history/<id>` | current session sets and feedback |
| `POST /api/history/<id>/edit` | append-only correction of sets and session metadata |
| `POST /api/history/<id>/vbt` | set/rep VBT overrides (also accepted inside `/edit`) |
| `POST /api/history/<id>/void` | void or unvoid a whole session |
| `GET /api/rep-velocity?session=<id>` | descriptive per-rep report after completion |
| `GET /api/rep-velocity/analysis?weeks=&date=` | stratified cross-session descriptive report |
| `POST /api/workout/<id>/abandon` | abandon the active workout |
| `GET /api/review/<session>` | session sheet |
| `POST /api/review/<session>` | `{scores, confidence, note, session_rpe, session_minutes, productivity}` -> marks + optional session detail |
| `GET /api/readiness/<date>` | merged readiness |
| `GET /api/readiness/history?from=&to=&fields=` | inclusive observed readiness/bodyweight series with per-field sources; requires date bounds, merges manual-over-import per field, no fill |
| `POST /api/readiness` | `{date, values, note}` -> merged readiness + score |
| `POST /api/readiness/override` | `{date, scope, value, reason}` -> merged readiness + score |
| `GET /api/readiness/calibrate` | calibration report text (no auto-apply) |
| `GET /api/logs?limit=N` | recent in-memory application/HTTP log records (max 500; cleared on restart) |
| `GET /api/state` | profile, constraints, suitability, e1RM, symptoms, attributed symptoms, injury signal |
| `GET /api/symptoms/attribution-options?onset=&timing=` | completed sessions and performed lifts available for an attributed symptom |
| `GET /api/exercises` | canonical exercise catalogue for the pickers |
| `POST /api/programme/key` | request body -> `{cache_key}` covering version, request, resolved profile, database revision and relevant config hashes |
| `POST /api/programme/jobs` | starts a background build; returns `202` with `job_id` and status |
| `GET /api/programme/jobs/<id>` | `running` / `done` with entries / `error`; has a one-hour in-memory TTL and is capped at 20 jobs |
| `POST /api/programme` | synchronous compatibility endpoint -> date entries; Apply selection mirrors `/api/prescribe`, and `selection_llm` lets the model choose only among filtered variants |
| `GET /api/cardio?weeks=N` | cardio summary for the window |
| `POST /api/cardio` | `{date, modality, minutes, avg_hr, max_hr, distance_km, srpe, note}` -> summary |
| `GET /api/fatigue?date=N` | strength fitness-fatigue diagnostic (per-lift state and status; not a predictor) |
| `GET /api/validation?max_dates=N` | retrospective walk-forward report (not prospective) |
| `GET /api/continuity?date=N` | return-to-training calibration: per-band n/median/CI/fixed/applied and `allow_relax_fixed` |
| `GET /api/volume?date=N&weeks=4&accounting=hard\|effective` | weekly pattern-group ledger with `patterns` and direct/indirect/effective `groups`; optional accounting override defaults to the profile setting |
| `GET /api/shadow?date=N&window_days=84` | shadow review: rows by component/action, applied/applied-nothing counts, high-signal days, abstention reasons and the four gate checks; `activation_allowed` is always false |
| `GET /api/residual?date=N&window_days=84` | VBT execution residual grouped by lift/reps/load basis, lift-scoped only, with the signal/evaluation gates and abstention reasons (shadow) |
| `GET /api/exposure?date=N` | rolling hard-set exposure ratio with windows, coverage, abstention reasons, per-group ratios and Part D advisories (read-only; `DEC-EXPOSURE-02`) |
| `GET /api/volume/budget?date=N` | read-only weekly volume budget: target, exemptions, completed, projection, session cap, feasibility and per-group status/persistent/top-up capacity |
| `GET /api/outcomes?weeks=N&date=N` | read-only 4/8/12-week strength, longevity and coverage review |
| `GET /api/prospective?weeks=N&date=N` | W5 read-only prospective summary: statuses, attendance, work, RIR, duration, flags |
| `GET /api/regime?weeks=N&date=N` | read-only main-lift/substitute regime check |
| `GET /api/settings` | masked LLM settings, drop settings, config/database paths and app version |
| `GET /api/settings/volume?date=N` | consolidated volume panel: effective budget, volume policy, landmarks, athlete-level values, profile source and local-overlay warning |
| `POST /api/settings/volume` | validate and append a settings-profile version for volume budget/policy; requires reason and typed VOLUME for target/cap/MRV/landmark changes |
| `GET /api/settings/drop/window?date=N` | whether per-session drop confirmation applies on that date; the Prescribe checkbox is hidden when false |
| `POST /api/settings/llm` | save local LLM settings; blank key keeps the stored key |
| `POST /api/settings/drop` | legacy drop-only save path; the consolidated volume panel uses `/api/settings/volume` |
| `GET/POST /api/settings/profile` | read or append a settings-profile version; POST takes set/unset/reset, effective_from, guard_confirmed, reason and resolver_enable_confirmed (required for a false->true resolver.enabled transition) |
| `GET /api/resolver/policy` | raw resolver policy YAML, path, digest, schema and newest backup metadata |
| `POST /api/resolver/policy` | validate the complete YAML, back up the current file, atomically replace it and prune to the newest 20 backups |
| `POST /api/resolver/policy/restore` | restore the newest normal validated policy backup; the current policy is snapshotted as `template-resolver-prerestore-*` and reported, and pre-restore snapshots are not later restore candidates |
| `POST /api/resolver/preview` | read-only candidate/beam/evaluator preview; returns the prescription directly (not nested), plus choices, alternatives, suggestions, top set, projected week and structured failure stages; the UI compares the full displayed prescription |
| `GET /api/modalities` | module list with class, enabled source, dependencies, citations and factors |
| `GET/POST /api/modalities/<id>` | module state or enabled/factor update; guarded modules need guard_confirmed and reason |
| `POST /api/settings/llm/test` | call the configured model with a tiny connectivity prompt |
| `GET /api/exposures?date=N` | recent high-intensity exposures and recovery guard |
| `POST /api/exposures` | log a manual max/competition/unplanned exposure; tests use the test endpoint |
| `POST /api/continuity/settings` | `{allow_relax_fixed}` -> update the calibration policy |
| `POST /api/readiness/volume` | update the readiness volume valve (enabled, score below, sets, include essentials — main lifts opt-in) |
| `GET /api/readiness/presets` | raw `config/readiness-presets.v1.yaml`, its path and the parsed presets |
| `POST /api/readiness/presets` | `{yaml}` -> validate and atomically replace the preset YAML; no schema change |
| `POST /api/readiness/preset` | write a quick-readiness preset as ordinary entries with `source=preset` |
| `POST /api/readiness/context` | append display-only context flags |
| `GET /api/readiness/feedback?weeks=N&date=N` | descriptive follow-up of MOD-FAT-001 reductions, including completed workout snapshots and set adherence |
| `GET /api/selection?date=N&session_type=X&llm=0\|1&include_different=0\|1` | exercise-selection rankings with A/B/C comparability classes |
| `GET /api/substitution?date=N&session_type=X` | Part C fatigue-informed suggestion (at most one, suggest-only) plus abstention reasons |
| `POST /api/exercises/demands` | `{exercise_id, dimension, level, confidence?, reason?, evidence?, clear?}` -> writes the git-ignored demand overlay and returns the merged profile; `supported` needs an existing evidence id |
| `GET /api/options` | canonical goal, constraint, severity, region, pattern, VBT-family, muscle and exercise choices |
| `GET /api/exercises/catalog` | full exercise catalogue with source/properties, patterns, VBT families and muscles |
| `POST /api/exercises` | create/update an entity in `config/exercises/overrides.v1.yaml`; unknown new patterns/muscles are rejected, legacy values are preserved |
| `GET /api/measurements?metric_key=&from=&to=&limit=&offset=` | metric catalogue, summary and newest-first exact-record pages; offset walks older, entries stay date-ascending, date bounds are inclusive |
| `POST /api/measurements` | `{metric, value, date, method, note}` -> summary |
| `POST /api/state/profile` / `constraint` / `suitability` / `e1rm` / `test` / `symptom` / `block` | append-only state writes; profile includes `volume_budget_enabled` and `main_lift_policy`; goals, constraint kinds/regions, forbidden patterns/exercises and exercise ids are validated against the canonical vocabulary; `symptom` accepts optional `timing`, `attributed_session_id`, `attributed_exercise_id`, `onset_on` and `attribution_confidence`, plus the short aliases the UI uses |
| `GET /api/calibrate` | calibration report |
| `GET /api/docs` / `GET /api/docs/<name>` | doc list and rendered doc from `docs/manifest.yaml`; public entries only, grouped by category; `private/` and maintainer-only design docs are never served |

### iOS facade — Phase 1 reads and Phase 2 workflow

/api/ios/v1/ is the authenticated boundary used by the native iPhone client. It is
additive: every unversioned route above keeps its current behaviour and stays unauthenticated.
The authoritative interfaces are [IOS-PHASE-1-CONTRACT.md](design/IOS-PHASE-1-CONTRACT.md),
[IOS-PHASE-2-CONTRACT.md](design/IOS-PHASE-2-CONTRACT.md) and
[IOS-PHASE-3A-CONTRACT.md](design/IOS-PHASE-3A-CONTRACT.md); the phase rules are in
[IOS-CLIENT-PLAN.md](IOS-CLIENT-PLAN.md).

| route | auth | payload |
|---|---|---|
| `POST /api/ios/v1/pair` | none | `{code, label?}` -> `{api_version, device, token, server_date, server_time, utc_offset_minutes, server_timezone}`; the token is shown once |
| `GET /api/ios/v1/bootstrap` | bearer | `{api_version, server_date, server_time, utc_offset_minutes, server_timezone, capabilities}`; Phase 2 adds `readiness_write`, `prescription` and `workout_write`; Phase 3A adds `healthkit_readiness` (false when mutations are disabled) |
| `GET /api/ios/v1/today` | bearer | `{date, readiness, readiness_score, active_workout}`; `readiness` is the existing `/api/readiness/<date>` payload and `active_workout` is null or the live workout detail |
| `GET /api/ios/v1/history?limit=&offset=&start=&end=` | bearer | exactly `history.list_sessions`; limit 1-100, default 50; offset >= 0, default 0 |
| `GET /api/ios/v1/history/<id>` | bearer | exactly `history.detail`; session outline, measured/manual duration, sets and feedback; unknown id 404 |
| `GET /api/ios/v1/progress?weeks=&date=` | bearer | exactly `progress_feature.dashboard`; weeks 1-52, default 8 |
| `POST /api/ios/v1/readiness` | bearer + Idempotency-Key | `{values, note?}` -> the existing readiness payload; values use the accepted manual field set; unknown/empty/zero-placeholder fields are rejected |
| `POST /api/ios/v1/healthkit/readiness` | bearer + Idempotency-Key | `{date, samples:[{field, value, sample_id, sample_at, source_name, source_bundle_id?, source_class, source_model?, source_manufacturer?}]}` -> the canonical readiness payload plus `healthkit` provenance; one to three samples (HRV, RHR, bodyweight), server-local today for the import, sample identity deduplicated; see Phase 3A contract |
| `POST /api/ios/v1/prescriptions` | bearer + Idempotency-Key | `{readiness_ack?, confirmations?: {deload?, drop?}, settings?: {session_type?, minimum_session?, minimum_target_minutes?}}` -> `202 {issued_plan_id, status, for_date, request_expires_at, plan_expires_at, retry_after_ms, settings}`; the request is built in the background (R7) |
| `GET /api/ios/v1/plans/current` | bearer | the authoritative plan-request state: `{status: queued|building|ready|error|none, issued_plan_id, elapsed_seconds, settings, plan?, readiness?, warnings?, error?}`; `none` is a normal answer, not a 404 |
| `POST /api/ios/v1/workouts` | bearer + Idempotency-Key | `{issued_plan_id}` -> the existing workout detail; starts by id only; expired/superseded/consumed plans are 410, another active workout is 409 |
| `POST /api/ios/v1/workouts/<id>/sets` | bearer + Idempotency-Key | `{exercise_id, load_kg?, reps, rir?, velocity_mps?, set_index?, plan_item_index?, rep_velocities?}` -> workout detail; `plan_item_index` is the stable plan-item identity (not the display position); `velocity_mps` is optional manual mean and `rep_velocities` is optional `[{rep_index, velocity_mps}]`; values must be positive and reps are required |
| `POST /api/ios/v1/workouts/<id>/form` | bearer + Idempotency-Key | `{exercise_id, rating 1-5, note?}` -> workout detail |
| `GET /api/ios/v1/exercises` | bearer | `{exercises:[{id, display, pattern}]}`; canonical catalogue for the R8 picker |
| `POST /api/ios/v1/workouts/<id>/plan/items/<index>/swap` | bearer + Idempotency-Key | `{exercise_id, expected_exercise_id}` -> workout detail; `409 sets_already_logged` after a set, `409 exercise_already_present`, `409 plan_changed` |
| `POST /api/ios/v1/workouts/<id>/plan/items/<index>/remove` | bearer + Idempotency-Key | `{expected_exercise_id}` -> workout detail; logged sets are kept; `409 last_plan_item`, `409 plan_changed` |
| `POST /api/ios/v1/workouts/<id>/plan/items/<index>/sets` | bearer + Idempotency-Key | `{delta, expected_exercise_id}` -> workout detail; `409 sets_below_logged`, `409 plan_changed` |
| `POST /api/ios/v1/workouts/<id>/plan/exercises` | bearer + Idempotency-Key | `{exercise_id}` -> workout detail; server defaults 3 sets, 8–12 reps, RIR 2, no load; duplicate is `409 exercise_already_present` |
| `POST /api/ios/v1/workouts/<id>/complete` | bearer + Idempotency-Key | `{session_rpe? or not_recorded: true, duration_min?, notes?}` -> completed workout detail; RPE and not-recorded are mutually exclusive |
| `POST /api/ios/v1/workouts/<id>/abandon` | bearer + Idempotency-Key | `{}` -> abandoned workout detail |

- **Pairing is CLI-only.** `strength-coach ios pair [--label LABEL] [--ttl 300]` prints a
  one-use 8-digit code (spaces/hyphens are ignored by the exchange); the default TTL is 300
  seconds and the accepted range is 60-3600. `ios devices` lists devices and `ios revoke`
  sets `revoked_at` (idempotent; an unknown id exits 2). No HTTP route issues a code.
- **Credential model.** A successful exchange creates one device and returns a 32-byte
  URL-safe bearer token. Only SHA-256 hex digests of the code and token are stored. A missing
  or unknown token returns `401`; a revoked device returns `403`. Authentication runs before
  route dispatch, so an unknown path under the namespace is `401` unauthenticated and `404`
  authenticated.
- **Pairing errors.** `400` malformed body/code/label, `401` wrong code, `410` expired or
  already used, `429` attempts exhausted. Five failed attempts exhaust one code.
- **Phase 2/3A writes.** Every mutation requires a UUID Idempotency-Key. A successful response is
  stored for 30 days and replayed with Idempotent-Replay: true; the same key with a different body
  or route is 409 idempotency_conflict. The receipt check and mutation run in one BEGIN IMMEDIATE
  transaction, so concurrent duplicates replay the committed response rather than executing twice;
  a receipt uniqueness race is rolled back and re-read instead of returning 500. Mutations are
  authenticated before dispatch and run through the existing readiness, prescription and workout
  services. Phase 3A adds the read-only HealthKit readiness import route; it stores observations,
  never writes HealthKit itself, and does not request sleep or workouts.
- **HealthKit readiness.** Phase 3A is read-only and opt-in. The client sends only HRV and
  resting heart rate; manual/preset readiness wins over HealthKit, which wins over imported
  readiness. HealthKit observations live in `healthkit_readiness`, never in `readiness_day` or
  `readiness_entry`. Sample identity is device + field + HealthKit sample UUID; identical
  observations are no-ops and changed immutable attributes are 409 healthkit_sample_conflict.
  The route accepts only the server-local today, HRV within 48 hours and RHR on that date; the
  canonical readiness payload exposes `sources` and `healthkit` provenance. No raw time series is
  retained and no score is computed in Swift.
- **Per-rep velocity.** The iOS set route accepts optional `rep_velocities` on a manual set. The
  server validates indexes/values, derives `velocity_mps` from the reps when the mean is omitted,
  and returns `reps_detail`/`rep_summary`. This is descriptive detail; it does not change load,
  RIR, prescriptions or scoring. The existing web import/API contract remains authoritative.
- **Issued plans.** POST /api/ios/v1/prescriptions persists the normal prescription and returns a
  single-use issued plan with a 60-minute TTL. The phone starts it by id only; plan content never
  comes from the phone. One live plan is allowed per device; a newer issue supersedes the older one.
  Device-scoped plans and receipts keep one device from reading another device's plan.
- **Asynchronous issue (R7).** The resolver build outlives the client's 10-second timeout, so the
  request is queued and built by one bounded dispatcher: `202` plus a database-backed request row,
  and `GET /api/ios/v1/plans/current` as the authoritative read for launch, foreground and polling.
  Two deadlines are separate: `request_expires_at` (`plan_request_ttl_seconds`, default 900)
  bounds the build, and `plan_expires_at` (`issued_plan_ttl_seconds`, default 3600) bounds starting
  a ready plan. Prescription rows are written in the start transaction, so an unstarted ready plan
  is a preview and not a prescription. Starting a `queued`/`building` plan is `409 plan_not_ready`;
  a failed build is `410 plan_failed`. Legacy Phase 2 rows are preserved by migration `0056` and
  keep their original prescription id.
- **Mutation switch.** Set mutations_enabled: false in config/ios.v1.yaml to return every Phase 2
  mutation as 503 ios_mutations_disabled while bootstrap/today/history/progress remain available.
  The bootstrap capabilities report the writes as disabled.
- **Errors.** Phase 2 conflicts use {"error", "code", "fields", "details"} with codes such as readiness_required,
  confirmation_required, workout_active, plan_expired, plan_superseded, plan_consumed,
  workout_not_active, session_rpe_required and idempotency_conflict. Validation failures remain 400.
- **Plan-item attribution.** A set's `plan_item_index` is the stable plan-item identity
  (`order_index`), not its current display position. It is optional. The client auto-attributes a
  unique exercise. When an exercise appears multiple times, the app lists the occurrences and
  defaults to Not attributed; selecting one sends that stable identity, while leaving it unselected
  sends nil. For backward compatibility an old display position is accepted only when it names the
  same exercise. The comparison response exposes `plan_item_index` (stable) and `display_index`
  (current order). An omitted index resolves only for a unique exercise; otherwise the set keeps no
  plan-item attribution.
- **Progress is available to the client in Phase 2.** GET /api/ios/v1/progress is the same
  progress_feature.dashboard payload used by the web UI; the native client has a Progress tab.
- **Retry boundary.** The client records each attempted mutation in a durable, capped journal
  before sending it. After relaunch it replays only those attempted operations with the original
  UUID and exact body, within a 28-day client window inside the server's 30-day receipt retention.
  Definitive 4xx responses remove the entry; idempotency conflicts and stale entries stop
  automatic replay and require review/discard. This is not an offline queue, and the server API is
  unchanged.
- **last_seen_at** is updated at most once per 60 seconds.
- **Dates.** `server_date`/`server_time` come from the server's local clock; the phone must
  not derive the training date from a UTC slice. `bootstrap` sends the numeric UTC offset and
  the platform timezone abbreviation, not an IANA name.

## Request security

**Temporary home-network mode (2026-10-28, `DEC-WEB-03`):** the loopback Host, Origin and
`Sec-Fetch-Site` guards were removed by owner decision; the UI binds `0.0.0.0` and has **no
authentication**. The accepted risk is `LIM-57`. Never expose it to the public internet.

What remains:

- `Content-Type: application/json` is required for mutation bodies, so a `text/plain` simple
  request cannot be used as a JSON body;
- request bodies are capped at 64 MiB;
- `/api/ios/v1/` is the only authenticated surface (per-device bearer token); every
  unversioned route remains unauthenticated as described above;
- logs do not record passwords or session tokens;
- authentication, per-user data, password reset, birth date/gender/timezone, CSRF and TLS are
  the `ROADMAP.md` §4.19 backlog. They must land before any exposure beyond the home LAN.

## Request limits

- A request body is capped at **64 MiB** (`MAX_BODY_BYTES`) before it is read. This covers two
  20 MiB decoded CSVs plus JSON escaping and keys. The per-file limit remains **20 MiB** on the
  decoded UTF-8 text (`MAX_IMPORT_FILE_BYTES`).
- Oversized bodies return **413** before `rfile.read`; a missing length returns **411**;
  invalid, negative or duplicate lengths and chunked transfer return **400**. The connection is
  closed on every framing rejection. The browser maps 411/413 to plain next-action copy:
  “reload and try again” and “split or compress the file and try again.”
- The handler is HTTP/1.0 today. If it ever becomes HTTP/1.1, a rejected body must still be
  closed or drained.
- The import is JSON text, not multipart; the per-file check stays in the import handler.

## Dates

- The **local calendar date in YYYY-MM-DD** is authoritative for UI defaults and daily records.
  The server's local timezone is authoritative today; a profile timezone (default
  Europe/London) is part of the auth/per-user backlog. Do not assume a remote browser shares it.
- Use `formatLocalDate`/`today`; never `toLocaleDateString` or a UTC
  `toISOString().slice(0, 10)` for a date default.

## Error responses

- Expected validation failures keep their useful 400/404/409 JSON messages.
- Form-validation 400s may add a `fields` map, for example
  `{"error": "...", "fields": {"main_lift_policy": "..."}}`. This is additive; clients that only
  read `error` keep working. Forms mark the named input `aria-invalid` and focus it.
- An unexpected server exception returns a stable `{"error": "internal server error"}` 500 and
  is logged with method, path and traceback. Exception classes, filesystem paths and database
  details are not returned to the client.

## Client modules

No build step and no bundler. The scripts load in this order:

1. `core.js` — API requests, HTML escaping, formatting, notices and local dates.
2. `settings.js` — Settings panels: LLM, profile, volume, modalities and monitoring.
3. `app.js` — navigation, routing, boot and the shared views.
4. `exercises.js` — exercise catalogue, editor and e1RM override.
5. `history.js` — history list, session details, corrections and VBT backfill.
6. `workout.js` — live workout start, sets, end and post-workout screens.
7. `summary.js` — descriptive workout summary.
8. `performance.js` — performance and relationship panels.

Feature modules use the core helpers. `app.js` dispatches view loaders through `VIEW_LOADERS`
rather than an if-chain. Boot is deferred to `DOMContentLoaded` so every module is loaded
before a deep link can call its loader.


## Related

- **UI surface:** [WEB-UI.md](WEB-UI.md)
- **Architecture:** [ARCHITECTURE.md](ARCHITECTURE.md)
- **UI map:** [UI-MAP.md](UI-MAP.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
