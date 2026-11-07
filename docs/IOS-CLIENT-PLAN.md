# Native iPhone Client — Local-First Implementation Plan

**Status:** proposal only; not approved for implementation. Documentation and planning only: this plan does not create an iOS project, API route, migration, or production code.

**Purpose:** deliver a practical iPhone interface for one person's existing strength-training workflow, without porting the training method or making a public cloud service a prerequisite. Start with an ordinary, connected strength session. Add offline capture, HealthKit, and Apple Intelligence only after the smaller client proves useful and reliable.

## 1. Recommendation and first-release acceptance

Build a modest SwiftUI client that calls the existing Python application through a small, versioned `/api/ios/v1/` facade. Python remains the sole authority for readiness scoring, prescription generation, exercise selection, loads, sets, RIR, validation, and training decisions. The phone presents server results and records the user's actions; it does not construct or change a prescription.

The **first useful release** is the following connected strength-training slice:

1. Securely pair the iPhone with the owner's local server.
2. Show today's readiness and relevant training/workout status.
3. Enter and save a manual readiness check-in.
4. Request and display a server-generated prescription and its warnings.
5. Start the server-authorized workout.
6. Log sets against the returned plan.
7. Complete or abandon the workout.
8. Record manual session RPE, or explicitly mark it not recorded.
9. Read basic workout history and existing progress summaries.
10. Open the existing post-workout review in the app, including optional form self-ratings and rubric marks.

**Acceptance:** the owner can complete a normal strength session from the iPhone without opening the web UI, while every training decision and validation result remains server-authoritative. The client receives an acknowledgement before displaying a mutation as saved. Existing web and CLI flows continue to work unchanged.

The post-session review uses existing server review/form contracts. It must be available in the first-release app, but review marks and form ratings remain optional and are not needed to complete a workout. They must not be calculated by the phone or an LLM.

### Explicitly not a first-release prerequisite

HealthKit, Apple Workout import, offline mutation sync, manual cardio, advanced Longevity analytics, background processing, Apple Intelligence, and PCC are deferred. Basic history/progress means read-only use of existing summaries, not a new dashboard or analytics engine. Keep these as later phases below rather than quietly adding them to the release gate.

## 2. Architectural invariants

- **Python is authoritative.** The client cannot construct, modify, select, or override a prescription. Readiness scores, exercise choices, load, sets, RIR, business validation, and training decisions come from Python.
- **No duplicate methodology.** Swift may validate form presentation (required fields, sensible number formatting), but the server repeats all domain validation. It must not reproduce training calculations.
- **No AI training decisions.** Apple Intelligence or any LLM may not generate/alter readiness scores, prescriptions, loads, RIR, exercise selections, form/rubric ratings, or other training decisions.
- **Keep existing clients compatible.** Add a versioned facade incrementally; do not change existing unversioned routes in a way that breaks the web UI or CLI.
- **Local-first, not cloud-dependent.** The normal product path is the owner's local server. No public endpoint, account, remote database, analytics, telemetry, or third-party exporter is required. PCC is a separate optional future AI exception, never a core dependency.
- **HealthKit is opt-in and read-only.** It is a measurement source, not a training authority. Preserve source, date/time, units and coverage. Python applies only its already documented readiness rules.
- **Manual values win.** When HealthKit is added, a manual value takes precedence per field and cannot be erased by a later import. Keep both values and provenance where correction/audit requires them.
- **Do not silently merge records.** Ambiguous HealthKit workouts remain separate until the owner explicitly associates them with an app session.
- **Append-only where the domain requires it.** Corrections/reviews follow existing append-only or superseding-record paths rather than editing history invisibly.
- **No scope drift into** vector databases, RAG, autonomous agents, time-decaying fatigue models, duplicated training logic, or sleep duration/Apple sleep-score features. Sleep remains outside this plan.

## 3. Existing implementation to reuse

