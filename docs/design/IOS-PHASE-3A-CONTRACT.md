# iOS Phase 3A — HealthKit HRV/RHR readiness: implementation contract

**Status:** draft for owner approval, 2026-11-08. Documentation only; this contract creates no
code, route, migration or client feature. Phase 2 and the R1/R3/R5 reliability work are complete
and closed. Do not implement Phase 3A until the owner approves this contract.

**Scope:** fixes the exact server surface, data model, client surface, permissions, tests,
acceptance and rollback for Phase 3A only: opt-in, read-only HealthKit heart-rate-variability
(HRV) and resting-heart-rate (RHR) readiness values. Phase 3B (Apple Workout summaries, cardio
imports, Apple effort values and any associated workout/session changes) is explicitly out of
scope and needs a separate contract.

**Owner decisions approved 2026-11-08:**

1. Phase 3A only; Phase 3B is separate.
2. Read-only HeartRateVariabilitySDNN (ms) and RestingHeartRate (bpm) only. No sleep duration,
   sleep stages, Apple Sleep Score, general heart rate, workouts, respiratory data or write access.
3. Newest HRV sample within 48 hours; current local-day RHR; missing/stale means unknown, never zero.
4. Manual readiness wins over HealthKit; within HealthKit prefer Apple Watch, otherwise the newest
   eligible sample. Show source and sample age.
5. HealthKit is off by default. When enabled, values flow into the existing HRV/RHR readiness
   inputs and the existing server scoring path. Existing weights, baselines, minimum-reading rules
   and score semantics do not change. No inferred subjective fields or new score.
6. Explicit Import from HealthKit on Today/Readiness plus an app-open refresh while enabled. No
   background delivery, observer queries or write access. Request permission only when enabled.
7. No historical backfill; import only the current relevant HRV/RHR values.
8. Additive provenance schema/API only; no raw HealthKit time series.
9. Physical iPhone testing with real HealthKit data is available.
10. HealthKit values travel to the local server over the existing trusted-LAN plain-HTTP model;
    no external/cloud fallback.

## 1. Phase 3A in one paragraph

A paired iPhone may optionally read the newest eligible HRV sample and today's resting heart rate
from HealthKit, send those two observations to the existing authenticated local server, and let the
server merge them into readiness with manual precedence. The server stores a small append-only
observation with source/provenance, returns the existing readiness payload plus HealthKit
provenance, and continues to make every readiness/score/training decision. The phone never writes
HealthKit values directly into manual readiness, never computes a score and never changes a
prescription. Permission is optional; manual readiness and the rest of the app work unchanged
without HealthKit.

## 2. Non-goals

- No sleep duration, sleep stages, sleep score or inferred sleep.
- No general heart-rate stream, HRV time series or raw HealthKit sample history.
- No Apple Workout summaries, cardio records, workout effort score or sRPE mapping.
- No HealthKit write, background delivery or observer query.
- No new readiness score, weights, baselines, readiness gates or training rules.
- No automatic import of other readiness fields.
- No health data sent to an external service, LLM or cloud.

## 3. Network, authentication and permissions

- Reuse the Phase 1/2 per-device bearer token and the existing /api/ios/v1/ facade.
- The new route requires Bearer authentication and a UUID Idempotency-Key, uses the existing
  Phase 2 receipt/replay semantics, and is device-scoped.
- The route is a mutation and therefore returns 503 ios_mutations_disabled when
  mutations_enabled is false in config/ios.v1.yaml.
- HealthKit access is read-only and requested only after the owner enables the feature. The app
  must continue to support manual readiness and the complete workout flow with HealthKit disabled
  or denied.
- No HealthKit permission is required for pairing, manual readiness, prescription, workout,
  completion or Progress.
- Update NSHealthShareUsageDescription to explain the two read types and that data stays on the
  owner's local server. Do not request HealthKit write access.

## 4. Server data model — migration 0054_healthkit_readiness.sql

