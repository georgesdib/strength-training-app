# Changelog

## [0.5.0] — unreleased

### Added

- Generated **programme summary** (`tools/programme_summary.py`): the strength-programme review's session, weekly-volume and spinal-exposure tables are rendered from the templates, taxonomy, volume config and `PRG-SPINE-001`. The review now names the sumo deadlift and reports the 5.5/6 bench+hinge week; a stale block fails `tests/test_programme_summary.py`.
- Read-only **weekly volume budget** (`volume --budget`, `GET /api/volume/budget`, Prescribe
  panel): target, safety exemptions, completed sets, projected week, session cap and feasibility,
  plus per-group week status, persistent four-week status and non-essential top-up capacity. It
  writes nothing and changes no prescription (`DEC-VOLUME-06`, step 1 of
  `docs/VOLUME-MODULATION-PLAN.md`).
- Opt-in **per-group volume budget** behind `athlete_profile.volume_budget_enabled` (default
  off): trims or tops up non-essential accessory sets toward each group's effective target,
  cites `MOD-VOL-003` (constitution 1.15.0, amended through 1.17.0), and records
  readiness/deload/spinal cuts in `volume_exemption` so they are never re-added. Main lifts
  keep their template sets; `main_lift_policy` is `preserve` by default. `reduce` is
  implemented as step 2b; `drop` remains step 9c and is recorded but not implemented, so a
  prescription warns if it is selected.
- The weekly dose is explicit: `budget.weekly_total` and per-group `budget.weekly_target` in
  `config/volume.v1.yaml`, validated to match. Change both when changing the total.
- Opt-in **main-lift reduce** (step 2b): with `main_lift_policy: reduce` and the budget enabled,
  a group that was already filled before today has its main-lift items trimmed to
  `budget.main_lift_floor` (default 3 sets). The session type is unchanged, accessory top-up is
  disabled (no cross-group reallocation yet), safety cuts are skipped, and every change cites
  `MOD-VOL-003` (constitution 1.16.0). `drop` remains step 9c.
- Every volume-budget allocation parameter is config-backed: total and per-group targets, the
  **daily/session total cap** (`session_cap.total`) and per-group caps, tolerance/band minimum,
  trim/top-up switches, accessory floor and per-item top-up ceiling, set seconds/warm-up/time
  cap, and the reduce floor. The only profile controls are on/off, policy, and a tightening
  `max_session_minutes`.
- **Cross-group compensation** (steps 9a/9b): `budget.compensation` holds one optional slot
  per session type (dumbbell bench for push, RDL for hinge), inverse-similarity weights and a
  floor. A group filled before today frees its non-essential sets; the report selects the
  best-weighted receiver and shows freed, source, candidates and the selected slot. With
  `apply: true` and the budget profile flag on, the engine adds the selected item with a real
  load and cites `MOD-VOL-004` (constitution 1.17.0). 9b is additive, so it now stops at the
  weekly high tolerance band and does not add when the week is already there. If no load is
  available, it retries with the e1RM basis and then asks for an e1RM in the Prescribe panel
  (CLI prints the `e1rm set` command); it refuses only if still unusable. `drop` remains 9c.