| Area | Current implementation and implication for iOS |
|---|---|
| Readiness | `docs/READINESS.md`, `features/readiness.py`, `features/readiness_score.py`, `readiness_day`, `readiness_entry` and `readiness_override`. Five subjective values are 1–5, higher-is-better; fields may be partial. The server owns the score, minimum-data gate and overrides. HRV/RHR use existing baselines only when their requirements are met. |
| Prescription | `/api/prescribe` and existing deterministic prescription/rules stack. A new iOS facade must call it with model selection disabled, return the exact plan/warnings, and bind workout start to that server-issued plan. Do not accept client-authored loads, sets, RIR or a replacement plan. |
| Workout lifecycle | `strength_coach/workout.py`; current routes cover start, active/detail, set add/remove/correction, end and abandon. Sets and corrections have domain validation; ending requires session RPE 1–10 or an explicit not-recorded choice. Use those services, not a Swift workout engine. |
| History/progress | Existing history, progress and outcomes queries are descriptive. Reuse a small read-only subset; no duplicated analytics in Swift. Dates follow server-local date semantics unless a future profile/time-zone decision changes this. |
| Session RPE and review | Workout completion accepts manual session RPE. `session_feedback.srpe` accepts 1–10 and is append-only; current schema does not preserve whether a value came from a person or Apple Health. The review route returns server-built rubric items and writes marks/feedback. Form self-ratings have existing workout/history paths. The iOS client must not compute rubric values or calibration; preserve the server's rubric version and confidence semantics (see [`RUBRIC-CALIBRATION.md`](RUBRIC-CALIBRATION.md)). |
| Security | Current web server is unauthenticated HTTP on the home LAN (`LIM-57`). Do not send an iOS bearer token or personal workout data through that interface until the additive iOS auth/transport gate is met. |
| Web/CLI | These remain supported, current ways to use the application. The iOS project is a thin additional client, not a replacement or administrative console. |

## 4. Phased implementation plan

Each phase is separately reviewable. Add only the endpoints, migrations, client screens, and tests needed for that phase. The first connected vertical slice should be implemented before any offline queue, HealthKit importer, or model feature. Do not begin implementation until the owner approves the plan and the relevant phase.

### Phase 1 — Secure Native Foundation

**Goal:** install a small app that securely pairs and reads current server information.

**Steps:**

1. Confirm the target iPhone/iOS, available Mac/Xcode path, local server host, and preferred deployment transport.
2. Implement a minimal SwiftUI shell and one-time pairing flow. A short-lived pairing code generated locally by the server/CLI authorizes exchange for a random per-device credential; there is no open device registration.
3. Store the credential in Keychain. Add a simple local revoke/re-pair procedure. Store only a verifier/hash server-side where practical; never log the credential.
4. Add the `/api/ios/v1/` namespace and only the first-phase read contracts: bootstrap/capabilities, today's status, and read-only history/progress summaries. Retain canonical server date/timezone semantics and response units.
5. Add device authentication and server-side checks for every iOS request. Pairing-code exchange is protected by the one-time code; there are no unauthenticated write endpoints.
6. Add the minimum API contract/integration tests for authentication, revocation, read-only status/history and errors. Do not define or implement the entire future API up front.

**Acceptance:** the paired iPhone can retrieve relevant server information over the selected secure private-network path; an unpaired or revoked device is rejected; credentials do not appear in logs; existing web and CLI behavior is unchanged.

**Scope note:** showing cached read-only information is allowed only when clearly marked with its last successful refresh time. Offline mutation is not promised in this phase.

### Phase 2 — Core Strength Training Workflow

**Goal:** complete a typical strength session entirely on the iPhone, online.

**Steps:**

