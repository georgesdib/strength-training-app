# Changelog

## [0.3.1] — unreleased

### Added

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
  preview/conflicts/apply/undo, replace matching sets.
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