Additive only. Existing readiness_day, readiness_entry, readiness scoring, prescriptions,
workouts, sessions and review tables are untouched.

    CREATE TABLE healthkit_readiness (
        observation_id  TEXT PRIMARY KEY,              -- uuid4 hex
        device_id       TEXT NOT NULL REFERENCES ios_device(device_id),
        on_date          TEXT NOT NULL,                -- server-local YYYY-MM-DD
        field            TEXT NOT NULL CHECK (field IN ('hrv_ms', 'rhr_bpm')),
        value            REAL NOT NULL CHECK (value > 0),
        sample_id        TEXT NOT NULL,                -- HealthKit object UUID
        sample_at        TEXT NOT NULL,                -- ISO-8601 with offset
        source_name      TEXT NOT NULL,                -- e.g. Apple Watch
        source_bundle_id TEXT,                         -- optional
        imported_at      TEXT NOT NULL,                -- UTC ISO-8601
        UNIQUE (device_id, field, sample_id)
    );

    CREATE INDEX idx_healthkit_readiness_date
        ON healthkit_readiness(on_date, field, sample_at);
    CREATE INDEX idx_healthkit_readiness_device
        ON healthkit_readiness(device_id, on_date);
    -- Append-only triggers: reject UPDATE and DELETE, matching readiness_entry.

- One row per selected field observation, not a raw time series.
- Multiple observations may be retained append-only for provenance. The effective value for a
  field/date is the latest by sample_at, then imported_at, then observation_id.
- A later HealthKit import never overwrites a manual readiness entry; the merge is per field.
- No schema change to readiness_entry is required. HealthKit is a distinct source.
- Migration rollback: drop the table and the matching 0054 schema_migration row together. The
  paired statement is added to IOS-CLIENT-PLAN.md section 13.2 when implemented.

## 5. Merge and scoring semantics

The server must merge with this per-field precedence:

    manual/preset (readiness_entry) > healthkit (latest) > imported (readiness_day)

- The merge must be shared by readiness_day, readiness_series and readiness_history so scoring and
  HRV/RHR baseline eligibility see the same values. Do not update only the Today payload.
- readiness_day is still the imported CSV layer; manual/preset entries still win over HealthKit.
  A later HealthKit refresh cannot replace a manual value.
- Return the existing sources map with healthkit added as a possible source, plus a separate
  healthkit provenance map described in section 6.3.
- Use the existing readiness_utils.validate rules for hrv_ms and rhr_bpm (finite, positive). Do not
  invent a new scale, normalize the value or convert units.
- Do not infer sleep, energy, mood, soreness or stress. A day with only HRV/RHR retains the
  existing readiness status/score behavior; if the existing rules say unknown/insufficient, that
  remains the result.
- Existing weights, baselines, minimum readings, readiness gates and prescription decisions are
  unchanged.

## 6. Server API

### 6.1 Route

    POST /api/ios/v1/healthkit/readiness

Authentication: Bearer. Required header: Idempotency-Key: UUID. Device-scoped.

The route is available only when mutations_enabled is true. bootstrap capabilities include
healthkit_readiness: true in that case; healthkit remains false because Phase 3B is not built.
When mutations are disabled, healthkit_readiness is false and the route returns
503 ios_mutations_disabled.

### 6.2 Request

    {
      "date": "2026-11-08",
      "samples": [
        {
          "field": "hrv_ms",
          "value": 55.0,
          "sample_id": "4A5B...",
          "sample_at": "2026-11-08T06:30:00Z",
          "source_name": "Apple Watch",
          "source_bundle_id": "com.apple.health"
        },
        {
          "field": "rhr_bpm",
          "value": 52.0,
          "sample_id": "9C1D...",
          "sample_at": "2026-11-08T06:45:00Z",
          "source_name": "Apple Watch",
          "source_bundle_id": "com.apple.health"
        }
      ]
    }

