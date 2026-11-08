# iOS Phase 3A — HealthKit HRV/RHR readiness: implementation contract

**Status:** implemented 2026-11-08; unit, simulator and live-server workflow verified. Physical
HealthKit acceptance remains pending. This contract remains the authoritative Phase 3A
specification. No Phase 3B, Phase 4 offline capture, HealthKit write access, sleep imports, new
score or training-rule change is authorized.

**Scope:** fixes the exact server surface, canonical readiness merge, data model, client surface,
permissions, concurrency, tests, acceptance and rollback for Phase 3A only: opt-in, read-only
HealthKit heart-rate-variability (HRV) and resting-heart-rate (RHR) readiness values.

**Explicitly separate:** Phase 3B (Apple Workout summaries, cardio imports, Apple effort values
and any associated workout/session changes) is out of scope and requires its own contract and
approval. This contract does not authorize Phase 3B, Phase 4 offline capture, HealthKit write
access, sleep imports, a new score or any training-rule change.

**Owner decisions approved 2026-11-08:**

1. Phase 3A only; Phase 3B is separate.
2. Read-only HeartRateVariabilitySDNN (ms) and RestingHeartRate (bpm) only. No sleep duration,
   sleep stages, Apple Sleep Score, general heart rate, workouts, respiratory data or write access.
3. Newest HRV sample within 48 hours; current local-day RHR; missing/stale means unknown, never zero.
4. Manual readiness wins over HealthKit; within HealthKit prefer Apple Watch only when positively
   identified, otherwise the newest eligible sample. Show source and sample age.
5. HealthKit is off by default. When enabled, values flow into the existing HRV/RHR readiness
   inputs and the existing server scoring path. Existing weights, baselines, minimum-reading rules
   and score semantics do not change. No inferred subjective fields or new score.
6. Explicit Import from HealthKit on Today/Readiness plus an app-open/refresh attempt while
   enabled. No background delivery, observer queries or write access. Request permission only
   when enabled.
7. No historical backfill; import only the current relevant HRV/RHR values.
8. Additive provenance schema/API only; no raw HealthKit time series.
9. Physical iPhone testing with real HealthKit data is available.
10. HealthKit values travel to the local server over the existing trusted-LAN plain-HTTP model;
    no external/cloud fallback.

## 1. Purpose and non-goals

A paired iPhone may optionally read the newest eligible HRV sample and today's resting heart rate
from HealthKit, send those observations to the existing authenticated local server, and let the
server merge them into readiness with manual precedence. The server stores small append-only
observations with provenance, returns the canonical effective readiness, and remains the sole
authority for readiness values and scores. The phone never writes HealthKit values directly into
manual readiness, never computes a score and never changes a prescription.

Non-goals:

- No sleep duration, sleep stages, sleep score or inferred sleep.
- No general heart-rate stream, HRV time series or raw HealthKit sample history.
- No Apple Workout summaries, cardio records, workout effort score or sRPE mapping.
- No HealthKit write, background delivery or observer query.
- No new readiness score, weights, baselines, readiness gates or training rules.
- No automatic import of other readiness fields.
- No health data sent to an external service, LLM or cloud.

## 2. Canonical effective readiness

### 2.1 Definitions

An **observation** is one accepted HealthKit sample for one field on one server-local date. It is
stored append-only with its source/provenance. An observation is not an effective readiness value.

The **effective readiness value** for a field/date is the value selected by the canonical merge in
section 2.2. Effective values, their sources and their provenance are what every consumer must see.

### 2.2 One merge, one precedence

The server must expose one canonical effective-readiness merge/query mechanism. Precedence is:

    manual/preset (readiness_entry) > healthkit (latest observation) > imported (readiness_day)

The merge must be shared by every consumer:

- readiness day / Today readiness;
- readiness series;
- readiness history;
- readiness scoring;
- HRV/RHR baseline eligibility.

No consumer may query healthkit_readiness directly, write its own HealthKit merge, or apply a
different precedence. Feature, scoring and presentation code must consume the same effective
values and provenance produced by the canonical merge. This is a consolidation of the existing
readiness merge path; do not refactor unrelated readiness, scoring or training code.

