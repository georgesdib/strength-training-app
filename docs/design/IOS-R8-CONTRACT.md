# iOS R8 — Active-workout plan editing (add, swap, remove exercise)

**Status:** approved by the owner on 2026-11-08; implementation not started. Documentation only;
no code, route, migration or CLI is created by this document. R8 is not implemented.

**Why R8 exists.** The Phase 2 contract deliberately excluded plan editing: "No plan edits, exercise
swap, set-count change, set update/remove, or load/reps overrides. Those remain web/CLI"
([`IOS-PHASE-2-CONTRACT.md`](IOS-PHASE-2-CONTRACT.md) §9). In practice the owner trains with the
phone in hand, and the web UI already exposes these edits on a live workout through
`strength_coach/workout.py`. R8 brings that existing capability to the phone without giving the
phone any new authority: every edit still runs through the same Python services.

## 1. Scope

In scope, on an **in-progress** workout only:

- **Swap** a plan item's exercise.
- **Add** an exercise to the plan.
- **Remove** an exercise from the plan.
- **Change the set count** of a plan item (same mechanism, smallest of the four).

Out of scope: editing a prescription that has not been started, editing a completed/abandoned
workout, editing loads (see §3), set-level correction or removal (Phase 4), reordering items,
editing a plan from the web-synchronised "plan override" surface beyond what the four operations
do, and any new rubric or scoring behaviour.

## 2. Existing server capability being reused

Nothing here is new domain logic. The services already exist and are already tested:

| Operation | Service | Behaviour |
|---|---|---|
| Swap | `workout.swap_exercise` ([workout.py](../../strength_coach/workout.py) L1075) | Replaces the item's `exercise_id`, records `substitution_for`, **clears the load** with `unknown_load_reason = 'swapped during workout; load not re-solved'`, discards `set_groups` |
| Add | `workout.add_exercise` (L1100) | Rejects a duplicate exercise, clamps `sets` 1–20 and reps 1–50, appends with `added_during_workout: true` |
| Remove | `workout.remove_exercise` (L1135) | Drops the item at `item_index`; positions of later items shift down |
| Sets | `workout.change_sets` (L1149) | Clamps to 1–20, resizes `set_groups` |

All four require `status = 'in_progress'` (they raise unless `_editable`), all four go through
`_write_plan`, which validates the resulting items and then:

1. rewrites `workout_session.plan_modified_json`, and
2. appends a `workout_event` row (`swap_exercise`, `add_exercise`, `remove_exercise`,
   `change_sets`).

`workout_event` is append-only by trigger, so the audit trail of edits is the event log;
`plan_modified_json` is the current editable state.

## 3. The load rule (the one real policy decision)

The phone may **not** supply a load for an added or swapped exercise. A load is a training decision
and Python owns it:

- **Swap:** unchanged — the load is cleared and marked unknown. The phone sends only
  `exercise_id`.
- **Add:** the request accepts `exercise_id`, `sets`, `reps_low`, `reps_high`, `rir_target`
  and nothing else. `load_kg` is **not accepted** (`400 unknown_field`). The server appends the
  item with a null load and `unknown_load_reason = 'added during workout; no load solved'`, mirroring
  the swap wording. This needs a small additive change to `add_exercise` so both paths carry the
  reason.
- The owner enters the actual load when logging the set, which is where a performed load belongs.
  Nothing on the phone invents a prescription load.

If the owner wants a solved load for an added exercise, that is a separate decision (re-solving at
edit time) and is explicitly not part of R8.

## 4. API surface

All routes are under `/api/ios/v1/` and require the bearer token. Mutating routes also require an
`Idempotency-Key` and return the full `workout.get` payload so the client never has to predict the
new plan. The request schemas are closed.

```text
GET  /api/ios/v1/exercises                                      -> {"exercises": [{"id", "display", "pattern"}]}
POST /api/ios/v1/workouts/{id}/plan/items/{item_index}/swap     {"exercise_id": "…"}
POST /api/ios/v1/workouts/{id}/plan/items/{item_index}/remove   {}
POST /api/ios/v1/workouts/{id}/plan/items/{item_index}/sets     {"delta": -1}
POST /api/ios/v1/workouts/{id}/plan/exercises                   {"exercise_id": "…", "sets": 3,
                                                                 "reps_low": 8, "reps_high": 12,
                                                                 "rir_target": 2}
```

Rules:

- `item_index` is positional and shifts after a removal, so every mutating request also carries the
  exercise the client believes is at that index: `{"expected_exercise_id": "…"}`. The server
  compares it with the current item and returns `409 plan_changed` on mismatch, with the fresh
  workout in the body. Without this, two clients (phone plus web) can silently edit the wrong lift.
- `swap` rejects a target exercise that is already in the plan (`409 exercise_already_present`).
  `swap_exercise` does not check this today; the check is added at the service so the web and the
  phone share one rule.
- `remove` is allowed even when sets are already logged for that exercise. Those sets are
  append-only and stay; they simply no longer match a plan item, and the comparison will report the
  item missing. The client must warn before sending: "Remove <lift>? Logged sets are kept."
