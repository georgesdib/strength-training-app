# iOS Phase 6 — watchOS companion contract

**Status:** planned, not started (decisions locked 2026-11-09). This document authorises no code.
The phone remains the planner; the watch becomes the client that executes a session.

## 1. Purpose

The watch fetches the server-issued plan, starts the workout, logs sets and rest, shows heart
rate, finishes with sRPE, and writes one HealthKit strength workout. The phone keeps readiness,
prescription requests and plan edits, and shows a read-only mirror while the watch owns the
session.

## 2. Scope

- A watch app target in the `StrengthApp` repository, sharing a Swift package with the iPhone app.
- Its own paired server device and bearer token, minted by the phone and handed over once.
- Plan fetch and start from the watch, within the existing issued-plan rules.
- Set logging, rest timer, form rating and finish with sRPE on the watch.
- Execution telemetry (rest and set events with their original `occurred_at`) so the server
  timeline keeps the times the user acted, not the replay times.
- Offline-safe logging: every mutation is persisted locally before the network call and replayed
  in order; start and plan fetch still require connectivity.
- Heart rate during the session and one `traditionalStrengthTraining` HealthKit workout with
  heart rate, active energy and the effort rating derived from sRPE.
- Plan-revision propagation so a substitution made on the phone reaches the watch without
  disturbing a set in progress.
- A phone mirror mode for a watch-owned session: plan edits allowed, set logging blocked and a
  take-over action available.
- Idle detection and automatic abandonment of forgotten sessions.

## 3. Non-goals

No readiness entry, prescription request, history, progress, settings or exercise library on the
watch. No heart-rate zones, no Shortcuts automation, no Apple Intelligence/PCC, no complications,
no watch-side pairing UI, no cellular or away-server support, and no second HealthKit writer on
the phone. The watch is a home-gym device on the same LAN as the server.

The watch does not notify the phone: there is no watch→phone event channel and no attempt to
auto-open the phone app. The phone discovers a watch-started session through its normal foreground
refresh, and watch→phone WatchConnectivity is not part of this plan.

## 4. Locked decisions

| # | Decision |
|---|---|
| D1 | The watch is its own server device (`kind = watch`), with its own token and independent revocation. |
| D2 | Plan fetch and start require connectivity; logging and finish work offline and replay. |
| D3 | During a watch session the watch is the only set writer. The phone may edit the plan and mirrors state, but cannot log sets. |
| D4 | iOS and watchOS share a `StrengthCore` Swift package; views stay per-platform. |
| D5 | `issued_plan_ttl_seconds` becomes 14400 (4h). The same-server-date rule is unchanged, so a plan still cannot cross midnight. |
| D6 | Idle warning at 3h without activity; automatic abandonment at 24h. Sets are preserved. |
| D7 | Heart rate is displayed; zones are not. HealthKit is written once, from the watch. |
| D8 | The watch never computes training numbers; it displays server values and sends user input. |

## 5. Shared code

`StrengthCore` is a local Swift package with no UI dependencies:

- `APIModels`, `Phase2Models`, `ExecutionModels` and the JSON value types (moved unchanged).
- `IOSAPIClient` (Foundation + `URLSession`), including the same-origin redirect policy.
- `MutationJournal` / offline capture logic, generalised to a session-scoped outbox.
- The session state machine (plan → start → set/form/finish), extracted from the 2,200-line
  `AppModel` behind a platform-neutral `SessionCore`.
- Display formatting and validation that does not touch UIKit.

Platform services sit behind protocols: `CredentialStore` (Keychain), `RestNotifier`
(iOS local notifications vs watch haptics), `HealthData` (readiness import vs workout write) and
`CompanionLink` (WatchConnectivity on the phone side).

The iPhone app keeps its views and its iOS-only services. The watch app adds `WatchSessionModel`
(HK session, credentials handoff, outbox) around the same core. Avoid `#if os()` inside the core.

## 6. Device identity and credentials

1. The phone, authenticated, calls `POST /api/ios/v1/devices/watch` (body `{"label": "Watch"}`).
   The server revokes any previous non-revoked watch device with the same `parent_device_id`,
   inserts a new `ios_device` row with `kind = 'watch'`, and returns
   `{device_id, label, token}` once. Only the digest is stored.
2. The phone sends `{baseURL, deviceID, token}` through WatchConnectivity
   (`updateApplicationContext`, namespaced key) and repeats it whenever the watch reports missing
   credentials.
3. The watch stores the token in its own Keychain (`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`)
   and the rest in UserDefaults. The token never reaches a log, a file or the server's URL.