### 2.3 Storage boundary

HealthKit observations must not be written into readiness_day or readiness_entry. Those tables
keep their existing meanings: readiness_day is the imported CSV layer; readiness_entry is the
manual/preset append-only layer. HealthKit is a separate source that the canonical merge reads.

### 2.4 Scoring boundary

Scores remain calculated exclusively by the existing Python readiness scoring implementation, using
the effective readiness values. Swift, SQL presentation code and the contract must not calculate,
recalculate or approximate a readiness score. If no existing scoring rule makes a score ready, the
existing unknown/insufficient result remains. Existing weights, baseline rules and thresholds,
minimum readings, readiness gates and prescription decisions are unchanged; a HealthKit
observation may satisfy an existing eligibility rule exactly as any other readiness value would,
but it does not change the rule.

### 2.5 Canonical-merge tests

The test suite must prove all consumers observe identical effective values and provenance:

- Build a date with an imported readiness_day value, a HealthKit observation and a manual entry.
- Read it through readiness day, readiness series, readiness history and scoring.
- Assert the same effective value, the same per-field source (manual, healthkit or import) and the
  same HealthKit provenance.
- Repeat with manual-over-HealthKit and HealthKit-over-import cases.
- Assert HealthKit observations are absent from readiness_day and readiness_entry.
- Assert the score is unchanged when the only change is an observation that existing baseline or
  scoring rules do not make eligible.
- Review that no consumer contains a second HealthKit merge; the canonical query is the only
  reader of healthkit_readiness.

## 3. Server data model — migration 0054_healthkit_readiness.sql

Additive only. Existing readiness_day, readiness_entry, readiness scoring, prescriptions,
workouts, sessions and review tables are untouched.

    CREATE TABLE healthkit_readiness (
        observation_id       TEXT PRIMARY KEY,              -- uuid4 hex
        device_id            TEXT NOT NULL REFERENCES ios_device(device_id),
        on_date              TEXT NOT NULL,                 -- server-local YYYY-MM-DD
        field                TEXT NOT NULL CHECK (field IN ('hrv_ms', 'rhr_bpm')),
        value                REAL NOT NULL CHECK (value > 0),
        sample_id            TEXT NOT NULL,                 -- HealthKit object UUID
        sample_at            TEXT NOT NULL,                 -- ISO-8601 with offset
        source_name          TEXT NOT NULL,                 -- display/audit only
        source_bundle_id     TEXT,
        source_class         TEXT NOT NULL
                             CHECK (source_class IN ('apple_watch', 'non_apple_watch', 'unknown')),
        source_model         TEXT,
        source_manufacturer  TEXT,
        imported_at          TEXT NOT NULL,                 -- UTC ISO-8601
        UNIQUE (device_id, field, sample_id)
    );

    CREATE INDEX idx_healthkit_readiness_date
        ON healthkit_readiness(on_date, field, sample_at);
    CREATE INDEX idx_healthkit_readiness_device
        ON healthkit_readiness(device_id, on_date);
    -- Append-only triggers: reject UPDATE and DELETE, matching readiness_entry.

- One row per selected field observation, not a raw time series.
- Multiple accepted observations may be retained append-only for provenance. The effective
  observation for a field/date is the latest by sample_at, then imported_at, then observation_id.
  Source preference is applied by the client before sending; the server does not reclassify source
  metadata.
- source_name is display/audit text and must never be the basis of source classification.
- A later HealthKit import never overwrites a manual readiness entry; precedence is per field.
- Migration rollback: drop the table and the matching 0054 schema_migration row together. The
  paired statement is added to IOS-CLIENT-PLAN.md section 13.2 when implemented.

### 3.1 Sample identity and complete observation

The immutable identity of one HealthKit observation is:

    device_id + field + sample_id (HealthKit sample UUID)

A **complete observation** consists of the identity plus all immutable attributes:

- on_date
- value
- sample_at
- source_name
- source_bundle_id
- source_class
- source_model
- source_manufacturer

The operation UUID is not part of sample identity. Operation identity and sample identity are
independent, as defined in section 4.4.

### 3.2 Deduplication rules

- Same identity and identical complete observation: idempotent no-op. Do not insert a second row;
  return the canonical effective readiness for the date.
- Same identity with any changed immutable attribute: conflict. This includes a changed value,
  sample timestamp, source name, bundle id, source class, model or manufacturer.
- Conflict response: 409 healthkit_sample_conflict. Insert nothing from the request.
- A new operation UUID importing an unchanged sample is still a no-op at the sample layer.
- Request-level atomicity: validate all samples and check all identities before inserting; if any
  sample fails validation or conflicts, the transaction rolls back and no observation is inserted.

## 4. Server API

### 4.1 Route

    POST /api/ios/v1/healthkit/readiness

Authentication: Bearer. Required header: Idempotency-Key: UUID. Device-scoped.

The route is available only when mutations_enabled is true. bootstrap capabilities include
healthkit_readiness: true in that case; healthkit remains false because Phase 3B is not built.
When mutations are disabled, healthkit_readiness is false and the route returns
503 ios_mutations_disabled.

### 4.2 Request

    {
      "date": "2026-11-08",
      "samples": [
        {
          "field": "hrv_ms",
          "value": 55.0,
          "sample_id": "4A5B...",
          "sample_at": "2026-11-08T06:30:00Z",
          "source_name": "Apple Watch",
          "source_bundle_id": "com.apple.health",
          "source_class": "apple_watch",
          "source_model": "Watch6,18",
          "source_manufacturer": "Apple Inc."
        },
        {
          "field": "rhr_bpm",
          "value": 52.0,
          "sample_id": "9C1D...",
          "sample_at": "2026-11-08T06:45:00Z",
          "source_name": "Apple Watch",
          "source_bundle_id": "com.apple.health",
          "source_class": "apple_watch",
          "source_model": "Watch6,18",
          "source_manufacturer": "Apple Inc."
        }
      ]
    }

- date is required and must equal the server-local current date. Historical/future dates are
  rejected; Phase 3A does not backfill.
- samples has one or two entries, one per field, both optional individually but at least one.
  Unknown fields, duplicate fields, an empty list or extra keys are rejected.
- value must be finite and greater than zero. Reject NaN, infinity, zero and negative values.
- sample_id is the HealthKit object UUID string, required, 1-128 characters.
- sample_at is required ISO-8601 with an offset. It must not be more than five minutes in the
  future. HRV must be no older than 48 hours at request time. RHR must fall on the supplied
  server-local date.
- source_name is required, trimmed, 1-128 characters. source_bundle_id is optional, 1-200
  characters. source_class is required and one of apple_watch, non_apple_watch or unknown.
  source_model and source_manufacturer are optional, each at most 200 characters. These fields
  are provenance; the server validates their shape and stores them but does not independently
  classify the HealthKit source.
- source_name is not a classification input. A sample with source_name "Apple Watch" but missing
  or ambiguous device metadata must be sent as source_class unknown.
- Same sample identity with any changed attribute is a conflict, even when the change looks
  cosmetic. See section 3.2.

### 4.3 Response

Return the canonical readiness payload from GET /api/ios/v1/today readiness, plus:

    {
      "healthkit": {
        "hrv_ms": {
          "value": 55.0,
          "sample_id": "4A5B...",
          "sample_at": "2026-11-08T06:30:00Z",
          "source_name": "Apple Watch",
          "source_bundle_id": "com.apple.health",
          "source_class": "apple_watch",
          "source_model": "Watch6,18",
          "source_manufacturer": "Apple Inc.",
          "imported_at": "2026-11-08T07:00:00+00:00"
        },
        "rhr_bpm": { "...": "same shape" }
      }
    }

- healthkit contains the selected/latest stored observations, not necessarily the effective
  values. A manual entry can win while the HealthKit observation remains present here.