1. Add manual readiness entry for the five existing subjective fields, preserving partial/missing values and displaying the returned server result. The phone does not calculate a score.
2. Add a prescription request that uses the current deterministic Python path, disables model-based selection for this client, and displays the returned plan and warnings without editing them.
3. Start only from the plan/session reference returned by the server. The server revalidates freshness, readiness acknowledgement and conflicts.
4. Build a focused workout logger for the prescribed exercise order and set fields supported by the existing API. Show an explicit saved/failed state based on the server response.
5. Complete or abandon through existing services. Capture manual session RPE 1–10, or an explicit “not recorded” choice; preserve server-measured duration or clearly identified manual duration.
6. Show recent workout history and a small set of existing progress summaries. No comprehensive dashboard or new calculation.
7. Expose the existing post-workout review as an optional screen: server-provided rubric items, optional manual marks/confidence, and existing form self-ratings. Keep it skippable and distinct from session RPE. Do not invent marks or make review a gate for workout completion.
8. Add idempotency at the same time as any mutation that may be retried after a timeout or duplicate tap. Keep the mechanism specific to the needed app operations, not a generic replication framework.

**Acceptance:** on the target iPhone, a user can save readiness, request the server prescription, start it, log sets, end it with manual session RPE (or explicitly not recorded), open and submit an optional form/rubric review, and view the completed session/history without opening the web UI. Tests establish that forged client plan values cannot alter the server plan, server validation is enforced, duplicate requests do not duplicate records, and existing web/CLI tests remain green.

**Boundary:** this is an online workflow. If connectivity fails, the UI must not claim a set, readiness entry, or completion has been saved when it has not. Durable offline capture is Phase 3.

### Phase 3 — Reliable Capture and Offline Support

**Goal:** add offline resilience only after the online strength flow is stable.

**Steps:**

1. Persist an active workout and mutation outbox locally before acknowledging offline capture to the user.
2. Give each queued mutation a stable client operation identifier; preserve per-workout ordering and the original local date/time/time zone.
3. Add server idempotency receipts alongside only the retriable mutations (set add, correction/removal, end, and any readiness write explicitly included). A repeated identifier with the same body returns the original result; a different body is a conflict.
4. Retry safely with bounded backoff and expose `pending`, `synced`, and `failed/needs attention` states. Do not discard queued work on a timeout or app restart.
5. Support explicit reconciliation for server conflicts, including a workout edited through another client. Never silently merge, overwrite or delete an event.
6. Add set correction/removal only through append-only event paths, with undo where it can be represented safely.
7. Keep fresh readiness scoring, prescription generation, workout authorization, and conflict resolution online/server-authoritative. Offline records are performed-work capture, not a new prescription and not proof of a server-completed workout until acknowledged.
8. Avoid a generic “sync every object” framework. Implement the smallest durable outbox that fits these workout/readiness operations.

**Acceptance:** capture can survive server disconnection, app termination and restart; reconnecting synchronizes each operation at most once; order and local-date context are preserved; partial failures remain visible/actionable; a fresh prescription is unavailable offline; no offline result is represented as server-authoritative.

### Phase 4 — HealthKit

HealthKit is optional and read-only. Ask permissions only when the owner enables the related feature. Never require HealthKit permission to enter readiness or complete a workout.

**Phase 4A: HRV and resting heart rate**

1. Request only HRV and resting-heart-rate read access needed by this use case.
2. Read available samples/aggregates with source, timestamp, unit and coverage; no sleep duration, sleep stages, or Apple Sleep Score.
3. Use those values only in the existing HRV/RHR readiness inputs and server scoring path, with existing baseline/minimum-reading requirements and weights unchanged. Do not create a new device score or infer subjective sleep, energy, mood, soreness or stress.
4. Display value/source/freshness and distinguish “no sample/limited history” from zero. HealthKit permission is epistemically limited: missing samples are not proof the user denied access.
5. Add field-level precedence: manual > HealthKit > other imported source. A later HealthKit refresh never overwrites a manual entry; preserve competing observations/provenance as needed.
6. Add the minimal source/provenance addition to readiness storage/API at implementation time. Existing source labels do not yet provide a HealthKit-specific import contract.

**Acceptance:** with read access, available HRV/RHR flow to the existing server readiness assessment; without samples or permission, fields remain unknown; a manual correction remains selected after later HealthKit imports; baseline eligibility and score behavior match existing Python rules; no sleep data is requested or consumed.

**Phase 4B: Apple Workout summaries and related cardio data, if useful**