4. `GET /api/ios/v1/devices` lists devices for the phone's Settings; `DELETE
   /api/ios/v1/devices/{id}` revokes the watch from the phone or the watch itself. Re-minting is
   the recovery path after a revoke.
5. The watch shows “Open StrengthApp on your iPhone” until credentials arrive. It never falls back
   to a debug or hard-coded token outside `#if DEBUG` simulator test seams.

## 7. Plan availability and start

- `issued_plan_ttl_seconds` changes from 3600 to 14400 in `config/ios.v1.yaml`; validation already
  allows 60–86400. This is a start window, not a workout lifetime.
- The server-date rule stays: a plan whose `for_date` is not today returns `410 plan_expired`.
  Late-night sessions therefore regenerate rather than extend.
- The watch reads `GET /api/ios/v1/plans/current` on launch, on foreground and on **Refresh**. A
  **Retrieve workout** button is just Refresh; it is not the transport.
- `POST /api/ios/v1/workouts` with `issued_plan_id` starts the session and sets
  `owner_device_id` to the calling device. Existing `409 workout_active`, `410 plan_expired`,
  `410 plan_consumed` and `409 plan_not_ready` responses keep their meaning.
- A plan is never pushed from the phone as the source of truth; at most the phone nudges the watch
  to refresh.
- The watch derives a clock offset from the server time in `bootstrap`/`today` and stamps
  `performed_at` and `ended_at` with server-adjusted time. The server rejects a timestamp more
  than a minute in the future, so a fast watch clock must not surface as a server error.

## 8. Ownership

`workout_session.owner_device_id` is set at start:

- **Owner** may add sets, forms and finish/abandon.
- **Non-owner** receives `409 not_owner` for set and finish writes. Plan edits are exempt and
  remain available to the phone (existing R8 rules).
- Workouts with `owner_device_id IS NULL` (legacy rows and pre-upgrade clients) keep today's
  permissive behaviour.
- `POST /api/ios/v1/workouts/{id}/takeover` transfers ownership to the caller and appends an event.
  The phone offers it in mirror mode when the watch is unavailable or the owner wants to log on the
  phone; the watch, on its next refresh, becomes read-only and shows “Logging moved to the phone”.
- The phone opens a watch-owned session in **mirror mode**: the existing active-workout view with
  set, form and finish controls disabled, plan editing enabled, a “Logging on Apple Watch” banner,
  and one **Take over logging** confirmation. The recovery card is labelled “started on Apple
  Watch”.
- Take-over ships in v1 with that button and the endpoint above; a richer hand-back from phone to
  watch is deferred (section 21).
- Abandon is allowed from any authenticated device, so a lost watch cannot strand a workout.

## 9. Plan edits and revision

- Existing plan edits preserve `order_index` and never renumber it, so a set already attributed to
  an item stays valid across a substitution.
- Add `workout_session.plan_revision`, incremented in the same transaction as every plan write
  (swap, add, remove, set-count). `GET .../execution` returns it; every plan-edit response returns
  the new value.
- Propagation: after an edit the phone pushes the new execution payload over WatchConnectivity
  while it is foreground. The watch also refreshes on foreground, after each set and on demand.
- The watch accepts a payload only when `plan_revision` is greater than or equal to its cached
  value; it never applies an older plan. A set in progress is not interrupted: show “Plan updated”,
  apply at the next set.
- Only items with no logged sets are editable (the server already returns `409` after a set).
  Whether the *current* exercise may be swapped before its first set is decided by the existing
  server rule; no new restriction is added.

## 10. Offline capture and replay

- The watch keeps a session store: plan snapshot + revision, workout id, device id, and an ordered
  outbox of pending set/form/finish operations with their idempotency keys and original timestamps.
- Each set carries `performed_at` and each finish `ended_at`, captured when the user acted and
  replayed unchanged. The server computes the duration from `started_at` and `ended_at`; the
  watch never sends a duration.
- Execution events (rest start/end and set events) are queued with their `occurred_at` in the same
  order, so an offline session's timeline keeps its original times.
- Every action is written locally **before** the request; the UI shows “Saved on watch, syncing”
  until the server acknowledges.
- Replay is ordered and bounded, reusing the server's idempotency receipts. A failed operation
  blocks later dependent operations (finish waits for its sets).
- Start and plan fetch are online-only. If the server is unreachable at start, the watch says so
  and offers retry; it does not fabricate a workout id.
- The outbox is per session and is not subject to the phone journal's 16-entry cap; it is bounded
  by storage (target: at least 500 operations) and cleared on acknowledgement.
- Relaunch, crash and background suspension reload the store and resume pending work. The active
  `HKWorkoutSession` is the mechanism that keeps the app running; persistence covers the rest.