- `sets` takes a delta of `-1`, `+1` or the set count directly; the service clamps to 1–20.
- Unknown workout → `404 workout_not_found`. Not in progress → `409 workout_not_active`. Unknown
  exercise → `400 validation_failed` (taxonomy lookup), never silently dropped.
- Idempotency uses the existing receipt table: a replayed key returns the stored workout and does
  not apply the edit twice. A different body with the same key is `409 idempotency_conflict`.

## 5. Data effects

- `workout_session.plan_modified_json` — updated in place (the current editable plan).
- `workout_event` — one appended row per edit, with the before/after payload.
- `ios_issued_plan.plan_json` — **never modified**. It remains the server-issued plan the workout
  started from, so "what was prescribed" and "what was performed" stay separately reconstructible.
- No new table, no new column, no migration.

## 6. Client behaviour

- The active-workout screen gains a per-item menu: **Swap exercise**, **Remove**, **Sets −/+**,
  and a plan-level **Add exercise**.
- Exercise choice uses an authenticated read-only catalogue route (`GET /api/ios/v1/exercises`)
  rather than a typed-name-only picker. The phone loads it while online; the catalogue is not a
  promise of offline editing. The server still validates every exercise id.
- If the catalogue request fails, the menu reports the error and does not guess an exercise. A
  typed fallback is not required for the first implementation.
- The app is online-only for R8 edits. The R1 journal makes an attempted edit retry-safe; it is not
  an offline queue and does not permit an edit without the server response.
- Every edit shows a busy state and applies only when the 2xx workout payload returns; on failure the
  previous plan stays on screen with the server's message. No optimistic local plan edits.
- After any edit the client re-renders from the response, which fixes index shifting for free.
- Logged sets are never removed by an edit; the UI states this explicitly on remove.
- An edit is a mutation and therefore uses the R1 journal: an unresolved edit blocks the next
  mutation and replays with the same key.

## 7. Invariants that still hold

- Python remains authoritative for exercises, loads, sets, reps, RIR and validation.
- The phone never sends a replacement plan, a prescription, a load or a plan item array.
- Edits are append-only events plus a mutable working plan; the issued plan is never rewritten.
- The prescription snapshot the workout started from is unchanged, so the rubric and comparison keep
  their meaning.
- No edit can convert a completed session back to in-progress, and no completed session row is
  ever touched.

## 8. Tests

- Server (`tests/test_ios_plan_edits.py`): swap clears load and set_groups and records
  `substitution_for`; add appends with a null load and the unknown reason; remove keeps logged sets;
  set count clamps; `expected_exercise_id` mismatch → 409 `plan_changed`; duplicate swap target →
  409; unknown exercise → 400; not in progress → 409; idempotent replay applies once; `plan_json`
  unchanged; one `workout_event` per edit.
- Client: menu actions build the right bodies; response re-render after a removal keeps the correct
  item; failure leaves the plan untouched; journaling covers edits; no load field is ever sent.
- Existing workout, comparison, history and Phase 2 tests stay green.

## 9. Acceptance

1. On an active workout the owner can swap, add, remove and change set counts from the phone.
2. A swapped or added exercise has no invented load; the reason is visible in the workout payload.
3. Removing an item with logged sets keeps the sets and warns first.
4. A concurrent web edit produces `plan_changed` rather than an edit to the wrong lift.
5. The issued plan JSON is unchanged after editing; the event log shows every edit.
6. Default suite, docs tests and `ruff` pass; the web UI's own editing is unchanged.

## 10. Rollback

- Remove the four routes and the client menu; the server services and the web UI keep their existing
  behaviour.
- No schema change to undo. Workouts edited during the period keep their events and their modified
  plan, which is the intended record.
- No prescription, session or readiness row is touched by enabling or removing R8.

## 11. Decisions taken and remaining open questions

Settled by the owner on 2026-11-08:

1. **Swap to a duplicate exercise:** the `409 exercise_already_present` check goes in the shared
   service, so the web and the phone agree. This is a deliberate web behaviour change: two clients
   disagreeing about whether a lift is on the plan is worse than one extra validation. Recorded as
   `DEC-IOS-05`.
2. **R8 stays a separate item from R7**, because it is a new write surface on a live workout rather
   than a reliability change.

Owner-approved decisions on 2026-11-08:

3. **Authenticated exercise catalogue:** add `GET /api/ios/v1/exercises` for the picker. The phone
   loads it online. No local taxonomy validation beyond the server response.
4. **Online-only edits:** R8 does not add an offline queue. R1 journaling covers attempted edits.
5. **No solved load:** the phone never supplies a load for add/swap, and R8 does not run the load
   solver mid-session.
6. **Order:** R8 follows R7. R7 is closed (2026-11-08), so R8 may start once this contract is
   confirmed.
7. **No reordering:** reordering remains out of scope even though the event log could carry it.

Still deferred:

1. **Adding an exercise with a solved load.** Deferred; needs a separate decision about re-running
   the load solver mid-session.
2. **Reordering items** is not in R8.