1. Import completed HealthKit workout summaries only after the HRV/RHR slice is stable. Preserve workout type, start/end, duration, source/device and HealthKit object identity where available.
2. Preview before materializing/importing. Keep Apple strength workout summaries as summaries: never infer exercises, sets, repetitions, loads or RIR.
3. Do not merge an Apple workout into an app session based only on time overlap. Offer an explicit association with a displayed existing app session; ambiguous records remain separate.
4. Add cardio records only through the existing descriptive cardio contract, with explicit provenance. No cardio prescription or fatigue model is introduced.
5. Keep HealthKit source deletion/updates and duplicate protection auditable. Do not retain raw sample time series unless a separate user-facing need justifies it.

#### Apple Workout Effort Score and session RPE

When supported effort data is available for an Apple workout that the owner has explicitly associated with an application session, it **may populate the effective session sRPE only when no manual sRPE already exists**. It is an optional source, not a requirement for Phase 2 or the first release.

- Preserve the exact HealthKit effort identifier (`workoutEffortScore` versus `estimatedWorkoutEffortScore`), source/device, value, timestamp and whether it is estimated or user-entered where the API exposes that distinction.
- Do not overwrite a manual value. If a manual value is later entered, it takes precedence; keep the Apple record and provenance rather than deleting it.
- Add source-aware persistence/read behavior before mapping Apple data into the app's effective `session_feedback.srpe`; the current table has no source field. A linked immutable HealthKit record plus an explicit selected-source field, or a small additive schema, is preferable to treating imported Apple data as manual.
- Accept only a supported value already compatible with the app's 1–10 session-RPE range; do not infer, rescale, average, or fill a missing score with a default.
- Keep session sRPE distinct from cardio-log sRPE, exercise-level RIR, workout metrics, the post-workout critique composite, and per-item rubric marks. Apple effort does not write or change those values.
- Late import may update a descriptive session feedback value only through an auditable source-aware path. It must not regenerate or retroactively alter a prescription.

**Acceptance:** unlinked Apple workouts stay separate; repeated imports are idempotent; strength details are never fabricated; imported effort retains its Apple/estimated/manual provenance; manual sRPE wins; unsupported or absent effort remains missing; prescriptions and critique/rubric calculations are unaffected.

### Phase 5 — Optional Enhancements

Only pursue after the core app is useful and stable, with a separate scope/approval decision for each feature:

- **Apple Intelligence:** optional tools may parse a spoken/typed set entry into an uncommitted draft, explain a server-produced prescription, summarize completed training, or structure free-text notes. The user reviews/accepts any draft before it reaches server validation. The model never controls training decisions or computes numbers.
- **PCC:** an explicitly selected Apple Private Cloud Compute option for a user-invoked AI task; disabled by default, visibly identified as Apple server processing, with a preview of the context and consent before personal workout/health data is included. It is not used by pairing, readiness, prescription, capture, or sync; no automatic fallback from on-device mode; core functionality remains available with PCC disabled or offline.
- Additional HealthKit observations (steps, body mass, VO₂max), richer cardio imports, richer but descriptive Longevity views, background delivery, Apple Watch companion, or historical XML backfill only when a concrete use case justifies their added privacy/schema/testing cost.
- Do not add sleep duration, sleep stages, or Apple Sleep Score under this plan.

**Acceptance:** each enhancement is independently disableable and does not become a dependency of pairing, readiness, prescription, workout capture, or review. On-device AI and PCC outputs are suggestions/text only; all numeric training data still pass through explicit user review and existing server validation.

## 5. Offline behavior — explicit contract

| Action | Phase 1–2 behavior | Phase 3+ behavior |
|---|---|---|
| View previously fetched status/history | May show cache, clearly labelled with refresh time and stale state. | Same. |
| Enter readiness | Requires an online server acknowledgement; an unsent form is not recorded/scored. | May queue a clearly labelled manual entry if included in the outbox; it is not scored until Python receives it. |
| Start a workout or request a fresh prescription | Requires server connectivity. | Still requires server connectivity and a current server-issued plan. |
| Log an in-progress set / finish | Requires server acknowledgement; do not claim saved on failure. | Can be durably captured locally and queued; show pending until server acknowledgement. |
| Synchronize pending changes | Immediate request/response; no offline queue guarantee. | Ordered, idempotent retry/reconciliation. |
| Readiness score/prescription while offline | Not available as a fresh result. | Still unavailable; no on-device substitute. |

