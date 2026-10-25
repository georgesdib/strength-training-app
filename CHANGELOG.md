# Changelog

## [0.3.1] — unreleased

### Added

- Dark mode with System / Light / Dark selection on the Settings page; stored per browser.
- History page with paginated sessions and append-only correction of completed/imported
  sessions; edits supersede old sets, rebuild totals/critique and mark re-review.
- Whole-session void/unvoid (audited, excluded from metrics/calibration) and set/rep VBT overrides.
- Evidence review for top set + back-off sets: no direct trial against the current programme;
  no change recommended.
- Optional per-rep velocity CSV in Workout mode, joined to set-level rows by exercise + set;
  append-only rep detail, per-set first/last/loss display, a descriptive `/api/rep-velocity`
  session report and a stratified `/api/rep-velocity/analysis` report. Missing table leaves the
  existing import unchanged. Evidence review: descriptive only, no RIR or injury prediction.
- Explicit `spinal_cost` for every high-fatigue entity; `single_leg_db_rdl` documented as
  non-counting; at-cap/headroom display in prescriptions. Cap unchanged.

### Fixed

- Added a partial index on `clean_set(supersedes_id)`; the append-only leaf lookup was
  O(n²) and made Today, Review, rubric calibration and Athlete-state requests slow after
  history growth.
- Readiness saves now accept the optional `wearable_score` (migration 0029) and are
  all-or-nothing, so a rejected field cannot leave a partial readiness day.
- Workout materialisation now classifies added bodyweight load through the domain resolver and
  derives session main lifts from actual sets; incomplete workouts carry a flag. Single-set
  e1RM sources emit a confidence warning.

### Added

- Read-only regime-change check: `regime` CLI, `/api/regime` and Prescribe panel for a main
  lift collapsing while a same-category substitute rises.
- Web **Settings** tab: enable/disable and configure the local LLM (write-only key), browser-only
  Prescribe defaults, and read-only app paths. New `/api/settings` endpoints.
- Rubric 1.1.0 scores measured live-workout duration; imported sessions remain
  unmeasurable. Prescription items expose `e1rm_source_sets` (migration 0027).

### Changed

- Save/review/workout actions now show a non-blocking toast confirmation; End review
  also disables the button while saving.
- Programme copy no longer mentions legacy A/B/C; the exercise catalogue table now fits its
  panel with fixed columns and a responsive narrow layout.
- Minimum-session target and deeper-tier controls are hidden until the mode is ticked, with
  an explanatory note; load/RIR behaviour unchanged.
- Evidence labels in the UI: e1RM estimate, readiness heuristic, configurable volume
  landmarks, ordinal spinal cap, weak deload evidence and heuristic minimum session.

### Added

- W5 read-only prospective review: `prospective` CLI, `/api/prospective` and Outcomes panel
  with stable-lift status, attendance, work completion, RIR, duration and flags.

### Documented

- Corrected the `metric_definition` claim: it supports measurements, not a live
  readiness composite; dynamic readiness metrics still need code/config work.
- Engine audit W0–W12 closed; implemented fixes, deferred policy choices and 36 open
  limitations consolidated.
- W11/W12 closeout: one test-count source, duration wording, public-data inventory,
  exact sample counts generalised and Git-history decision recorded.
- W10 age-in-state audit: optional `birth_year` proposal, age-conditional wording and no
  age-based load rule.
- W8 volume-balance audit: current 57-set split, spinal/time accounting and four
  options; no change.
- W5 prospective evaluation protocol: stable-lift e1RM, attendance, planned-vs-completed,
  RIR, duration, symptoms and sRPE definitions; no model or policy change.
- W4 programme-evidence audit: rule classes, confidence, qualified claims and no new model.
- Limitations register indexing all open, mitigated and accepted audit limitations.
- W2 load-lineage audit: bodyweight added-load misclassification, incomplete-workout
  provenance and e1RM coverage gaps.
- W9 spinal-cap audit: zero-headroom normal week, exact-cap trigger behaviour, missing
  high-fatigue costs and cap/headroom options.
- W1/W7 attendance audit and implementation: schedule simulations, shared attendance summary,
  Today/Outcomes display, forecast-deload fix and session-time cap.
- W0 execution-path map: complete flow, modifier ownership/order, input risks, test
  coverage and candidate findings.
- W3 modifier-interaction audit: six deload-order, set-floor, load-stack and RIR defects
  fixed with regression tests.
- Canonical `METHODOLOGY.md`, `PRIVACY.md`, generalised public examples and the public/private
  boundary; architecture/LLM contract reconciled with the actual bounded set-count proposal.
- Focused spinal-load review: keep the ordinal cap; no load/RIR/set weighting.
- Heavy spinal advisory: RIR ≤ 1 sets on high-fatigue spinal exercises shown as context only.

### Changed

- Replaced the legacy A/B/C session fields and overrides with four canonical session types
  (`squat`, `hinge`, `bench_squat`, `bench_hinge`). Migration 0023 reparses imported sessions
  from their preserved raw exercise composition, leaves unresolved sessions `unknown`, and
  drops `session_day`/`day_guess`. `--day` and `--start-day` are removed; use
  `--session-type`.

### Added

- Attendance summary shared by Today and Outcomes: completed/target, shortfall, family and
  session-type exposures, measured duration and symptom coverage; no prescription effect.
- `max_session_minutes` now tightens the planned cap and warns; it does not cut sets.
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