- sources continues to label the effective field source; manual wins when present.
- The normal readiness status/score fields remain; importing HRV/RHR alone does not fabricate a
  ready score.
- GET /api/ios/v1/today must expose the same healthkit provenance map and effective sources. POST
  and GET must not diverge; both use the canonical merge.
- The response is stored in the Phase 2 idempotency receipt only after the mutation succeeds.
- Error envelope and codes: 400 validation_failed/unknown_field, 401/403 auth, 409
  idempotency_conflict or healthkit_sample_conflict, 503 ios_mutations_disabled. Details never
  contain tokens or raw HealthKit history.

### 4.4 Operation receipts versus sample identity

These are two different mechanisms and both must work:

- **Operation identity** is device + Idempotency-Key. Success stores the route, request hash and
  response in ios_operation_receipt inside the same transaction as the observations. A retry with
  the same key and identical body replays the stored response with Idempotent-Replay: true. The
  same key with a different body returns 409 idempotency_conflict.
- **Sample identity** is device + field + sample_id, independent of the operation key. It prevents
  duplicate observations when a new operation UUID imports an unchanged sample.
- Validation failures and sample conflicts create no successful operation receipt and insert no
  observations. After correcting the request, the client uses a new operation UUID.
- A new user-initiated import always uses a new operation UUID, even when the underlying sample is
  unchanged. The sample layer deduplicates it.
- Mixed valid/conflicting samples are rejected atomically; no partial success and no receipt.
- Receipt retention remains the Phase 2 30-day window. After receipt expiry, a new operation may
  replay the same sample; sample identity still returns a no-op or conflict as appropriate.

## 5. Apple Watch source classification

Classification is a client-side, deterministic, testable function of HealthKit sample source and
device metadata. It must not infer Apple Watch from a display name or bundle identifier alone.

### 5.1 Classes

    apple_watch       Positively identified Apple Watch.
    non_apple_watch   Positively identified non-Watch source (including iPhone or third party).
    unknown           Metadata missing or ambiguous; no positive classification.

### 5.2 Rules

- apple_watch: the sample's HKDevice manufacturer is Apple (case-insensitive, trimmed, Apple or
  Apple Inc.) AND HKDevice model matches the Apple Watch hardware pattern
  ^Watch[0-9]+,[0-9]+$ (for example Watch6,18). No other signal alone may produce this class.
- non_apple_watch: the sample's HKDevice manufacturer is present and not Apple; OR the manufacturer
  is Apple and a model is present but does not match the Apple Watch pattern. This includes an
  iPhone source.
- unknown: manufacturer missing/blank, model missing when positive classification would require
  it, or any other ambiguous metadata. A source_name of "Apple Watch" with no device metadata is
  unknown, not apple_watch.
- Source name and source bundle id may be stored as provenance but must not be used to classify
  Apple Watch.
- Classification is recorded in source_class and is part of the immutable observation identity.

### 5.3 Selection

After filtering to eligible samples (section 6.3):

1. If at least one eligible sample is apple_watch, select the newest apple_watch sample.
2. Otherwise select the newest eligible sample across non_apple_watch and unknown.
3. Deterministic ties: latest sample_at, then lexicographically smallest sample_id.
4. Unknown samples are never promoted to apple_watch. Non-Apple-Watch samples are never excluded
   solely because they are not Apple Watch.

Tests must cover apple_watch, non_apple_watch and unknown classification, the "Apple Watch" name
with missing device metadata, fallback when no Apple Watch exists, and deterministic ties.

## 6. Client HealthKit behavior

### 6.1 Opt-in and permission

- Settings toggle: HealthKit readiness, default off. Persist the choice in UserDefaults.
- Request read authorization only when the owner turns it on, for exactly
  HeartRateVariabilitySDNN and RestingHeartRate. No write authorization. Do not request sleep,
  workouts, heart rate, respiratory or other types.
- Manual readiness, prescription and workout flows work without HealthKit and without permission.
- Update NSHealthShareUsageDescription to explain the two read types and that data stays on the
  owner's local server. No HealthKit entitlement beyond the existing app capability is added.