- If an offline session outlives the 24h abandonment window (section 11), the replay can hit an
  abandoned workout. v1 surfaces that as a conflict with the preserved sets and does not silently
  recreate the session; a recovery flow is deferred (section 21).

## 11. Idle and stale workouts

- `workout_session.last_activity_at` is updated on start, set, form and plan edit.
- The execution/today payload exposes `stale` and `last_activity_at` when the workout is
  `in_progress` and idle beyond `workout_idle_warn_seconds` (default 10800, 3h).
- At `workout_idle_abandon_seconds` (default 86400, 24h) the next read or start lazily marks the
  workout `abandoned`, sets `ended_at`, appends an `abandon_stale` event and preserves every set.
  Lazy evaluation avoids a scheduler; the operation is idempotent.
- The client shows “Still training? Resume / Abandon” at the warning threshold and explains an
  automatic abandonment when it happens.
- 24h rather than 12h because an offline watch can legitimately hold a session for many hours.

## 12. Heart rate and HealthKit

- The watch starts an `HKWorkoutSession` with `HKLiveWorkoutBuilder` when the user starts the
  session, and ends it with finish or abandon. This is also what keeps the app alive.
- Activity type: `traditionalStrengthTraining`. Collected: heart rate, active energy, duration.
  At finish, the effort rating (1–10) is written from sRPE.
- The watch is the only writer. The phone's HealthKit use stays read-only (readiness import) and
  never saves a workout for the same session.
- Finish saves the HealthKit workout even if the server finish is queued. Abandon discards it.
- The saved workout's start and end are the real session timestamps, not the sync time: a queued
  finish that syncs later still records the real end.
- If HealthKit authorisation is denied or unavailable, the session still works with no HR and no
  saved workout; the UI says so once.
- Heart rate is displayed as BPM (current and session average). Zones are out of scope.

## 13. Watch UI contract

Three vertically paged screens plus the end flow:

1. **Set** — exercise name, “Set n of m”, target load × reps @ RIR, last set, current HR, a large
   **Log set** button, and the rest countdown when resting.