## 6. API and data approach

Preserve `/api/ios/v1/` as the future facade namespace, but implement endpoints only when a phase needs them. Existing web/CLI routes remain intact and authoritative. Do not prebuild the earlier proposed full route inventory or generic `/sync/all` framework.

| Increment | Contract needed | Notes |
|---|---|---|
| Phase 1 | Protected pairing exchange; `GET bootstrap/today`; read-only recent history/progress | Return server/API version, server-local date/timezone, capabilities, readiness/workout status and small existing summaries. No config paths or secrets. |
| Phase 2 | Read/write readiness; request prescription; read active workout; start; add set; complete/abandon; read history/progress; optionally review/form | Mutations require authentication and a stable idempotency key/operation ID. Start references a server-issued plan identifier/digest; the client cannot submit an altered plan. Validate every field via existing Python services. |
| Phase 3 | Add/correct/remove set and offline event replay/reconciliation | Add narrowly scoped receipts and conflict responses as required by the operation. |
| Phase 4+ | HRV/RHR provenance; HealthKit record import and optional workout association | Add only the source/provenance fields and routes needed by enabled types; keep user-consented HealthKit read-only. |

All dates use server-local calendar semantics for readiness/prescription. Preserve timezone/absolute timestamps for captured workout events; do not infer training date from a UTC date slice. Use the server's canonical units and validation. Return stable, useful validation/conflict errors without exposing file paths, stack traces or secrets.

### Minimal data changes anticipated

- **Phase 1:** per-device authorization record and a revocable credential verifier; avoid a user/account system.
- **Phase 2:** plan/workout references and request idempotency only where needed; reuse current append-only workout, readiness and feedback services.
- **Phase 3:** small operation receipt/outbox schema for retry safety; not a generic replicated-object data model.
- **Phase 4:** HealthKit source-object identity/provenance and field-level source precedence. For Apple effort, source-aware session RPE is necessary because current `session_feedback` rows do not identify their source.

Review exact migration sequence against the implementation branch at coding time. Do not change core methodology or current web/CLI data behavior as a side effect.

## 7. Security and deployment — adequate, not a separate project

The present home-LAN server has no authentication and uses HTTP (`LIM-57`). The iPhone must not send credentials or personal workout data through the existing unauthenticated interface. Add the smallest defensible iOS boundary before personal use:

- Authenticate all iOS requests with a per-device random credential; protect it in Keychain, keep only a verifier/hash server-side, and provide a clear revoke/re-pair command.
- Pair only with a short-lived, one-use code generated locally by the owner. Protect the exchange against guessing; there is no open registration or unauthenticated data mutation.
- Use a secure transport appropriate to the chosen private deployment and rely on standard platform TLS validation. Do not make certificate pinning, a custom CA management system, or a complex token lifecycle a prerequisite without a demonstrated need.
- Do not port-forward the service or expose a public API. A trusted home-LAN HTTPS deployment is the default. **Tailscale may be considered** if the owner wants a private remote path and accepts its account/control-plane dependency; it does not replace app-level authentication and must not create an unauthenticated mutation path. No VPN/tailnet is required for local-only home use.
- Do not build elaborate DNS-rebinding, public-IP-audit, packet-capture, Internet-disabled or general egress test programs as release gates. Basic tests still verify authentication/revocation, normal TLS validation, no secret logging, and that the app is configured for the paired private service rather than a public server.
- No analytics, telemetry, advertising SDK, remote crash reporting, cloud database, or automatic Internet fallback. Core features use the local Python server. The optional later PCC AI call is the only app-level non-local exception in scope, and is fully separate from core API traffic.