### 6.2 Observable states

HealthKit does not reliably expose whether read permission was denied. An empty query can mean no
data or denied read access. The app must not infer denial from an empty result, authorization
request completion or any read-authorization status. Use these states consistently in UI, tests
and acceptance:

    featureDisabled       Feature is off. No HealthKit query or permission request.
    unavailable           HealthKit is unavailable on this device/build/server capability.
    enabled               Owner enabled the feature and the authorization request completed.
                          This does not prove read access was granted.
    noEligibleSample      Query completed, no eligible sample. Permission denial versus absence
                          is indeterminate.
    eligibleSample        At least one eligible sample exists.
    staleSample           A sample exists but is outside the accepted window; it is not imported.
    importError           HealthKit query, network, server or validation failure.

UI wording:

- unavailable: "HealthKit is not available on this device."
- noEligibleSample: "No eligible HealthKit sample was returned. This can mean no data or that read
  access was not granted."
- staleSample: "The HealthKit sample is outside the accepted window."
- importError: a normal retryable error message with the server's safe detail.
- Never show "not authorized" or "denied" as a fact derived from an empty query.
- Never show zero for a missing or stale sample.

### 6.3 Sample selection

Use a testable HealthKitReadinessProviding protocol; production uses HKHealthStore.

- HRV: eligible samples are finite, >0, with sample time in [now - 48 hours, now + 5 minutes].
  Apply the source classification and selection rules in section 5.3.
- RHR: eligible samples are finite, >0, for the current server-local date. Apply the same source
  selection. Use a timestamp that lies on that server-local date: prefer the sample start for a
  daily resting-HR interval, and use the end only when the end also lies on the date. If neither
  timestamp lies on the date, treat the sample as not eligible rather than shifting the date.
- Client sends at most one HRV and one RHR. If neither exists, make no request and show the
  noEligibleSample state. If samples exist but all are stale, show staleSample and make no request.
- Use the server date from bootstrap/today as date. Convert sample timestamps to ISO-8601 with
  offset. If the phone and server are in different time zones, the server remains authoritative
  and may reject the date; the UI must show that result without silently changing the date.
- Never copy HealthKit values into the manual readiness form.

### 6.4 Single-flight import

All import triggers go through one serialized coordinator:

- Explicit Import from HealthKit.
- App-open attempt while enabled.
- Refresh-triggered attempt while enabled.

Rules:

- At most one HealthKit query and one POST are in flight at a time. Explicit and automatic
  triggers must not overlap.
- A trigger while an import is running sets one coalesced follow-up flag; it does not launch a
  second query. After the current import finishes, run at most one follow-up if still enabled and
  appropriate.
- Do not queue unbounded triggers.
- A retry of an ambiguous request reuses the same operation UUID and exact body through the R1
  journal. Do not create a new operation UUID for the same logical retry.
- A new import, including a user-initiated import of an unchanged sample, uses a new operation
  UUID. Server sample identity deduplication prevents a duplicate observation.
- Cancellation or app background: no background work continues. If a task is canceled before a
  journal entry is written, no server operation exists and a later import is a new operation. If
  it is canceled after journaling or after the request may have reached the server, keep the R1
  journal entry and retry with the same UUID; do not start a fresh UUID for that ambiguous
  operation.
- Refresh completion interacts with import by waiting for the import acknowledgement and the
  authoritative Today/readiness fetch; it must not replace the import with a parallel refresh.
  Coalesce a refresh requested during import into the single follow-up.
- No HKObserverQuery, background delivery or periodic background task.

### 6.5 Import and authoritative refresh

After selection, the flow is:

1. Query HealthKit and select at most one HRV and one RHR using sections 5.3 and 6.3.
2. POST the selected observations to /api/ios/v1/healthkit/readiness with a UUID
   Idempotency-Key. Add MutationKind healthkitReadiness so the R1 journal and same-key retry rules
   apply.