2. **Session** — elapsed time (from the server's `started_at`), sets done/total, tonnage so far,
   average HR, next exercise, and **Refresh**.
3. **Plan** — remaining items, read-only, with a marker when the plan was updated.

- End flow: summary, sRPE picker (Digital Crown, 1–10), **Finish**. Productivity is not captured
  here; it defaults to “not recorded” and stays a phone concern.
- Persistent states: offline banner, pending-sync count, “Plan updated”, “Logging moved to phone”,
  plan-expired/regenerate message.
- No keyboard text entry except an optional short note if it proves necessary; v1 omits notes.
- Always-On dims to the Set screen; no complication.

**Phone mirror.** A watch-owned session opens on the phone in the existing active-workout view with
set, form and finish controls disabled, plan editing enabled, a banner naming the watch, and one
take-over confirmation. No WatchConnectivity message is involved; the phone discovers the session
on its next foreground refresh.

## 14. Server API changes

| Route | Change |
|---|---|
| `POST /api/ios/v1/devices/watch` | New. Phone-authenticated; mints/replaces the watch device and returns the token once. |
| `GET /api/ios/v1/devices` | New. Lists devices with kind, label, created/last-seen/revoked. |
| `DELETE /api/ios/v1/devices/{device_id}` | New. Revokes the watch from phone or itself. |
| `GET /api/ios/v1/plans/current` | Unchanged. |
| `POST /api/ios/v1/workouts` | Sets `owner_device_id`; response includes `owner_device_id`, `plan_revision`, `last_activity_at`. |
| `GET /api/ios/v1/workouts/{id}/execution` | Adds `owner_device_id`, `plan_revision`, `last_activity_at`, `stale`. |
| Existing set/form/finish routes | Owner check (`409 not_owner`), unchanged otherwise. |
| Existing plan-edit routes | Increment `plan_revision`; response returns it. |
| `POST /api/ios/v1/workouts/{id}/takeover` | New. Transfers ownership and appends an event. |
| Existing abandon route | Allowed by any device; records the device. |

`config/ios.v1.yaml` gains `workout_idle_warn_seconds`, `workout_idle_abandon_seconds` and
`watch_enabled` (gates device minting until the watch app ships); all validated with closed
ranges and fail-closed parsing, like the existing TTLs.

## 15. Data model

Migration `0058_watch_companion.sql` (additive, no data rewrite):

- `ios_device.kind TEXT NOT NULL DEFAULT 'phone' CHECK (kind IN ('phone','watch'))`
- `ios_device.parent_device_id TEXT` (nullable; the phone that minted a watch)
- `workout_session.owner_device_id TEXT` (nullable; NULL keeps legacy permissive behaviour)
- `workout_session.plan_revision INTEGER NOT NULL DEFAULT 0`
- `workout_session.last_activity_at TEXT` (backfilled from `started_at`)

Rollback drops the added columns; existing rows and every other table are untouched.

## 16. Failure and recovery matrix

| Situation | Behaviour |
|---|---|
| No watch credentials | “Open StrengthApp on your iPhone”; retry on foreground. |
| Plan not ready | Show status and retry; no local plan generation. |
| Plan expired / wrong date | “Generate a new plan on the phone.” |
| Workout already active | Show recovery: resume, or abandon then start. |
| Token revoked | 401 clears watch credentials; prompt to re-handoff. |
| Set write fails offline | Queued; pending badge; retry with the same key. |
| Finish fails offline | Queued; server still shows in-progress until replay. |
| Phone opens mid-session | Read-only mirror; plan edits allowed. |
| Phone closed when the watch starts | Nothing is signalled; the phone shows the session on its next foreground refresh. |
| Watch stolen/lost | Phone takes over ownership, finishes or abandons; revoke the watch device. |
| Phone substitutes the current exercise | Allowed only before any set; watch applies at next set. |
| Server unreachable at start | Blocking message; no fabricated session. |

## 17. Tests and acceptance

Server (pytest, default suite): TTL 4h boundary, same-date rejection, idle warning and 24h lazy
abandon (idempotent, sets preserved), ownership enforcement and takeover, plan revision increments
and ordering, device mint/replace/revoke, idempotency replay, and rollback of `watch_enabled`.

`StrengthCore` tests: outbox ordering, bounded retry, revision rejection, finish-after-sets,
relaunch recovery.

Client: existing iPhone suite stays green throughout 6.0; the watch scheme builds for a watchOS
simulator in CI; a simulator UI smoke test covers fetch → start → log → finish.

Physical acceptance on the Ultra 4: phone generates a plan, phone app is closed, watch fetches it,
starts, logs at least three sets, phone substitutes an unstarted exercise, watch shows the update,
finish with sRPE, server shows a completed session, HealthKit shows exactly one strength workout
with HR and effort. Repeat once with Wi-Fi disabled after start, then re-enabled before finish.
Start a session and exercise the idle warning with a lowered test threshold or a seeded
`last_activity_at` (a real 3h wait is not an acceptance step); abandon, start another and confirm
no 409.

Additional checks:

- **Clock skew:** with the watch clock set +5 minutes, a set and a finish still succeed because
  timestamps use the server offset.
- **Offline timestamps:** a set logged at T and synced much later is stored at T, and the execution
  timeline shows the original time.
- **Mirror:** a watch-owned session opens on the phone with set logging disabled; an unstarted
  exercise can still be substituted from the phone; the watch shows the update after refresh.
- **Take-over:** the phone takes ownership, logs a set, and the watch becomes read-only on its next
  refresh.
- **HealthKit end date:** the saved workout ends at the real finish even when the server sync was
  queued.

## 18. CI and distribution

Add a watch scheme to the existing `ios-ci` workflow: build the watch app for a watchOS simulator
(resolving a UDID the same way the iPhone job does) and keep unit tests on the iPhone target and
the package. Watch UI tests are not a CI gate in v1. The watch app ships embedded in the iPhone
app; both need signing, and the existing personal-team 7-day signing applies.

## 19. Risks

- WatchConnectivity handoff reliability and re-pairing; mitigate with a visible retry and the phone
  Settings device list.
- LAN-only networking: the watch must be on the same Wi-Fi; cellular cannot reach the server.
- watchOS suspension: only an active `HKWorkoutSession` keeps logging alive; persistence covers
  crashes.
- Project format: `project.xcproj` is Xcode 27's JSON format; adding a watch target is Xcode-driven
  and CI grows accordingly.
- Dual-client edge cases during takeover; the 409 paths must be exercised.
- Offline longer than 24h conflicts with automatic abandonment; documented and deferred.

## 20. Rollback

Set `watch_enabled: false` and stop minting watch devices; the watch app becomes unusable while
the phone is unaffected. Revert `issued_plan_ttl_seconds` and the idle keys in config. Drop
migration 0058 with its paired rollback row if the feature is abandoned before data depends on it.
Ownership enforcement is inert for rows with `owner_device_id IS NULL`.

## 21. Deferred

Recovery of an offline session that outlives the abandonment window; a richer hand-back from phone
to watch after take-over; automatic phone-side surfacing of watch events (there is no
WatchConnectivity event channel); heart-rate zones; Shortcuts automation; complications;
away-server/cellular support; watch-side readiness or history; Apple Intelligence. Each needs a
separate decision.