- date is required and must equal the server-local current date. Historical/future dates are
  rejected; Phase 3A does not backfill.
- samples has one or two entries, one per field, both optional individually but at least one.
  Unknown fields, duplicate fields, an empty list or extra keys are rejected.
- value must be finite and greater than zero. Reject NaN, infinity, zero and negative values.
- sample_id is the HealthKit object UUID string, required, 1-128 characters. It must be unique
  per device and field.
- sample_at is required ISO-8601 with an offset. It must not be more than five minutes in the
  future. HRV must be no older than 48 hours at request time. RHR must fall on the supplied
  server-local date.
- source_name is required, trimmed, 1-128 characters. source_bundle_id is optional, 1-200
  characters. They are provenance only; the server does not treat source_name as a clinical
  guarantee.
- Same device+field+sample_id with the same value is an idempotent no-op. Same identifier with a
  different value returns 409 healthkit_sample_conflict. An entire request is atomic: a conflict
  or validation failure inserts nothing.

### 6.3 Response

Return the existing readiness payload from GET /api/ios/v1/today readiness, plus:

    {
      "healthkit": {
        "hrv_ms": {
          "value": 55.0,
          "sample_id": "4A5B...",
          "sample_at": "2026-11-08T06:30:00Z",
          "source_name": "Apple Watch",
          "source_bundle_id": "com.apple.health",
          "imported_at": "2026-11-08T07:00:00+00:00"
        },
        "rhr_bpm": { "...": "same shape" }
      }
    }

- healthkit contains only the selected/latest observations for fields with an accepted sample.
- sources continues to label the effective field source; manual wins when present.
- The normal readiness status/score fields remain; importing HRV/RHR alone does not fabricate a
  ready score.
- The response is stored in the Phase 2 idempotency receipt. Retrying the same key/body replays it
  with Idempotent-Replay: true.
- Error envelope and codes: 400 validation_failed/unknown_field, 401/403 auth, 409
  idempotency_conflict or healthkit_sample_conflict, 503 ios_mutations_disabled. Details never
  contain tokens or raw HealthKit history.

## 7. Client HealthKit behavior

### 7.1 Opt-in and permission

- Add a Settings toggle, HealthKit readiness, default off. Persist the choice in UserDefaults.
- Request read authorization only when the owner turns it on, for exactly:
  HeartRateVariabilitySDNN and RestingHeartRate.
- No write authorization. Do not request sleep, workouts, heart rate, respiratory or other types.
- If HealthKit is unavailable, permission is denied or no sample exists, show a clear status;
  never use zero and never block manual readiness.
- Keep an explicit Import from HealthKit action on Today/Readiness while enabled. Also attempt an
  import on app open/refresh while enabled. No background delivery, HKObserverQuery or periodic
  background task.

### 7.2 Sample selection

Use a testable HealthKitReadinessProviding protocol; production uses HKHealthStore.

- HRV: eligible samples are finite, >0, with sample time in [now - 48 hours, now + 5 minutes].
  Prefer samples whose source identifies Apple Watch; otherwise use all eligible sources. Choose
  the newest eligible sample (endDate, then startDate), and use its UUID, end/start timestamp and
  source.
- RHR: eligible samples are finite, >0, for the current server-local date. Prefer Apple Watch;
  otherwise use the newest eligible sample. Use the sample's end timestamp as sample_at.
- Client sends at most one HRV and one RHR. If neither exists, make no request and show No
  HealthKit sample. Never send a synthetic/zero value.
- Use the server date from bootstrap/today as date. Convert sample timestamps to ISO-8601 with
  offset. If the phone and server are in different time zones, the server remains authoritative
  and may reject the date; the UI must show that result without silently changing the date.
- Manual readiness remains the owner's action. Never copy HealthKit values into the manual form.

### 7.3 Import and display

- POST to /api/ios/v1/healthkit/readiness with a UUID Idempotency-Key. Add a MutationKind
  healthkitReadiness so the R1 journal and same-key retry rules apply.