3. Receive the mutation acknowledgement. If the outcome is ambiguous, leave the journal entry
   pending and retry with the same UUID/body; do not claim success.
4. Fetch the authoritative Today/readiness payload from GET /api/ios/v1/today (or the equivalent
   readiness read) after the acknowledgement. Do not treat the POST response as the display
   authority.
5. Display the effective values, effective sources, sample age, score/status and basis returned by
   the Python readiness implementation.
6. Clearly distinguish stored HealthKit observations from effective readiness. The healthkit map
   is an observation record; the readiness values/sources are the effective values. A manual value
   may win while the observation remains visible.
7. Do not imply every imported HRV/RHR observation changes the readiness score. Baseline
   eligibility and existing scoring rules still apply; an observation can be stored and displayed
   without changing the score.
8. If the authoritative refresh fails after a successful acknowledgement, show the import as
   accepted but the readiness view as stale/unrefreshed, and offer a refresh retry. Do not show
   the POST payload as authoritative.

## 7. Tests and acceptance traceability

### 7.1 Server tests

- Migration creates the append-only healthkit_readiness table and indexes.
- Valid HRV-only, RHR-only and both-field imports return the canonical readiness payload and
  provenance.
- Canonical merge consumer parity: readiness day, series, history, scoring and baseline eligibility
  return identical effective values and provenance for the same fixture; POST and GET readiness
  return the same healthkit provenance for the same observations.
- Manual/preset > HealthKit > imported precedence; a later HealthKit import does not overwrite
  manual; healthkit observations are not present in readiness_day or readiness_entry.
- Scores are produced only by the existing Python scoring path; eligibility and weights are
  unchanged when an observation is not score-eligible.
- Same sample identity + identical complete observation is a no-op; changed value, sample_at,
  source_name, source_bundle_id, source_class, model or manufacturer each produces 409.
- Mixed valid/conflicting samples insert nothing and create no successful receipt.
- Operation receipt behavior: same key/body replays; same key/different body conflicts; new key +
  unchanged sample no-ops; sample dedup survives receipt expiry.
- Reject wrong date, stale HRV (>48h), future timestamp (>5m), wrong RHR date, nonfinite/zero/
  negative values, unknown/duplicate fields, oversized source fields and unknown source_class.
- Device scoping and revoked-device behavior.
- Capability true/false and 503 with mutations disabled.
- No sleep/workout/effort route or field is added.

### 7.2 Client tests

- Fake provider classification: apple_watch, non_apple_watch, unknown; "Apple Watch" source name
  with missing device metadata is unknown; Apple Watch is preferred only when positively
  classified; no Apple Watch falls back to newest eligible; ties are deterministic.
- HRV eligibility: newest within 48h, stale excluded; RHR current-day selection; both/missing/stale
  states.
- Observable states: featureDisabled, unavailable, enabled, noEligibleSample, eligibleSample,
  staleSample, importError. No test may expect a denied-read inference.
- Payload encoding: date, field, value, sample id/timestamp, source class/model/manufacturer,
  source name/bundle and Idempotency-Key.
- Toggle default off; permission request only after enabling; manual readiness still works when
  unavailable, no sample or an indeterminate read result.
- Single-flight: explicit and automatic triggers never overlap; one coalesced follow-up; canceled
  task keeps the same operation UUID; new import uses a new UUID.
- R1 journal captures the import and replays the same UUID/body; authoritative refresh occurs after
  acknowledgement; POST payload is not treated as display authority.
- Display distinguishes observations from effective values and shows manual precedence and
  score/basis without implying a score change.

### 7.3 Acceptance tests mapped to normative requirements