**Stop condition:** if the chosen installation/transport cannot provide understandable secure communication and authentication on the owner's actual setup, stop at the disposable Phase 1 spike and choose an alternative. Do not invent custom cryptography or silently fall back to HTTP with a bearer token.

## 8. Swift client structure

Keep the app simple and testable. A reasonable initial layout is:

```text
ios/StrengthCoach/
  App/
  Features/
    Today/
    Readiness/
    Workout/
    History/
  Core/
  Networking/
  Persistence/
  HealthKit/       # added in Phase 4, not required by the initial app
  Tests/
```

Use SwiftUI views for presentation, small observable feature state for user interaction, one API client for DTO/network handling, and a local persistence component only when needed by the phase. Add protocol abstractions when they make a boundary testable or are used by multiple features; do not require a distinct repository, service, and use-case layer for every screen. Keep business rules in Python. The initial app can be mostly online and need not ship a complex local database/outbox.

## 9. Tests and quality gates

Prioritize server contract/domain tests; keep UI tests focused and robust. Add coverage with each phase, not speculative tests for unimplemented features.

### Phase 1–2

- Pairing: one-use code, rejected invalid/reused code, auth required, revoked credential rejected, no secret in logs.
- Contract tests for each implemented versioned endpoint, date/timezone/units, useful validation/conflict responses, and stable server-issued plan reference.
- Prescription boundary: altered client plan/load/set/RIR is rejected or ignored; an iOS request cannot enable a configured external LLM; existing web/CLI requests remain unchanged.
- Workout integration: start, set add, completion, duplicate/retry, explicit not-recorded sRPE, and history retrieval against temporary SQLite.
- Manual iPhone acceptance: a normal session can be completed without opening the web app; accessible set entry and clear server-acknowledged save state.
- Run existing readiness, prescription, workout, history, session-feedback, docs-manifest and docs-consistency tests unchanged.

### Phase 3

- Kill/relaunch and disconnect at each queue state; verify durable ordering, idempotent retry, partial acknowledgement and visible conflict.
- A stale cached plan cannot authorize a new session; queued performed work is not presented as a fresh server prescription or completed server session.
- Manual corrections append; no queued mutation is silently dropped or duplicated.

### Phase 4

- HealthKit unavailable/disabled/no-sample/limited-history cases remain unknown, not zero. Test manual-over-HealthKit precedence and source/timestamp display.
- Existing readiness baselines and score are unchanged. Do not request or process sleep data.
- Repeated workout import is idempotent; no inferred strength sets; ambiguous association remains separate.
- Apple effort can be selected only for an explicit match and empty manual sRPE; later manual sRPE wins; provenance remains queryable; no prescription/rubric changes.

### Phase 5

- Apple Intelligence is disabled by default. On-device and PCC choices are explicit; PCC requires a user action and context consent, has no automatic fallback, and is unnecessary for all core flows.
- Model-generated text/drafts cannot write a prescription, set, readiness score, RIR, form rating, rubric mark, or policy value without explicit user action and normal server validation.

## 10. Risks and decisions to settle during implementation

| Question/risk | Recommended handling |
|---|---|
| Target phone, OS, Xcode/signing | Confirm before Phase 1; keep the initial OS target to what the owner can run. Do not choose a higher OS solely for optional HealthKit effort or AI APIs. |
| Private server transport | Choose simple maintained home-LAN TLS; consider Tailscale only if its operational/privacy trade-off is acceptable. App authentication remains required. |
| Existing unauthenticated HTTP API | Add an authenticated versioned facade before iPhone mutations; do not retrofit/break existing web/CLI routes in this task. |
| Plan staleness or concurrent web use | Server validates at start and on mutation; return a clear conflict. Client refreshes and asks the owner, never silently overwrites. |
| Partial or missing readiness | Show the server's status and warnings; no Swift score and no missing-as-zero behavior. |
| Session RPE source | Manual remains first choice. Future Apple effort is source-labelled, only associated after confirmation, and usable only when no manual value exists. Current storage needs additive provenance. |
| Rubric use | Reuse server's current review payload and rubric version. Marks are human optional feedback; do not implement scoring or calibration logic in Swift. |
| HealthKit scope | HRV/RHR first; all other types later by explicit scope. No sleep/sleep score in this plan. |
| PCC privacy and availability | Separate future decision; disabled by default, user-invoked, context preview/consent, no health data by default, no core dependency. |
| Offline complexity | Defer durable offline mutation until an online session loop is proven. Cached reads do not imply the ability to prescribe or sync offline. |

