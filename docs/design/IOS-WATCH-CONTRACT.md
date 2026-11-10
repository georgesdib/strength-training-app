# iOS Phase 6 — watchOS companion contract

**Status:** 6.0 (S1–S4, shared core) complete 2026-11-10; 6.1 and later planned, not started.
Decisions locked 2026-11-09; design remediation 2026-11-09. The extraction authorises no server
migration; no migration is created by this design task. Target platforms: **iOS 27.0** and
**watchOS 27.0**.

## 1. Purpose

The watch fetches the server-issued plan, starts the workout, logs sets and rest, shows heart
rate, finishes with sRPE, and writes exactly one HealthKit strength workout. The phone keeps
readiness, prescription requests and plan edits, and shows a read-only mirror while the watch owns
the session.

## 2. Scope

- A watch app target in the `StrengthApp` repository, sharing a Swift package with the iPhone app.
- Its own paired server device and bearer token, minted by the phone and handed over once.
- A plan carries an explicit execution target (`phone` or `watch`); the server records it and only
  the target device may start it.
- The watch is pinned to the home server: the phone hands over `homeBaseURL` and a monotonic
  `configVersion`, never the phone's currently active Away route.
- Plan fetch and start from the watch, within the existing issued-plan rules. Start is the only
  online gate in v1; everything after it is offline-first.
- Set logging, rest timer, form rating and finish with sRPE on the watch.
- Execution telemetry (rest and set events with their original `occurred_at`) so the server
  timeline keeps the times the user acted, not the replay times.
- Offline-first execution: every mutation is persisted locally before the network call and
  replayed in order; partial flushes are normal. Start and plan fetch still require connectivity in
  v1; the pending-session shell for offline start is deferred (section 21).
- Heart rate during the session and one `traditionalStrengthTraining` HealthKit workout with
  heart rate, active energy and the effort rating derived from sRPE.
- Plan-revision propagation so a substitution made on the phone reaches the watch without
  disturbing a set in progress.
- A phone mirror mode for a watch-owned session: plan edits allowed, set logging blocked and a
  take-over action available.
- Idle detection and automatic abandonment of forgotten sessions. The 24h hard threshold is
  accepted and unchanged.

## 3. Non-goals

No readiness entry, prescription request, history, progress, settings or exercise library on the
watch. No heart-rate zones, no Shortcuts automation, no Apple Intelligence/PCC, no complications,
no watch-side pairing UI, no cellular or away-server support, and no second HealthKit writer on
the phone. The watch is a home-gym device on the same LAN as the server.

The watch does not notify the phone: there is no watch→phone event channel and no attempt to
auto-open the phone app. The phone discovers a watch-started session through its normal foreground
refresh. WatchConnectivity is used only for the phone→watch credential/config handoff and for the
phone→watch plan nudge described in section 10.

No offline start in v1: the watch must reach the server once to start. The pending-session shell
that would make start offline-capable is deferred (section 21). No phone relay in v1 either:
"Send to iPhone" is deferred with the watch-token and idempotency constraints recorded in
section 21. The watch performs no Home/Away switching and never follows the phone's Away route.

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
| D9 | Deployment targets: iOS 27.0 and watchOS 27.0; the package declares both. |
| D10 | A watch session requires an `HKWorkoutSession`. Exactly one HealthKit workout is saved per session, keyed by a stable external UUID; a session with no saved workout is possible only on an unrecoverable HealthKit failure and is reported. |
| D11 | Credential handoff is state, not events: one `updateApplicationContext` payload with a server-issued epoch and an acknowledgement. No queued event copying of tokens. |
| D12 | Plan conflicts never overwrite: the watch applies only equal-or-newer revisions, and a replayed set whose plan item changed is preserved as an off-plan set rather than dropped. |
| D13 | A plan has an `execution_target` (`phone` or `watch`); the server rejects a start from the other kind with `409 wrong_execution_target`. |
| D14 | The watch is pinned to `homeBaseURL`; config changes carry a monotonic `configVersion` and apply only between sessions with an empty outbox. No Home/Away switching. |
| D15 | Offline-first after start: sets, forms, telemetry, finish and HealthKit are local-first; the network is opportunistic and partially flushed. |
| D16 | Post-finish sync is foreground retry on the summary plus sync on next open. The phone relay and offline start are deferred. |

## 5. Platform targets and project shape

- The iPhone app keeps `IPHONEOS_DEPLOYMENT_TARGET = 27.0`; the watch target uses
  `WATCHOS_DEPLOYMENT_TARGET = 27.0`; `StrengthCore` declares `.iOS(.v27), .watchOS(.v27)`.