- On success, refresh Today so the readiness payload, sources and healthkit provenance are shown.
- Show HRV/RHR value, source, sample age and selected/unselected status. When manual wins, say so
  and keep the HealthKit provenance visible as an observation.
- Distinguish Not authorized, No sample, and Stale sample; do not present any as zero.
- Do not run HealthKit reads when the toggle is off. Do not request permission at app launch unless
  the owner has enabled the feature and permission has not yet been requested.

## 8. Tests

Server contract tests:

- Migration creates the append-only healthkit_readiness table and indexes.
- Valid HRV-only, RHR-only and both-field imports return the readiness payload and provenance.
- Idempotency replay; same sample no-op; same sample different value conflict; atomic rollback.
- Reject wrong date, stale HRV (>48h), future timestamp (>5m), wrong RHR date, nonfinite/zero/
  negative values, unknown/duplicate fields, oversized source fields.
- Device scoping and revoked-device behavior.
- Merge precedence: imported < HealthKit < manual; later HealthKit does not overwrite manual;
  preset/manual behavior remains.
- readiness_series/readiness_history include HealthKit values for scoring/baseline eligibility.
- Existing score weights/gates unchanged; no subjective fields inferred.
- Capability true/false and 503 with mutations disabled.
- No sleep/workout/effort route or field is added.

Client tests:

- Fake HealthKit provider: newest HRV within 48h, stale excluded, RHR current-day selection,
  Apple Watch preference, no-sample and unauthorized states.
- Payload encoding, date, HKSample UUID/source fields and Idempotency-Key.
- Toggle default off; permission requested only after enabling; manual readiness still works when
  denied/unavailable.
- R1 journal captures the import and replays it with the original UUID/body.
- Today/Readiness display source, sample age and manual precedence.

Acceptance:

- Toggle off: no HealthKit prompt, no reads, manual readiness unchanged.
- Enable with data: HRV/RHR import, source/freshness display, existing readiness score sees the
  values under the existing rules.
- Manual entry after import remains selected after a later HealthKit refresh.
- Denied/empty/stale data stays unknown; no zero or inferred values.
- No sleep/workout data requested or consumed.
- Simulator tests use the fake provider; physical iPhone acceptance uses real HealthKit data and a
  temporary SQLite database. Never test against live data/coach.db except the owner's existing
  backup discipline.

## 9. Rollback

- Turn the client toggle off and remove the HealthKit importer/UI; no server change is required
  and manual readiness remains.
- Remove the POST route and healthkit_readiness capability.
- With the server stopped and a verified backup, drop healthkit_readiness and delete the matching
  0054 schema_migration row together. Do not drop or rewrite readiness_entry, readiness_day,
  prescriptions, workouts or sessions.
- Revoke HealthKit permission on the phone if desired. No external data exists.
- Because no existing table is altered, rolling back restores the pre-Phase-3A readiness behavior
  once HealthKit observations are gone.

## 10. Limitations and deferred work

- Permission denial and no sample are not distinguishable as a clinical fact; the UI reports
  authorization separately from missing data.
- HealthKit source/device metadata is provenance, not a measurement guarantee.
- Phase 3A does not reconcile sample deletion/update, historical backfill, sleep, workouts,
  cardio, Apple effort/sRPE or raw time series.
- Phone/server timezone differences can cause a date rejection; the server date remains
  authoritative.
- Plain HTTP on the trusted home LAN only, consistent with the existing deployment.

## 11. References

- IOS-CLIENT-PLAN.md section 4 (Phase 3A scope), section 10 (risks) and section 13 (rollback).
- docs/READINESS.md, docs/READINESS-SCORE.md, docs/LIFT-READINESS.md, docs/DATA-MODEL.md.
- docs/API.md for the authenticated facade and idempotency contract.
- IOS-PHASE-2-CONTRACT.md for bearer/receipt/error conventions.
