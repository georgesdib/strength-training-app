# Changelog

## [0.3.1] — unreleased

### Documented

- Focused spinal-load review: keep the ordinal cap; no load/RIR/set weighting.
- Heavy spinal advisory: RIR ≤ 1 sets on high-fatigue spinal exercises shown as context only.

### Changed

- Replaced the legacy A/B/C session fields and overrides with four canonical session types
  (`squat`, `hinge`, `bench_squat`, `bench_hinge`). Migration 0023 reparses imported sessions
  from their preserved raw exercise composition, leaves unresolved sessions `unknown`, and
  drops `session_day`/`day_guess`. `--day` and `--start-day` are removed; use
  `--session-type`.

### Added

- Minimum effective session (`MOD-MIN-001`): an explicit, volume-only 30/45/60-minute fallback
  that preserves main lifts by default and offers a separate deeper tier. No load/RIR change;
  provenance and UI/CLI controls included.
- UI start-workout now commits the plan as a stored prescription with item and modifier
  provenance in one transaction; the UI prescribe preview remains read-only.
- Readiness feedback: a read-only follow-up of `MOD-FAT-001` reductions from completed workout
  snapshots and CLI modifiers, including planned-versus-actual sets, sRPE, RIR, e1RM and
  7-day symptoms; no tuning.
- Quick readiness presets and display-only context flags, with ordinary `preset` entries and
  an explicit empty-by-default HRV/RHR suppression config.
- High-intensity exposure tracking: tests auto-register a non-volume exposure, near-max
  attempts/competition/unplanned work can be logged, and a conservative recovery guard warns or
  blocks another maximal exposure without changing loads. See `docs/HIGH-INTENSITY-EXPOSURE-PLAN.md`.
- Workout mode foundation: start a workout from a prescription, required pre-workout readiness,
  manual set entry, removable sets, timer, editable measured duration, session RPE, end and
  abandon.
- Workout session/API/UI; a prescription snapshot is frozen at start so later regeneration
  cannot rewrite what was shown.
- Completion materialises workout sets into `session`/`clean_set`, shows actual vs modified
  plan and original prescription, persists the deterministic rubric, and closes the workout
  when review marks are saved.
- In-workout plan overrides: adjust planned sets, swap/add/remove exercises, append-only events.
- In-workout CSV import (paste or file): `Exercise,Set,RPE,Value,Weight,Reps`; RPE→RIR mapping,
  preview/conflicts/apply/undo, replace matching sets, and add recognised new exercises to the plan.
- Inline actual-set edit, review-page planned-vs-actual summary, exercise details popup, and
  partial workout CLI (status/add/update/remove/end/import).

## [0.3.0] — 2026-10-20

### Added

- Retrospective walk-forward validation report
  (`strength-coach validate`, API and Prescribe panel). It is explicitly retrospective, not
  prospective.
- Display-only own-history e1RM context on exercise-selection candidates. It never affects the
  score, ranking, comparability class or prescription.
- Selection A/B/C comparability guard; A applies, B requires confirmation, C is never automatic.
- Readiness volume valve, weekly volume ledger, MRV cap, under-MEV accessory progression.
- Scheduled deload suggestion + automatic reactive deload.
- 50/70/85 warm-up ramp and 10-week 3RM/5RM cadence.
- Readiness score, per-lift readiness, HRV/RHR baselines and e1RM calibration/decay.
- Descriptive progress dashboard and local web coverage for these surfaces.

### Changed / decided

- Strength fatigue model remains **shadow-only**; it lost the retrospective persistence baseline.
- Calibrated continuity remains **rejected**; fixed 14/28/56 bands stay in use.
- No weakness/injury-targeted selection. Injury remains exclusion/penalty/ceiling.
- Strength-programme review closed; future items moved to ROADMAP §4.20.
- Session duration remains manual/optional; no automatic timestamp feature.

### Validation

- 604 tests pass locally, including 15 private integration tests (589 public).