- **Save feedback**: Athlete-page profile saves now show a toast ("Profile saved — new
  version appended"); the other state forms show a generic saved toast on success.
- **Budget UI label fix**: the volume-budget option is now “on”, with a helper explaining
  preserve/reduce/drop and that the main-lift policy is ignored while the budget is off.
- **Volume-ledger coverage plan**: recorded the calendar-window denominator and complete-coverage
  zero-fill design, including break/deload handling and under-MEV eligibility; not implemented.
- **Volume-modulation plan closed**: step 3 is now a standing Today review, not a plan item;
  step 8 effective accounting is live; future model and UI/KPI placeholders remain in the roadmap.
- **Budget effective allocation**: trim/top-up recompute through the 0.25 map when effective;
  session caps/time stay raw. Live remains hard; diff/activation pending.
- **Budget effective counts**: report target selection and effective completed/today/future
  counts; allocation and live activation remain pending. `hard` remains default.
- **Step 8 target audit**: documented the 12-week hard-vs-effective decision audit and stored
  the target-implied effective target table (68.25). Landmarks are not scaled; live accounting
  remains hard and the budget is not migrated.
- **Step 8 map revision**: indirect weights lowered to 0.25 after the target-implied check;
  target-implied total is 68.25 effective sets. Not activated; live accounting remains hard.
- **Step 8 chunk 1**: effective-set ledger infrastructure and the indirect map; `hard`
  remains the default and the live profile is unchanged. Target re-base, budget migration and
  live activation remain chunk 2/3.
- **Roadmap placeholder**: nicer UI, adherence encouragement and KPI/adherence stats;
  future only, no implementation or rule change.
- **Volume-ledger coverage correction**: calendar-window denominator, opt-in complete-coverage
  zero-fill, coverage arithmetic, and an under-MEV clock that resets on break/deload/zero weeks.
  The live profile is set to complete. `unknown` remains the app default.
- **Future personalised volume-response model**: recorded as a shadow-only, gated research
  track (uncertainty, pre-registered prospective run, no prescription change); not implemented.
- **Remaining modules (5c)**: continuity, fatigue-fitness shadow, test cadence and warmup
  are profile-backed and wired; high-intensity exposure is guarded-editable and always on;
  selection is a per-session read-only card. All YAML factors are in the registry; the Modules
  panel carries a behaviour note and docs link.
- **Budget-aware forecast/weekly panels (step 6)**: the programme simulates earlier projected
  sessions in the same ISO week; prescriptions carry a weekly volume panel; Prescribe, Programme
  and Workout show it. `drop` follows the real policy, held only inside the competition window.
- **Modality registry/UI (5b)**: 11 modules with classes, dependencies, citations and
  factor references; every enable delegates to the existing setting; hard-safety entries are
  read-only; `settings modalities`, `/api/modalities` and the Settings Modules panel share the
  same core. Remaining modules are deferred to 5c.
- **Settings UI and guarded settings (step 5)**: profile editor with diff/reset and
  append-only reason; guarded MRV cap and spinal cap/costs with typed `SPINAL` confirmation;
  Drop / volume fill writes a profile budget override; the step-3 volume-review reminder appears
  on Today once the budget is enabled and stays open. Modalities/factors are 5b.
- **Configurable hinge maximal scheme**: `undulation.maximal_hinge_allowed` (default false)
  is profile/config-backed; true lets the maximal scheme use the currently excluded hinge IDs.
  Settings UI exposure follows step 5.
- **Profile-backed feature wiring (7b)**: one resolved `FeatureSettings` per date now drives
  DUP (including the full scheme table), deload, volume landmarks/under-MEV, readiness set
  reduction, e1RM window/source/decay/calibration and plausibility in the engine, forecast, CLI
  and status views. Per-date forecast; no retrospective review; no UI; MRV cap remains guarded.
- **Settings profile (step 4)**: append-only `settings_profile` versions, full resolved
  `prescription_profile` snapshots, precedence profile > config > registry default, guarded-key
  rejection, CLI `settings profile` and GET/POST API, and budget override wiring. No UI; other
  feature loaders are 7b.
- **Settings registry (7a)**: a typed registry and read-through snapshot over DUP, deload,
  MRV/under-MEV, readiness set reduction, e1RM and plausibility, with classes, sources and
  ranges. The deload reactive two-week/two-flare constants moved to `config/deload.v1.yaml`.
  No precedence, profile, UI or behaviour change.
- **Drop confirmation/settings (9c-3)**: a Settings **Drop / volume fill** panel and
  `GET/POST /api/settings/drop`, backed by `config/volume.local.yaml`; per-session competition
  confirmation via `--drop-confirm`/API/Prescribe; candidate-pool validation; computed high band.
- **Drop identity/UX (9c-2)**: derived session labels in Prescribe, Workout, History and the
  programme forecast; an empty technique session can be started and ended as attendance with no
  rubric; `volume_fill` is reviewed against its actual items without a missing-main penalty;
  migration 0038 removes the fixed session-type CHECK.
- **Drop engine (9c-1)**: `budget.drop` candidate pools, high-band technique session, and a
  multi-slot `volume_fill_<original>` below the high band; the filled group's main and
  non-essential work are removed, the original type is recorded, and the rolling schedule maps
  the derived type back to its family. `MOD-VOL-005`/constitution 1.18.0. UI/CLI confirmation,
  labels, history and programme forecast are not part of 9c-1.
- Evidence review for reverse hyperextensions and belt squats: acute biomechanics/EMG only,
  no longitudinal strength or injury outcomes; both remain optional accessories.
- Guided **Workout workflow**: readiness → prescription preview → start → active workout (sets, CSV/per-rep import, end) → post-workout comparison. Readiness settings and Prescribe analysis remain separate pages.
- User-declared **technique throttle** (`MOD-TECH-001`): a one-session 90% load cap and RIR floor of 3, chosen explicitly in the Prescribe UI or with `run --technique-throttle [--throttle-pattern]`. It never reads `form_rating`, stores no state and cannot carry into the next session. The automatic `MOD-FORM-001` variant was rejected; see `docs/TECHNIQUE-THROTTLE.md`.
- Display-only **e1RM plausibility advisory**: when the e1RM behind a main-lift load is >5%
  above the decayed median of the lift's recent working sets (28 days, ≥3 sets), the
  prescription says so and names both numbers. No load, set or verdict changes; no modifier id;
  not persisted with the prescription (`DEC-E1RM-PLAUS-01`, `ASSUMPTION-37`).
- **e1RM overrides where the lift is on screen**: an **e1RM** action on every Exercises row
  (shows the override in force, appends a new one), and an optional e1RM panel on the
  ended-workout screen — a measured test from the set just performed (which registers a
  high-intensity exposure) or a direct override. Both use the same append-only endpoint as
  the Athlete page and `e1rm set`.
- **Measured-test coverage for P1** (`e1rm tests-needed`, Athlete page): one row per main
  lift with the tests counted, the tests still needed, the gate status and the next action,
  plus a note when a filed test was not counted because the app had no formula estimate inside
  the window before it. Read-only, and built from the same calibration pass, so its counts
  cannot drift from `e1rm calibrate`.
- **Symptom-logging workflow documented** (`docs/SYMPTOM-LOGGING.md`, linked from the Athlete
  page beside the form): what to write in `settled`, why a settled flare is closed by a new
  level-0 reading rather than an edit, and how the readings drive `MOD-BACK-001`,
  `PRG-EREC-001` and the injury signal.
- **Declared breaks** (`strength-coach break`, Athlete page): an append-only date range for a
  holiday, deload, test week or other break. Every week containing a break day is frozen — it
  leaves the trained-week count, so the DUP cycle and the erector ramp do not advance inside it
  (`DEC-CONTINUITY-04`). A mistake is cancelled by a new row, never an edit; no load, RIR or set
  changes. The scheduled-deload clock is not shifted (`LIM-50`).
- **Minimum-session target shown against the clock** (`LIM-47` mitigated, `DEC-MIN-02`): after a
  workout the ended screen reports target, estimate and measured duration together, and the
  estimate is labelled a planning aid. No load, set or RIR change; calibration stays a later
  option.
- The **technique throttle** is now reachable from the web: `POST /api/prescribe` takes
  `technique_throttle` and `technique_throttle_pattern`, and the Prescribe form has a
  **Technique throttle** tick plus an optional pattern scope. This closes the gap that
  `DEC-TECH-01` had assumed.

### Changed

- **Quality-limited power work** (`DEC-POWER-02/03`): `box_jump` now carries a stored quality stop rule instead of an RIR target. The item has `effort_model = quality`, a null `rir_target`; migration `0041` persists both; the API, UI, CLI, narrative and proposal show the stop rule; RIR transforms and RIR-compliance analytics skip quality items. Old prescriptions keep their recorded numbers.
- **Same-date plan accounting** (`DEC-VOLUME-30/31`): a plan rebuilt on a date with a recorded session is a revision; the date's recorded sets are excluded from the MRV, spinal and budget baselines and the plan is counted once. A same-date warning and `notes["same_date_session"]` are surfaced; performed-work policy still sees the session.
- **Back-flare alignment** (`DEC-SPINE-07/08`): the bench+hinge sumo is essential; `MOD-BACK-001` holds essential items and high-fatigue spinal lifts at RIR ≥3 with the load re-solved from the same e1RM, and the direct-erector dose is a ceiling that never restores a readiness cut. The sumo is excluded from the maximal scheme; constitution 1.19.0.
- **A level-1 symptom reading is a flare unless a 48-hour settlement is recorded**
  (`DEC-SYMPTOM-04`, Q25 closed). An unrecorded `settled` answer — the CLI and UI default —
  counts as not settled, so `symptom --level 1` no longer clears `MOD-BACK-001` and the
  erector-ramp gate by silence; recording `--settled yes` keeps the non-flare path.
- **Spinal cap raised 3 → 6**, the low-bar competition squat now counts as one high-fatigue
  exposure, and the bench+hinge support becomes a low-rep **sumo deadlift** (3×3–5, e1RM-derived) at 2.5. Standard weeks
  are 4 (bench+squat) or 5.5 (bench+hinge), leaving limited headroom; constitution 1.14.0
  (`DEC-SPINE-05`, Q24 closed).

- The e1RM behind a main-lift load is now an explicit **selector** rather than an implicit
  best-of-window: `median` (28-day robust window, the default), `best_usable` or `most_recent`
  (`DEC-E1RM-SOURCE-01`). Median can prescribe materially below a single great day, by design.
- The weekly spinal cap gains a one-directional trim: a non-essential erector slot is dropped
  when that alone brings the week to the cap, and the veto stands (naming the exposures) when
  essential work is the cause (`MOD-SPINE-001`, `DEC-SPINE-03`). The cap was 3 at that point; it was later raised to 6 by `DEC-SPINE-05`.
- Volume `under`/`high`/`over` status is judged per **landmark group**; the ledger exposes
  `group` and `group_average` per row (`DEC-VOLUME-05`).
- The weekly spinal cap's **squat classification** was documented with the evidence that ranks
  the variants: the low-bar competition squat has the most forward lean and erector demand, the
  safety-squat bar the most upright trunk. It was later resolved by `DEC-SPINE-05`: the cap is
  raised 3 → 6 and the competition squat counts at cost 1.
- **Two implemented modifiers are now declared in the constitution**: `MOD-TECH-001` and
  `MOD-MIN-001` were cited by the engine and the UI but absent from the document. Both are
  explicit one-session user requests, never automatic (constitution 1.13.1). The
  closed-question register and the roadmap's completed next-actions/gaps were also pruned to
  live items.
- **bench+squat no longer repeats the squat session's main lift.** Its 4-set squat support is
  the **competition squat** — a different bar, and the squat with real recent data — instead of
  a second SSB exposure two days later. Set count and squat-pattern volume are unchanged
  (`DEC-PROGRAMME-08`).

### Fixed

- `e1rm_source` was read by nothing: changing it to `median` changed no prescription. Unknown
  values now raise at config load instead of silently defaulting.
- `MOD-FAT-001`'s first-set RIR-drop branch was documented but never implemented. Removed, with
  the noise-floor reasoning recorded in `OPEN-QUESTIONS` Q23 (`DEC-RIR-04`, constitution 1.13.0).
- `MOD-VOL-002` added an under-MEV set to the wrong sub-pattern every session (a low
  `core_flexion` grew `ab_wheel`; a low `squat_unilateral` grew `split_squat`) and re-fired
  indefinitely. It now acts on the group that is actually under.
- The retired A/B/C labels still appeared in `PRG-RIR-001`'s rule scope and in `day_roles`
  in the exercise taxonomy. Both now list the four canonical session types
  (`DEC-SESSION-01`), and tests pin the vocabulary so the labels cannot return.
- A gap reduction could raise `UnboundLocalError` when a bodyweight item was the first one in
  the loop (box jump): its branch read `applied`, which only the load branch bound. Both
  branches now share the readiness+continuity budget, so a bodyweight set drop records the
  factor it actually used (`DEC-W3-02`).

- A readiness override did nothing on a day without a numeric score: `compute()` returned
  empty category scores and the engine only ran when the status was `ready`, so the override
  was stored, displayed and ignored. It now supplies the factor for the categories it covers
  (the status still says `insufficient`/`unknown` and the injury ceiling still caps it). A
  misspelt `category:<name>` scope is rejected instead of stored and silently ignored
  (`DEC-READINESS-17`, `READINESS-SCORE` §2.2a).

### Planned

- v0.5 cardio depth: capture audit, reproducible impulse, shadow 7/28-day load context, and a
  later model decision only after enough data (ROADMAP §4.13a). No automatic load effect.
- Comparable calibration depth: live-workout snapshots and per-rep data, per-item comparable
  counts, and a pre-declared rubric review (ROADMAP §4.14).

## [0.4.0] — 2026-10-25

**Audit, documentation and form closeout.** This release packages the post-v0.3 audits, UI
documentation contract, form assessment and calibration milestone. Cardio depth and comparable
 calibration implementation move to v0.5.

### Changed

- Exposed cumulative load reductions below 0.80 and added a stacked decay/readiness/deload test;
  no total-stack cap or load change.

- Exposed cumulative load reductions below 0.80 and added a stacked decay/readiness/deload test;
  no total-stack cap or load change.
- Closed Q7: floor-only RIR veto accepted; easier sets remain reported, not violations.
- Closed Q2/Q8: weighted one-exercise-per-session spinal exposure accepted; stale distinct-type wording corrected.
- Closed Q1: date-only imported sessions accepted; no timestamp backfill or inferred duration.
- Closed Q21: the current A/B/C exercise-comparability guard is accepted as-is.
- Closed Q6: current readiness merge and non-authoritative composite architecture accepted;
  Q3 documented as a manual anchor plus symptom input.
- PRG-SCHED-001 wording/scope now uses canonical session types (`squat`, `bench_squat`),
  not legacy Day A/C labels. No behaviour change.
- Retired derived `clean_set.form_score` after the per-exercise backfill; source Form remains in
  `raw_row.payload`. New `session_form_rating` is authoritative.

### Added

- Weakness-targeting test plan (`docs/WEAKNESS-TARGETING-PLAN.md`, ROADMAP §4.20.3): own-lift
  noise-aware definition, retrospective screen, opt-in N-of-1/alternating blocks, decision
  gates. Plan only; no targeting.
- Evidence review for parent-variant e1RM ratios: they are relative performance profiles, not
  weakness or injury measures. Display-only prior at most; no targeting (`DEC-SELECT-09`).
- UI documentation P0–P4: deep-linkable docs (`#docs?doc=...&anchor=...`), stable heading IDs,
  a canonical `docs/UI-MAP.md`, help + link on every panel, a Related footer on every UI-linked
  document, and `tools/check_ui_docs.py` coverage/link checks.
- Descriptive form trend in Outcomes and prior-form context in Review; no prescription use.
- Backfilled historical imported Form ratings per exercise (average of valid sets, inverted
  1=best → 5=worst, rounded half-up) into the new session form table.
- Optional post-lift form assessment, one 1–5 rating per exercise, editable in Workout and
  History; rubric 1.2.0 adds `FORM_ASSESSMENT` at weight 0.05.
- Dark mode with System / Light / Dark selection on the Settings page; stored per browser.
- History page with paginated sessions and append-only correction of completed/imported
  sessions; edits supersede old sets, rebuild totals/critique and mark re-review.
- Whole-session void/unvoid (audited, excluded from metrics/calibration) and set/rep VBT overrides.
- Evidence review for top set + back-off sets: specific overview plus indirect high-load/
  multiset/autoregulation evidence; no direct trial against the current programme; no change
  recommended yet.
- Optional per-rep velocity CSV in Workout mode, joined to set-level rows by exercise + set;
  append-only rep detail, per-set first/last/loss display, a descriptive `/api/rep-velocity`
  session report and a stratified `/api/rep-velocity/analysis` report. Missing table leaves the
  existing import unchanged. Evidence review: descriptive only, no RIR or injury prediction.
- Explicit `spinal_cost` for every high-fatigue entity; `single_leg_db_rdl` documented as
  non-counting; at-cap/headroom display in prescriptions. Cap unchanged.

### Fixed

- History corrections are now atomic: forms are validated before any write, set/form/feedback/audit
  mutations share one transaction, and a failed critique rebuild uses a savepoint instead of
  committing partial history. Rollback tests cover invalid forms and injected failures.
- Dynamic form-follow-up docs links used bare filenames; both now use `docs/...`, and the P4 checker scans JavaScript-generated docs links and requires their `Related` footer.
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