- One Xcode project (`project.xcproj`, Xcode 27's JSON format), one shared scheme plus a watch
  scheme; the watch app is embedded in the iPhone app.
- No third-party dependencies. The watch app uses the same API base URL and bearer scheme as the
  iPhone.
- CI builds the watch scheme for a watchOS 27.0 simulator; the iPhone suite and the package tests
  remain the test gates.

## 6. StrengthCore extraction

### 6.1 Goal and shape

Move platform-neutral code into a local package without changing iPhone behaviour, then let the
watch consume the same code. One library target (`StrengthCore`) with folder boundaries
(`Models`, `API`, `Session`, `Offline`, `Support`) and one test target. No module-per-type
split and no dependency-injection container.

### 6.2 Boundaries

- Allowed imports: `Foundation`, `Security`. The core has no `SwiftUI`, `UIKit`,
  `WatchKit`, `HealthKit`, `WatchConnectivity`, `UserNotifications`, `AudioToolbox` or
  `Combine`, and no `#if os()`.
- Platform-specific behaviour is injected by the app: rest notifications, HealthKit, Watch
  Connectivity, the credential service/account names and the storage location.
- The API client keeps taking an `IOSSession` (base URL, token, device id); it never reads the
  Keychain itself.
- DTOs stay `Codable` and `Equatable`; request bodies and error mapping do not change.

### 6.3 Staged extraction

Each stage is a separate, reviewable change; the iPhone suite must be green at every stage boundary.

1. **S1 — Models.** `APIModels`, `Phase2Models`, `ExecutionModels`, `JSONValue` and pure
   formatting/validation. Tests move with the code. No behaviour change.
2. **S2 — Networking.** `IOSAPIClient`, the same-origin redirect policy and `APIError` mapping.
   The same requests, headers and retry rules; the existing client tests move and stay green.
3. **S3 — Persistence and credentials.** `MutationJournal`, the offline capture/outbox and
   `KeychainStore` (service and account injected). File formats stay readable by the existing
   data, so an upgrade does not lose a pending operation; the iPhone journal's 16-entry cap and
   conflict behaviour are unchanged.
4. **S4 — Session engine.** Extract the session state machine from the 2,200-line `AppModel` one
   operation at a time, in this order: start, add set, form rating, remove set, finish/abandon,
   plan edit, recovery reconciliation. Each slice introduces a value-type state and an effect enum,
   moves one operation, and changes no view. `AppModel` remains the `ObservableObject` adapter
   that publishes state and executes effects.
5. **S5 — Watch target (moved to 6.2).** Creating the embedded watch app target, scheme,
   deployment target, Info.plist and CI job belongs to 6.2, where credentials and plan fetch give
   it a purpose. It is not part of the 6.0 core extraction.

### 6.4 Acceptance

- Every stage: the existing iPhone unit suite passes with the same test count (tests may move, not
  disappear); the package builds for iOS 27.0 and watchOS 27.0; no view file changes; no API
  payload or header changes; the same server-call order for the same user actions.
- S4 slices additionally prove parity for the moved operation: success, retry, conflict and
  offline paths; if parity cannot be demonstrated, revert that slice only.
- The extraction is complete when the iPhone app no longer owns models, networking, journal or
  session transitions, and the package builds for iOS 27.0 and watchOS 27.0. The watch target
  itself is 6.2.

### 6.5 What not to do

Do not rewrite `AppModel` wholesale, move views into the package, add generic repositories or
use-case layers, change the public surface the views bind to, or change a server contract as part
of the extraction.

## 7. Credential handoff

### 7.1 Device model

- `ios_device` gains `kind` (`phone`/`watch`), `parent_device_id` (the minting phone) and
  `credential_epoch` (server-issued integer, incremented on every mint).
- At most one non-revoked watch per phone, enforced by a partial unique index on
  `(parent_device_id)` where `kind = 'watch' AND revoked_at IS NULL`.

### 7.2 Minting

- The phone calls `POST /api/ios/v1/devices/watch` with `{"label":"Watch"}`. In one
  transaction the server revokes the parent's active watch (if any), inserts the new device with
  `credential_epoch = max(prior epochs for the parent, 0) + 1`, and returns
  `{device_id, label, epoch, token}` once; only the digest is stored.
- Minting is **identity-idempotent**, not receipt-idempotent: a lost response produces a new
  epoch and device, and the previous watch token is revoked. There is never a second active watch
  and no plaintext token is stored for replay. Mint is rate-limited per phone.
- The phone mints only when no active watch exists or the watch reports missing credentials. A
  successful acknowledgement stops all further minting.

### 7.3 Delivery and acknowledgement

- The phone sends one `updateApplicationContext` payload under a versioned key:
  `{schema, epoch, configVersion, homeBaseURL, deviceID, token, issuedAt}`. `homeBaseURL` is the
  Home server, never the phone's active Away route.
- `updateApplicationContext` is asynchronous, coalesced to the latest value and may be delayed
  until the counterpart app runs. The design therefore treats it as latest-wins state, not as a
  message queue.
- The watch accepts a payload only when `epoch` is greater than its stored epoch, validates the
  schema and base URL, writes the token to its Keychain, then acknowledges with a second
  `updateApplicationContext`: `{schema, ackEpoch, configVersion, deviceID, status: "ready"}`.
- A stale or duplicate payload is ignored but acknowledged again with the stored epoch, so a
  delayed delivery cannot roll the watch back.

### 7.4 Retry and foreground recovery

- The phone retries only on a WC activation change, a reachability change, the phone entering the
  foreground, or an explicit `credentialsMissing` request from the watch. At most three attempts
  per foreground session, with 2s/10s/30s backoff; there are no background timers and no tight
  loops.
- On launch/foreground both sides exchange contexts. The phone re-sends when `ackEpoch < epoch`;
  the watch asks again when it has no credentials.
- If the watch reports missing credentials after a send, the phone re-mints (new epoch) rather than
  resending an old token that may never have arrived. The watch accepts the higher epoch.
- A delivered and acknowledged token is never re-sent.

### 7.5 Missing and revoked credentials

- Any `401`/`403` from the server makes the watch wipe its token, mark credentials missing, stop
  retrying API calls, and show “Open StrengthApp on your iPhone”. It retries only on foreground or
  when a new context arrives.
- The phone, on foreground, reads `GET /api/ios/v1/devices`: if the watch is absent or revoked it
  mints; if the watch is active but reports missing credentials it mints a new epoch (rotation).
  Revoking the watch from Settings produces the same path.
- Re-pairing the phone itself does not resurrect a watch token; the phone mints a new watch device
  after its own pairing succeeds.

### 7.6 Security

- The token never appears in a log, error description, analytics event, URL, file, UserDefaults
  value, notification or crash report; `Authorization` headers are redacted in diagnostics.
- Credentials travel only in `updateApplicationContext`. They are never sent through
  `transferUserInfo` or `sendMessage`, which could deliver a stale queued copy.
- The watch stores the token in `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`; the phone holds it
  in memory only until the acknowledgement and then clears it.
- The payload is accepted only from the paired WC session, with a known schema and the same base
  URL validation used by pairing. No debug or hard-coded token exists outside an explicit
  `#if DEBUG` simulator seam.

### 7.7 Handoff failures

| Situation | Behaviour |
|---|---|
| WC not activated / watch not paired | Watch shows the instruction; phone retries on activation. |
| Phone app not running | Context is delivered when it next runs; no background wake is attempted for credentials beyond the OS's own delivery. |
| Delivery delayed | Latest context wins; the epoch guard prevents a rollback. |
| Acknowledgement lost | Phone resends the same epoch; the watch ignores and re-acks. |
| Token revoked mid-session | Watch wipes on 401, pauses API calls, requests credentials; queued local operations remain. |
| Duplicate mint attempt | Partial unique index plus revoke-on-mint; no second active watch device. |

### 7.8 Home server and config refresh

- The watch is pinned to the phone's Home server for its whole lifetime. The payload carries
  `homeBaseURL`; the Away URL is never sent and the watch never probes or switches routes.
- `configVersion` is a phone-local monotonic integer, independent of `credentialEpoch`. Saving a new
  home address or changing the reachability preference that selects it increments it.
- The watch accepts a newer `configVersion` only when it has **no active session and an empty
  outbox**. Applying a new base URL while queued operations exist would leave them pointing at the
  old server, where their idempotency receipts live; the watch therefore defers the change.
- If the home URL changes while queued operations target the old URL, the watch flushes them to the
  old URL first. If that is impossible it surfaces a conflict and keeps the old URL; it never
  silently retargets the queue.
- Reachability failures mean **offline**, never “switch server”. Cellular availability does not make
  the home LAN reachable.

## 8. Plan availability and start

- `issued_plan_ttl_seconds` changes from 3600 to 14400 in `config/ios.v1.yaml`; validation
  already allows 60–86400. This is a start window, not a workout lifetime.
- The server-date rule stays: a plan whose `for_date` is not today returns `410 plan_expired`.
  Late-night sessions regenerate rather than extend.
- The plan request carries `execution_target: "phone" | "watch"`. The server stores it on the
  issued plan and returns it from `GET /api/ios/v1/plans/current`; only a device of the matching
  kind may start it. A phone start of a watch-targeted plan, or the reverse, returns
  `409 wrong_execution_target`. This is the “plan for the watch” option.
- The watch reads `GET /api/ios/v1/plans/current` on launch, on foreground and on **Refresh**.
  **Retrieve workout** is Refresh, not a transport.
- `POST /api/ios/v1/workouts` with `issued_plan_id` starts the session and sets
  `owner_device_id` to the calling device. A retried start with the same plan returns the
  existing in-progress workout; the existing `409 workout_active`, `410 plan_expired`,
  `410 plan_consumed` and `409 plan_not_ready` responses keep their meaning.
- Start is the only online gate in v1. If the watch cannot reach the home server it shows “connect
  to home Wi-Fi”, retries within the plan TTL, and does not fabricate a session. Offline start via a
  pending-session shell is deferred (section 21).
- The watch must have HealthKit workout authorisation before it starts (section 11). If it does
  not, it explains why and offers to log on the phone instead.
- The watch derives a clock offset from the server time in `bootstrap`/`today` and stamps
  `performed_at` and `ended_at` with server-adjusted time. The server rejects a timestamp more
  than a minute in the future, so a fast watch clock must not surface as a server error.

## 9. Ownership and phone mirror

`workout_session.owner_device_id` is set at start:

- **Owner** may add sets, forms and finish/abandon.
- **Non-owner** receives `409 not_owner` for set and finish writes. Plan edits are exempt and
  remain available to the phone (existing R8 rules).
- Workouts with `owner_device_id IS NULL` (legacy rows and pre-upgrade clients) keep today's
  permissive behaviour.
- `POST /api/ios/v1/workouts/{id}/takeover` transfers ownership to the caller and appends an
  event. The phone offers it in mirror mode when the watch is unavailable or the owner wants to
  log on the phone; the watch, on its next refresh, becomes read-only and shows “Logging moved to
  the phone”.
- The phone opens a watch-owned session in **mirror mode**: the existing active-workout view with
  set, form and finish controls disabled, plan editing enabled, a “Logging on Apple Watch” banner,
  and one **Take over logging** confirmation. The recovery card is labelled “started on Apple
  Watch”.
- Take-over ships in v1 with that button and the endpoint; a richer hand-back from phone to watch
  is deferred (section 21).
- Abandon is allowed from any authenticated device, so a lost watch cannot strand a workout.

## 10. Plan revision and offline conflicts

### 10.1 Revision contract

- Every plan write (swap, add, remove, set-count) increments
  `workout_session.plan_revision` in the same transaction and returns the new value.
  `GET .../execution` returns it with the plan.
- The watch stores the revision with its snapshot and never writes plan content.

### 10.2 Propagation

- After an edit the phone, while foreground, sends the new execution payload to the watch over
  WatchConnectivity (`updateApplicationContext`, latest-wins). This is a nudge, not the source of
  truth: the watch also refreshes on foreground, after each set and on demand.
- The payload carries `plan_revision`; the watch applies it only when it is equal to or newer than
  its snapshot, and only at an idle point (10.4).

### 10.3 Reconnect order

When the watch regains connectivity with pending work:

1. Flush pending set/form/telemetry operations in their original order, each with its original
   idempotency key and timestamps.
2. Fetch `GET .../execution`.
3. If the fetched revision is newer, replace the local snapshot and its revision.
4. Resume the UI on the new snapshot. A newer plan is never applied before the pending sets are
   flushed.

### 10.4 Mismatch policy

- A replayed set carries the `exercise_id` actually performed and the `plan_item_index` it was
  logged against. If the phone swapped that item while the watch was offline, the server rejects
  the set with `409 plan_item_mismatch` rather than silently attributing it to the new exercise.
- The client then retries once with `plan_item_index = null` (an off-plan set) keeping the
  original exercise, load, reps, RIR, `performed_at` and idempotency-derived identity. The set
  is preserved, volume still counts by exercise, and the session summary and telemetry record a
  visible “plan changed while offline” note. The original `plan_item_index` is retained in the
  telemetry event as provenance, so the performed plan item is not lost even though the accounting
  link is cleared.
- This is automatic data preservation, not a silent reinterpretation: the user sees the note, and
  the plan is not rewritten to make the set fit.

### 10.5 Stale snapshots and in-progress input

- The watch applies a payload only when its revision is greater than or equal to the cached one;
  an older or delayed payload is ignored. A stale snapshot can never overwrite a newer revision
  because the watch never writes plans.
- A plan update arriving while the user is entering a set is deferred until that entry is
  committed or cancelled; it is not allowed to change the target under the user's fingers.
- If the current item is swapped before any set is captured, the watch updates the label at the
  next idle point. If a set was captured, that set keeps its performed exercise and the mismatch
  policy applies on replay.

### 10.6 Phone edits while the watch is offline

Phone edits remain allowed, subject to the existing rule that an item with a logged set on the
server cannot be swapped. The phone cannot see a set the watch has captured but not yet sent, so
it may swap an item the watch has already performed. That is accepted: the replay preserves the
set as off-plan (§10.4) and the revision guard keeps both devices coherent afterwards. There is no
server-side reservation or locking while the watch is offline.

### 10.7 Offline-first execution and network policy

- **Network states:** `unknown`, `online(home)`, `offline`. “Cellular available” is **not** online:
  the server is on the home LAN. The watch does not switch servers or fall back.
- **Start gate:** start needs one successful call to the home server. Without it the watch shows
  “connect to home Wi-Fi”, retries within the plan TTL, and does not fabricate a session. Offline
  start via the pending-session shell is deferred (section 21).
- **Persist first:** after start, every set, form, telemetry event and finish is written to the
  session store before the request. The UI shows captured/pending until acknowledged.
- **Partial flush:** the outbox flushes in order and acknowledges per operation; it stops on the
  first failure and never clears an unacknowledged operation. Reconnecting mid-session and
  flushing a prefix is normal.
- **Retry:** on failure wait 5s, 15s, 60s, then every 5 minutes; reset on success. Also retry on a
  network-path change and on foreground. No tight polling; the watch is on battery.
- **Finish:** the finish intent and `ended_at` are persisted, HealthKit is saved locally, and the
  server finish is queued. The summary retries while visible; if the app is suspended, the queue
  survives and syncs on next open. There is no guaranteed background sync.
- **Timestamps:** `performed_at` and `ended_at` are captured at action time and replayed unchanged;
  the sync time never replaces them.
- **Config changes** wait until the session is finished, synced and the outbox is empty (7.8).

## 11. Watch execution lifecycle

### 11.1 States

`idle → fetching → ready → starting → active(running/resting) → finishing → finished`, plus
`abandoned` and the recovery states `suspended`, `terminated` and `reconciling`.

### 11.2 HealthKit is the liveness anchor

- The watch starts an `HKWorkoutSession` and `HKLiveWorkoutBuilder` before the active UI is
  shown. This is what keeps the app running when the wrist is lowered or the screen dims.
- HealthKit **workout authorisation is required to start a watch session**. Without it the app
  cannot be relied on to stay alive, so the watch refuses to start and explains the choice
  (enable Health access, or log on the phone). Heart-rate read authorisation is optional: without
  it the session runs and simply shows no HR.
- If a session is somehow running without an HK session, the app treats itself as foreground-only:
  every action is persisted, and the UI says logging may stop when the screen locks.

### 11.3 Lifecycle matrix

| Event | Behaviour |
|---|---|
| Wrist lowered / screen dims | HK session keeps the app alive; timers continue; the UI dims; a tap wakes it. Logging needs no continuous screen. |
| App backgrounded (Digital Crown, another app) | Same as above while the HK session is active; state is persisted on every action. |
| System suspension (no active HK session) | The app may suspend; the session store is authoritative; resume on next activation. |
| System termination / low power / reboot | HK session ends; on relaunch the store and server are reconciled (11.5); the HK workout is recovered per section 12. |
| User force-quits the app | Same as system termination; no workout is finalised unless the finish intent was already persisted. |
| Screen lock / Always-On | The dimmed screen shows the current set; no computation depends on it. |
| Network drops mid-session | The set persists; the outbox flushes what it can on reconnect; no blocking error, retry with backoff. |
| Finish while offline | Finish and `ended_at` persist; HealthKit saves locally; the server finish queues; the summary shows “syncing”. |
| App suspended after finish, before sync | The queue survives; sync runs on next open. No background-sync guarantee. |

### 11.4 Set capture

- **Log set** first performs one atomic local write of the operation (set payload, timestamp,
  idempotency key, plan item attribution) and only then updates the UI to “captured, syncing”.
  The network call is asynchronous and may fail without losing the set.
- A captured set is never re-entered because the screen dimmed, the app backgrounded or the
  network failed; duplicate taps are suppressed by a local operation id plus the server's
  idempotency receipt.
- The rest timer's end date is persisted and recomputed on relaunch; it never depends on the UI
  remaining active.
- The same rule applies to form ratings, finish and telemetry: persist first, then send.

### 11.5 Interrupted-session recovery

On launch, the watch reads its session store and `GET .../execution`:

| Local | Server | Behaviour |
|---|---|---|
| active | in_progress, owner = this watch | Resume: restore the snapshot, restart the HK session, flush pending operations. |
| active | in_progress, owner = phone | Read-only; show “Logging moved to the phone”; offer to clear local state. |
| active with pending finish | completed/abandoned | Flush nothing; show the conflict and the preserved summary; do not recreate the workout. |
| active | no active workout | Show “ended elsewhere”, keep the local summary, offer clear. |
| finishing | in_progress | Resume finalisation: retry the server finish and the HealthKit save (section 12). |
| finished | completed | Clear the store after the summary is acknowledged. |

## 12. HealthKit idempotency and recovery

### 12.1 One workout per session

- At start, generate a `sessionUUID`, persist it **before** starting the HK session, and use it
  as the HK workout metadata external UUID (`HKMetadataKeyExternalUUID`). The workout is
  `traditionalStrengthTraining` with the real start and end dates.
- The phone never saves a workout for the same session; the watch is the only writer.

### 12.2 Finish protocol

1. Persist a finish intent: `{endedAt, sRPE, effort, hkState: pending, serverAcked: false}`.
2. End collection at `ended_at` and call `finishWorkout` on the live builder.
3. On success, persist `hkState: saved`. On failure, leave `pending` and retry on the next
   launch/foreground.
4. Independently enqueue the server finish. A server retry never triggers a second HK save.

### 12.3 Crash and relaunch during finalisation

- On relaunch, first query HealthKit for a workout whose external UUID equals `sessionUUID`. If
  one exists, mark `saved` and do not save again.
- If none exists and the builder survived (same process), retry `finishWorkout`.
- If none exists and the builder is gone (relaunch), rebuild a **minimal** workout from the
  persisted intent with the original start/end and effort, no HR samples, and save it once. If
  HealthKit refuses, mark `unsaved`, show the summary and do not retry indefinitely. Never
  create a second workout.
- If the app relaunched mid-session it starts a new HK session for liveness and the resumed
  segment's HR. That segment is **not** saved as its own workout: at finish the resumed builder is
  discarded and the single minimal workout above is saved with the original start. Crash recovery
  therefore trades HR samples for one workout with truthful timestamps; the summary says so. If a
  workout with the external UUID already exists, the resumed segment is discarded too.
- The external UUID plus the persisted `hkState` are the exactly-once mechanism; the server's
  idempotency is separate and cannot create duplicates in HealthKit.

### 12.4 Permissions

- Workout authorisation is required to start (§11.2). HR read denial only removes the HR display.
- If authorisation is revoked mid-session, HR collection stops; the finish save may fail. The app
  reports it once, keeps the server session intact, and does not retry in a loop.
- Abandon ends the HK session without saving a workout; if a workout was already saved (only
  possible after a finish), it is left as the single saved workout.

## 13. Watch UI contract

Three vertically paged screens plus the end flow:

1. **Set** — exercise name, “Set n of m”, target load × reps @ RIR, last set, current HR, a large
   **Log set** button, and the rest countdown when resting.
2. **Session** — elapsed time (from the server's `started_at`), sets done/total, tonnage so far,
   average HR, next exercise, and **Refresh**.
3. **Plan** — remaining items, read-only, with a marker when the plan was updated.

- End flow: summary, sRPE picker (Digital Crown, 1–10), **Finish**. Productivity is not captured
  here; it defaults to “not recorded” and stays a phone concern.
- Persistent states: offline banner with pending count (“offline · 4 pending”), “Plan updated”,
  “Logging moved to phone”, plan-expired/regenerate, “credentials missing”, “resume session”,
  “finish saved on watch — syncing”.
- The watch never labels itself online because cellular is available; only a successful home-server
  call does. It never offers a server switch.
- After finish the summary stays visible and retries; if it is dismissed or the app suspends, the
  outbox syncs on next open.
- A captured set shows a distinct confirmation before the server acknowledges; the screen never
  claims “saved” on a failed request.
- No keyboard text entry except an optional short note if it proves necessary; v1 omits notes.
- Always-On dims to the Set screen; no complication.

**Phone mirror.** A watch-owned session opens on the phone in the existing active-workout view with
set, form and finish controls disabled, plan editing enabled, a banner naming the watch, and one
take-over confirmation. No watch→phone message is involved; the phone discovers the session on its
next foreground refresh.

## 14. Server API changes

| Route | Change |
|---|---|
| `POST /api/ios/v1/devices/watch` | New. Phone-authenticated; revokes the previous watch, mints a new epoch, returns the token once. |
| `GET /api/ios/v1/devices` | New. Lists devices with kind, label, epoch, created/last-seen/revoked. |
| `DELETE /api/ios/v1/devices/{device_id}` | New. Revokes the watch from phone or itself. |
| `POST /api/ios/v1/prescriptions` | Accepts `execution_target` (`phone` or `watch`) and stores it on the issued plan; absent means `phone` for older clients. |
| `GET /api/ios/v1/plans/current` | Returns `execution_target` with the plan. |
| `POST /api/ios/v1/workouts` | Rejects a start from the wrong device kind with `409 wrong_execution_target`; sets `owner_device_id`; response includes `owner_device_id`, `plan_revision`, `last_activity_at`. |
| `GET /api/ios/v1/workouts/{id}/execution` | Adds `owner_device_id`, `plan_revision`, `last_activity_at`, `stale`. |
| Existing set/form/finish routes | Owner check (`409 not_owner`); a set whose plan item changed returns `409 plan_item_mismatch` with the current item. |
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
- `ios_device.credential_epoch INTEGER NOT NULL DEFAULT 0`
- Partial unique index: one active watch per parent
  (`(parent_device_id) WHERE kind = 'watch' AND revoked_at IS NULL`)
- `ios_issued_plan.execution_target TEXT NOT NULL DEFAULT 'phone' CHECK (execution_target IN ('phone','watch'))`
- `workout_session.owner_device_id TEXT` (nullable; NULL keeps legacy permissive behaviour)
- `workout_session.plan_revision INTEGER NOT NULL DEFAULT 0`
- `workout_session.last_activity_at TEXT` (backfilled from `started_at`)

The `sessionUUID`, `hkState` and the outbox live only in the watch app's local store; the
server stores no HealthKit data. Rollback drops the added columns and index; existing rows and
every other table are untouched.

## 16. Failure and recovery matrix

| Situation | Behaviour |
|---|---|
| No watch credentials | “Open StrengthApp on your iPhone”; retry on foreground; phone re-mints if needed. |
| Credential delivery delayed | Latest context wins; epoch guard; ack retried. |
| Token revoked | 401 wipes the watch token, pauses API calls, shows the instruction; queued local ops stay. |
| Plan not ready | Show status and retry; no local plan generation. |
| Plan expired / wrong date | “Generate a new plan on the phone.” |
| Workout already active | Show recovery: resume, or abandon then start. |
| Set write fails offline | Queued; pending badge; retry with the same key. |
| Finish fails offline | Queued; server still shows in-progress until replay. |
| Phone opens mid-session | Read-only mirror; plan edits allowed. |
| Phone closed when the watch starts | Nothing is signalled; the phone shows the session on its next foreground refresh. |
| Phone swaps an unstarted item offline | Replayed set hits `409 plan_item_mismatch`; preserved as off-plan and flagged. |
| Watch relaunch with pending ops | Store reload, ordered replay, HK recovery; UI shows pending until acked. |
| HealthKit save fails at finish | Retry on launch; if the builder is gone, save the minimal persisted workout once; else report unsaved. |
| Watch stolen/lost | Phone takes over ownership, finishes or abandons; revoke the watch device. |
| Phone substitutes the current exercise | Allowed only before any set; watch applies at the next idle point. |
| Server unreachable at start | Blocking message; retry within the plan TTL; no fabricated session. |
| Wrong execution target | `409 wrong_execution_target`; no state change; the phone must request a plan for its own target. |
| Network drops mid-set | Set persists; partial flush on reconnect; no blocking error; backoff retry. |
| Home URL changes mid-session | Config change deferred until the session is finished, synced and the outbox empty; old-URL operations flush first. |
| Finish while offline | Finish and `ended_at` persist; HealthKit saves locally; server finish queues; summary shows “syncing”. |
| App suspended after finish | Queue survives; sync on next open; no background guarantee. |

## 17. Tests and acceptance

Server (pytest, default suite): TTL 4h boundary, same-date rejection, idle warning and 24h lazy
abandon (idempotent, sets preserved), ownership enforcement and takeover, plan revision increments
and ordering, `plan_item_mismatch` and off-plan retry, device mint/replace/revoke with one active
watch and monotonic epochs, credential epoch in device responses, idempotency replay, target
enforcement (`409 wrong_execution_target` both ways), `execution_target` in `plans/current`, and
rollback of `watch_enabled`.

`StrengthCore` tests: outbox ordering, bounded retry, revision rejection, finish-after-sets,
relaunch recovery, and one parity test per extracted session operation.

Client: the existing iPhone suite stays green throughout 6.0; the watch scheme builds for a
watchOS 27.0 simulator in CI; a simulator UI smoke test covers fetch → start → log → finish.

Required scenario tests (unit/integration where possible, physical where not):

1. **Delayed or failed credential delivery:** context delayed past the first UI render, a lost
   acknowledgement, a stale epoch, and a revoked token; the watch ends ready once, with one active
   device and no duplicate mint.
2. **Relaunch with pending offline mutations:** three queued sets before relaunch, replay in
   order after relaunch, no duplicates, the pending badge clears only after acknowledgement.
3. **Backgrounding and returning during an active workout:** background for several minutes with
   the HK session active, return, log a set, and confirm the rest timer and elapsed time are
   correct.
4. **Phone plan modification while the watch is offline:** swap an unstarted item; on reconnect
   the pending set flushes first, the newer revision then applies, and the watch does not
   interrupt an in-progress entry. If the swap hits the item the offline set was logged against,
   the set is preserved off-plan and its original index is recorded in telemetry.
5. **Stale plan revision rejection:** a delayed R4 payload cannot overwrite a cached R5; an R6
   payload applies.
6. **Take-over and read-only state:** the phone takes ownership, logs a set, and the watch becomes
   read-only; a set write from the watch returns `409 not_owner` and nothing is lost.
7. **HealthKit finish retry without duplication:** simulate a failed `finishWorkout`, a crash
   before the save and a relaunch; exactly one workout with the session's external UUID exists,
   with the real start/end, and the resumed segment is not saved separately.
8. **Clock skew and timestamps:** a watch clock +5 minutes still logs and finishes; an offline set
   captured at T and synced later is stored at T in both the session and the telemetry timeline.
9. **watchOS 27.0 deployment and CI:** `xcodebuild -showBuildSettings` reports
   `WATCHOS_DEPLOYMENT_TARGET = 27.0` for the watch target and
   `IPHONEOS_DEPLOYMENT_TARGET = 27.0` for the app; the CI watch scheme builds on a watchOS 27.0
   simulator.
10. **Execution target:** a watch-targeted plan cannot be started by the phone and a phone-targeted
    plan cannot be started by the watch; both return `409 wrong_execution_target`, and
    `plans/current` reports the target.
11. **Patchy Wi-Fi:** drop the network several times mid-session; each drop queues, each return
    partially flushes, and no operation is cleared before acknowledgement. Finish offline, reconnect
    two minutes later, and confirm the server matches the watch: same sets, same timestamps, one
    finish, no duplicates.
12. **Home config refresh:** change the home URL while no session is active and the outbox is empty;
    the watch applies the new `configVersion` and keeps its token. With an active session or
    queued operations, the change is deferred and the old-URL queue flushes first. The watch never
    follows the phone's Away route.

Physical acceptance on the Ultra 4: phone plan (watch target) → phone app closed → watch fetch →
start → sets → phone substitution → watch update → finish with sRPE → server completed → exactly
one HealthKit workout with HR and effort. Repeat with the network dropped repeatedly during the
session and re-enabled only after finish: the session must sync, timestamps must stay at the times
the sets were logged, and a suspended app must sync on next open. Exercise the idle warning with a lowered test threshold or a seeded `last_activity_at`
(a real 3h wait is not an acceptance step); abandon, start another and confirm no 409.

## 18. CI and distribution

- Add a watch scheme to the existing `ios-ci` workflow: build the watch app for a watchOS 27.0
  simulator, resolving a UDID the same way the iPhone job does, and keep unit tests on the iPhone
  target and the package.
- Assert the deployment targets in CI with `xcodebuild -showBuildSettings` so a future target
  bump cannot silently break the 27.0 baseline.
- Watch UI tests are not a CI gate in v1. The watch app ships embedded in the iPhone app; both
  need signing, and the existing personal-team 7-day signing applies.

## 19. Risks

- WatchConnectivity handoff latency and the absence of any guaranteed background wake; the epoch
  and ack design tolerates delay but not a phone that is never opened.
- LAN-only networking: the watch must be on the same Wi-Fi; cellular cannot reach the server and
  is not treated as online.
- watchOS suspension: logging depends on the HK session; persistence covers crashes but not user
  force-quits during finalisation. After finish, sync needs the app to run again; the deferred
  phone relay is the only answer for a watch that never opens at home.
- Start needs one moment of home connectivity; the deferred pending-session shell is the only way
  to remove that gate.
- Target enforcement must be right: a phone start of a watch plan, or the reverse, would create a
  session the other device cannot log into.
- HealthKit finalisation across a crash: the backdated minimal-workout fallback needs a spike
  (§22) and may be the only path to exactly one workout.
- `AppModel` extraction is the largest refactor; a slice that cannot prove parity is reverted
  rather than forced through.
- Offline plan mismatch is accepted data loss of *plan attribution*, never of the set itself.
- Project format: `project.xcproj` is Xcode 27's JSON format; adding a watch target and scheme is
  Xcode-driven and CI grows accordingly.

## 20. Rollback

- Set `watch_enabled: false` and stop minting watch devices; the watch app becomes unusable and
  the phone is unaffected. Revert `issued_plan_ttl_seconds` and the idle keys.
- Drop migration 0058 with its paired rollback row if the feature is abandoned before data depends
  on it. Ownership enforcement is inert for rows with `owner_device_id IS NULL`.
- Each `StrengthCore` stage is independently revertible; reverting S1–S4 restores the app to its
  current structure without touching server data.

## 21. Deferred

**Pending-session shell / offline start.** Create a shell at plan time (or on an explicit prepare)
with `{shell_id, issued_plan_id, intended_device_id, start_expires_at}`, let the watch start
against it offline with a client `started_at`, and convert it to a workout on sync. Needs a new
state/table, expiry cleanup, target/conflict rules and a client-timestamp policy.

**Phone relay — “Send to iPhone”.** The phone replays the watch's exact queued bodies using the
watch token over WatchConnectivity, so the server sees the same `device_id` and
`(device_id, operation_id)` receipts dedupe; ownership and provenance stay with the watch. Needs
the token handoff, a relay envelope, per-operation acknowledgement and a partial-relay recovery
path, and cannot be relied on while the watch app is suspended. Takeover is not a substitute: its
receipts are phone-device-scoped, so a later watch retry could duplicate.

Recovery of an offline session that outlives the abandonment window; a richer hand-back from phone
to watch after take-over; automatic phone-side surfacing of watch events (there is no
WatchConnectivity event channel); heart-rate zones; Shortcuts automation; complications;
away-server/cellular support and watch-side Home/Away switching; watch-side readiness or history;
Apple Intelligence. Each needs a separate decision.

## 22. Validation spikes before implementation

These are technical proofs, not open design decisions; they run before the corresponding work
package and do not change the decisions above.

1. **WatchConnectivity (before 6.2):** measure `updateApplicationContext` delivery when the
   counterpart is backgrounded, killed and relaunched; confirm the epoch/ack loop converges, that
   no duplicate watch device is minted across a lost response, and that a `configVersion` change
   arriving mid-session is deferred rather than applied to a non-empty outbox.
2. **HealthKit (before 6.5):** confirm a minimal workout can be saved after relaunch with the
   original start date (backdated `beginCollection`), that a metadata UUID can be queried, and
   that a failed `finishWorkout` followed by a retry yields exactly one workout.
3. **Toolchain (before 6.2):** confirm the GitHub `xcode-27` image builds a watchOS 27.0
  simulator target and reports the deployment targets through `showBuildSettings`.