## 11. First task after approval

Start Phase 1 by confirming the target iPhone/iOS and build/signing path, then choose the simplest acceptable private transport for the owner's server. Implement only the secure pairing/read-only foundation and prove that a paired device can fetch today's status and basic history. Do not begin HealthKit, offline sync, cardio, or PCC work before the core iPhone strength workflow is accepted.

## 12. References

### Existing application contracts

- [`API.md`](API.md) — current routes, limits, local network security state and date semantics.
- [`READINESS.md`](READINESS.md) and [`READINESS-SCORE.md`](READINESS-SCORE.md) — readiness merge, manual precedence, baselines, score/gates.
- [`DATA-MODEL.md`](DATA-MODEL.md) and [`DATA-QUALITY.md`](DATA-QUALITY.md) — persisted fields, append-only records and missingness.
- [`METHODOLOGY.md`](METHODOLOGY.md) — authoritative decisions and exclusions, including sleep/cardio boundaries.
- [`RUBRIC-CALIBRATION.md`](RUBRIC-CALIBRATION.md) — current B1 review outcome and the limits/gates on interpreting rubric agreement.
- [`LONGEVITY-REVIEW.md`](LONGEVITY-REVIEW.md) — evidence limits for any later descriptive display.
- [`REFERENCES.md`](REFERENCES.md) #104–105 — session RPE context.

### Apple platform documentation for later phases

- [HealthKit data types](https://developer.apple.com/documentation/healthkit/data-types), [authorizing access](https://developer.apple.com/documentation/healthkit/authorizing-access-to-health-data), and [HealthKit queries](https://developer.apple.com/documentation/healthkit/queries) — read permissions and query patterns.
- [HKWorkout](https://developer.apple.com/documentation/healthkit/hkworkout), [HKWorkoutEffortRelationship](https://developer.apple.com/documentation/healthkit/hkworkouteffortrelationship), [HKWorkoutEffortRelationshipQuery](https://developer.apple.com/documentation/healthkit/hkworkouteffortrelationshipquery), and [Workout Effort Score](https://developer.apple.com/documentation/healthkit/hkquantitytypeidentifier/workouteffortscore) — workout and effort records. Confirm API availability and source semantics against the selected OS/device at implementation time.
- [Protecting user privacy](https://developer.apple.com/documentation/healthkit/protecting-user-privacy) — HealthKit obligations.
- [Foundation Models](https://developer.apple.com/documentation/foundationmodels), [SystemLanguageModel](https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel), and [Private Cloud Compute integration](https://developer.apple.com/documentation/foundationmodels/adding-server-side-intelligence-with-private-cloud-compute) — optional later Apple on-device/PCC modes.
- [App Transport Security](https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity) and [local-network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy) — deployment considerations, not an instruction to implement a custom TLS stack.

## Related repository documents

- [`ROADMAP.md`](../ROADMAP.md) §4.29 — proposal status and phase tracking.
- [`WEB-UI.md`](WEB-UI.md) and archived [`UI-MOBILE-AUDIT.md`](archive/UI-MOBILE-AUDIT.md) — existing responsive client.
- [`DECISIONS.md`](DECISIONS.md), [`PRIVACY.md`](PRIVACY.md), [`OPEN-QUESTIONS.md`](OPEN-QUESTIONS.md), and [`manifest.yaml`](manifest.yaml).

## Completion state

This remains a documentation proposal. No iOS application, backend route, migration, HealthKit integration, training logic, or server behavior is implemented by this document. Each implementation phase requires the owner's approval.