| Requirement | Test / acceptance |
|---|---|
| Phase 3A only; no 3B/offline/sleep/write | Server route/field tests; client type list; acceptance review |
| One canonical merge; all consumers identical | Consumer-parity fixture across day/series/history/scoring/baseline |
| No HealthKit writes to readiness_day/entry | DB assertions after import |
| Python-only scoring | Existing scoring tests; no Swift/SQL score implementation review |
| Sample identity and complete-observation conflict | Same/changed value, timestamp and each provenance field; mixed request |
| Request atomicity | Mixed valid/conflicting request inserts nothing |
| Operation receipt vs sample identity | Same key replay; new key no-op; changed identity conflict; receipt expiry |
| R1 journal and ambiguous retry | Same UUID/body on replay; new import uses a new UUID |
| Apple Watch classification and fallback | Three classes, missing metadata, name-only false positive, tie; Apple Watch only when positively identified |
| Permission states indeterminate | Client state tests and acceptance copy |
| Single-flight/cancellation/lifecycle | Coordinator tests with overlapping triggers and cancellation |
| Authoritative refresh | Import acknowledgement then GET Today/readiness; refresh failure state |
| Manual precedence | Manual entry after import; later import does not change effective source |
| No score change implied | Observation stored without eligibility; score/status unchanged |
| No backfill/raw time series | Import only current HRV/RHR; schema stores one observation per field/date |
| POST/GET provenance parity | Same observations return the same healthkit map from both paths |
| Rollback | Merge integration removal, table/migration drop and client toggle-off rehearsal |

## 8. Acceptance

- Feature off: no HealthKit prompt, no reads, manual readiness unchanged.
- HealthKit unavailable: honest unavailable state; manual flow works.
- Enabled with data: eligible sample imported; effective values/sources, sample age, score/status
  and basis are shown from the authoritative server refresh.
- No eligible sample: the noEligibleSample wording is used; no claim of denied permission.
- Stale sample: staleSample is shown and nothing is imported.
- Import/network/server error: error state with retry; no zero or inferred value.
- Manual entry after import remains selected after a later HealthKit import.
- Every imported observation does not imply a score change; baseline/scoring rules still decide.
- Single-flight: overlapping triggers do not duplicate queries/imports; cancellation/replay uses
  the same operation UUID.
- No sleep/workout data requested or consumed; Phase 3B remains absent.
- Simulator tests use the fake provider; physical iPhone acceptance uses real HealthKit data and a
  temporary SQLite database. Never test against live data/coach.db except the owner's existing
  backup discipline.

## 9. Rollback

- Turn the client toggle off and remove the HealthKit importer/UI; no server change is required
  and manual readiness remains.
- Remove the POST route and healthkit_readiness capability.
- Remove the Phase 3A canonical-merge integration (or deploy a verified no-op that does not query
  the table) before dropping the table. Do not leave code that reads a dropped table.
- With the server stopped and a verified backup, drop healthkit_readiness and delete the matching
  0054 schema_migration row together. Do not drop or rewrite readiness_entry, readiness_day,
  prescriptions, workouts or sessions.
- Phase 3A receipts are harmless once the route is removed and expire under the existing 30-day
  window. Do not delete unrelated operation receipts.
- Revoke HealthKit permission on the phone if desired. No external data exists.
- Because no existing table is altered, rolling back restores the pre-Phase-3A readiness behavior
  once HealthKit observations are gone and the canonical merge no longer has observations to read.

## 10. Limitations and deferred work

- Read permission denial and no data are not distinguishable; the UI reports authorization request
  completion and no eligible sample separately, without claiming denial.
- HealthKit source/device metadata is provenance, not a measurement guarantee. Unknown metadata
  stays unknown and is eligible only through the fallback rule.
- Phase 3A does not reconcile sample deletion/update, historical backfill, sleep, workouts, cardio,
  Apple effort/sRPE or raw time series.
- Phone/server timezone differences can cause a date rejection; the server date remains
  authoritative.
- Plain HTTP on the trusted home LAN only, consistent with the existing deployment.

## 11. References

- IOS-CLIENT-PLAN.md section 4 (Phase 3 scope), section 10 (risks) and section 13 (rollback).
- docs/READINESS.md, docs/READINESS-SCORE.md, docs/LIFT-READINESS.md, docs/DATA-MODEL.md.
- docs/API.md for the authenticated facade and idempotency contract.
- IOS-PHASE-2-CONTRACT.md for bearer/receipt/error conventions.
