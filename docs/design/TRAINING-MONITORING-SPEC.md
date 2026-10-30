# Training monitoring design specification

**Strength performance, external dose, internal load, relative strength and specialised exposure**

| Item | Value |
|---|---|
| Status | Proposal for review. **Not approved, not implemented.** |
| Repository | strength-training-app |
| Branch audited | development |
| Commit audited | bd9c796bebce3c6289c2b8d885f9336e6452c760 |
| Commit date | 2026-10-30 |
| Document date | 2026-10-30 |
| Scope | Research, audit and design only. No code, schema, config, API, UI, migration or dependency change. |
| Intended next reader | A human reviewer first, then a coding agent implementing an approved phase. |
| Location note | This file lives in docs/design/ rather than directly in docs/ because the repository's documentation-map test requires every top-level docs/*.md to be listed in AGENTS.md, and this task forbids editing AGENTS.md. Adoption should add it to that map. |

> **Non-negotiable framing.** The system described here is a set of **separate descriptive measurements**. It is not a universal workout score, not a fatigue model, not an injury predictor and not a prescription controller. Where the evidence is weak, this document says so and withholds the feature.

---

## 1. Executive summary

### 1.1 What was audited

The audit covered the branch and commit above, the set-level schema and ingest path, the e1RM and RIR domain code, the store read/write layer, the prescription engine's e1RM selector, the workout lifecycle and its end screen, the critique rubric, the volume ledger, the hard-set exposure ratio, high-intensity exposure, exercise demands, spinal cost, session feedback, the web API and UI, the migrations, and the test suite. The detailed findings are in §2.

### 1.2 The central finding

The repository already contains most of the **raw material** for the proposed system, and several computations are better than the proposal assumes. It does **not** contain a monitoring layer that turns those materials into a coherent, explicitly labelled set of session-level and longitudinal measurements. The gap is therefore mostly **definitions, composition, eligibility and presentation**, not new data capture.

Three existing facts change the proposal:

1. **"Pre-workout e1RM" is overloaded.** The app already has a prescription e1RM selector (median by default, 28-day robust window, 84-day outer window, age decay, measured-test calibration, overrides). That value is the **load base** used to solve the prescribed load. It is not the same quantity as "best recent demonstrated performance". Using one number for both relative intensity and the within-session change creates a **max-versus-median mismatch** that biases the change upward. This specification therefore defines two named quantities and keeps them separate.
2. **A within-session e1RM change is not a strength gain.** It is a re-estimate of the same latent capacity from a different set. A direct 1RM test has a median test–retest coefficient of variation of about **4.2%** in a 32-study systematic review (Grgic 2020). A formula-plus-RIR estimate has additional error. A reported change of +2.8% therefore lies inside ordinary measurement noise. The UI must say so rather than celebrate it.
3. **The existing session-RPE capture is immediate, not the validated 30-minute protocol.** Sweet 2004 and Day 2004 collected session RPE about 30 minutes after exercise. The app asks at the end of the workout. That is a defensible friction trade-off, but it must be labelled as immediate sRPE, and the app must not claim the 30-minute protocol until it collects a delayed value.

### 1.3 What is recommended

- **Keep the domains separate**: external dose, internal load, estimated strength, relative strength, power exposure, axial/spinal exposure, subjective productivity, longitudinal response. Present them together; never add them into one score.
- **Reuse** the existing clean_set, session, workout tables, e1rm_override, session_feedback, high_intensity_exposure, taxonomy, demand catalogue, spinal-cost registry, volume ledger, exposure ratio and rubric. Do not reimplement any of them.
- **Add one shared e1RM source function** and make the prescription engine, calibration report, monitoring layer and progress view use it. Today there are at least four independent "latest/best e1RM" computations with different windows, aggregations and eligibility.
- **Add a read-only monitoring module** that composes session summaries and trend series on demand. Do not persist derived metrics.
- **Add one nullable productivity column** to session_feedback if Domain G is approved. That is the only schema change this specification can justify. Everything else fits existing fields, the frozen plan JSON snapshot, or a new configuration file.
- **Withhold** velocity-loss claims, injury prediction, universal ratios, automatic prescription changes, complex forecasting and any composite 0–100 score.

### 1.4 The one-sentence verdict on each proposed domain

| Domain | Verdict |
|---|---|
| A. External dose | **Build it**, from completed clean_set rows only. Tonnage stays exercise-specific. |
| B. Internal load | **Build it** as sRPE × duration in AU, with explicit missingness and timing labels. |
| C. Estimated strength | **Build it**, but split load base from best-performance comparison and do not call the change adaptation. |
| D. Relative strength | **Build it as a descriptive, explicitly configured, date-stamped ratio**, with no targets and no weakness diagnosis. |
| E. Power exposure | **Build the count and the set-to-set velocity retention**; do not claim within-set loss or quality from mean velocity. |
| F. Axial/spinal exposure | **Present the existing ordinal exposure**; do not create a new spinal-load number. |
| G. Productivity | **Add one optional item**; keep it subjective and out of every calculation. |

### 1.5 What would make this design wrong

- If the athlete's measured tests show that the Epley+RIR estimator has large, rep-range-dependent bias, the best-set comparison should be replaced by a test-anchored estimate.
- If prospective data show that session load AU or productivity predicts subsequent performance better than a simple baseline, that is a reason to **study** them, not to automate them.
- If the exercise taxonomy gains a validated equivalence system for variants, Domain D could use it. Until then, explicit configuration is the only defensible route.

---

## 2. Repository audit and current-state architecture

### 2.1 Layering and data flow

The repository follows the documented direction utils ← domain ← ingest / store ← features ← rules / prescribe / critique ← agents / eval, with workout.py and history.py as operational services over the store. The web server only serialises and routes; deterministic computation lives in the core. This is the correct place for a monitoring layer: features/, read-only, no new controller.

The relevant flow for this design is:

    raw export / live workout
            ↓
    raw_row  →  clean_set  →  session
                     ↓
            features.derived.enrich
            (e1rm_kg, e1rm_method, e1rm_quality, velocity_present, in_rir_window)
                     ↓
       prescription (reads history before the date)
       critique (reads a stored session)
       volume / exposure / demands / spinal / high-intensity
       monitoring (new; reads completed sessions and their plan snapshot)

### 2.2 Existing functionality that must be reused

| Area | Existing implementation | What it already does | Reuse decision |
|---|---|---|---|
| Set identity and load | ingest/clean.py, domain/load.py | Canonical exercise id, load basis, external/total/progression load, bodyweight resolution, flags | Reuse unchanged. Do not recompute load basis in monitoring. |
| RIR semantics | domain/rir.py | RIR 6 = warm-up (DEC-RIR-01), RIR 0–5 effort, allowed window 1–4, target 2–3 (DEC-RIR-02) | Reuse the classifier. Do not add a second RIR rule. |
| e1RM formula | domain/e1rm.py | Epley and Epley+RIR, rep caps, method and quality tags | Reuse the formula. Add a **shared selector** around it. |
| Per-set enrichment | features/derived.py | e1RM applicability, e1RM, velocity presence, RIR window, power exclusion | Reuse, then extend eligibility for monitoring display. |
| Prescription e1RM | prescribe/engine.py::_latest_e1rm | Override first; best_usable / median / most_recent; 84-day window; 28-day robust median; age decay; calibration factor | Extract into a shared feature. Preserve behaviour exactly for prescriptions. |
| Calibration | features/e1rm_calibration.py | Measured-test ratio, bootstrap CI, bounded correction, per-lift coverage | Reuse for confidence and correction; do not create a second calibration. |
| Decay | features/e1rm_decay.py | Bounded 1%/week after 21 days, max 10% | Reuse. Show the factor. |
| Session feedback | features/session_feedback.py, session_feedback table | Optional sRPE (1–10), duration (minutes), note; append-only; blank allowed | Reuse. Add per-field merge and timing labels. |
| Live workout | workout.py, workout_session / workout_set / workout_event | Plan snapshot, in-workout edits, actual sets, end, materialisation, comparison | Reuse. Add monitoring to the summary, not to the active workout. |
| Completion comparison | workout.py::_comparison | Actual vs frozen plan, status, extra sets | Reuse; do not reimplement. |
| Volume ledger | features/volume.py | Working/hard sets by pattern, MEV/MAV/MRV landmarks, effective accounting | Reuse for weekly context. Do not duplicate landmarks. |
| Hard-set exposure | features/exposure.py | 7/28-day hard-set ratio, abstention, coverage, groups | Reuse the hard-set definition. Do not build a second ratio. |
| High-intensity exposure | features/high_intensity_exposure.py | Tests, max attempts, competition, unplanned; guard windows | Reuse for the "special exposure" section. Never count as volume. |
| Demand catalogue | features/demands.py, config/exercises/demands.v1.yaml | Qualitative axial/trunk/technical/local dimensions with provenance | Reuse for axial/spinal context. Never aggregate dimensions. |
| Spinal cost | rules/registry.py (spinal_exposures, weekly_spinal_costs), features/heavy_spinal.py | Ordinal cost per (session, exercise), bounded set/intensity policy factors, weekly cap | Reuse. The summary must call the registry, not recompute. |
| Critique | critique/facts.py, critique/rubric.py | Adherence/execution rubric with a weighted composite | Keep separate. Never present the rubric composite as a workout load or stimulus. |
| Progress dashboard | features/progress.py | sRPE coverage, attendance, volume, 84-day performance ratio, back symptom | Reuse as context; do not treat its ratio as an e1RM series. |
| Fatigue-fitness | features/fatigue_fitness.py | Shadow per-lift model; rejected retrospectively | Do not connect. Do not assume new metrics improve it. |

### 2.3 Set-level data audit

| Field | Meaning in the schema | Sufficient for the proposal? | Ambiguity / gap |
|---|---|---|---|
| set_id, session_id, occurred_on | Identity and date | Yes | Imported sessions have a date, not a timestamp; two sessions on one date cannot be ordered. Live workouts use a UUID and a started_at. |
| exercise_id, raw_exercise | Canonical and raw identity | Yes | Equivalence is explicit only for documented relations; trap bar / sumo / conventional are separate. |
| load_kg | Normalised load | Partly | Three meanings (external, total bodyweight, added load) are disambiguated by load_basis. |
| load_basis | external / bodyweight_total / added / unknown | Yes | For added, the read helper queries.clean_sets sets total_load_kg = load_kg, losing the bodyweight contribution. This is latent because current bodyweight-typed exercises are e1rm_applicable: false, but it must be fixed before any bodyweight e1RM or relative-intensity feature. |
| external_load_kg | Load actually added | Yes | 0 is valid for pure bodyweight. |
| reps, reps_unit | Repetitions or seconds | Yes | Timed sets are not repetitions; do not sum them into rep totals. |
| rir, rir_source | Proximity-to-failure report | Partly | RIR is self-reported with substantial error (Zourdos 2021; Refalo 2024). RIR 4 is almost absent in the local history and RIR 5 is common, so the configured hard-set threshold ≤4 behaves as ≤3 in practice. |
| velocity_mps, velocity_present | Mean velocity per set | Partly | A mean has no within-set variance. 0 is a device-unused sentinel. |
| power_w | Power | **No** | The column exists but is never populated by ingest or workout materialisation. The raw Avg_power column is not mapped. Do not use it. |
| rom_mm, tut_s | Range and time under tension | Partly | Present in schema; not used by the proposal. Do not infer ROM changes from it without a standard measurement. |
| form_score | Per-set form | **Retired** | Migration 0034 cleared it; the source remains in raw_row.payload. Use session_form_rating instead. |
| tonnage_kg | External load × reps | Yes, per exercise | Null for bodyweight/time-based. Do not sum across unrelated exercises and call it a universal workload. |
| is_working_set | Warm-up exclusion | Yes | Derived from RIR 6. A missing RIR is still a working set (assisting accessories). |
| flags | Data-quality flags | Yes | JSON list; REPS_TYPO, LOAD_BASIS_UNKNOWN, SECONDS_NOT_REPS, NO_RIR, SUSPECT_RIR, WARMUP. |
| source_row | Traceability to raw | Yes | Rejoin through raw_row. |
| prescription_item_index | Link to the plan item | Yes | Set on materialisation; useful for completion and substitution. |

**Conclusion:** the set-level schema is sufficient for Domains A, B (with feedback), C, E (counts only), F and G (with one new column). It is not sufficient for within-set velocity loss, jump height, contact time, or a measured spinal load. Those must be explicitly withheld or collected prospectively. Weighted bodyweight movements (for example a weighted pull-up) cannot have an e1RM under the current taxonomy because pull_up carries e1rm_applicable: false; enabling that is a separate identity/product decision, not part of this proposal.

### 2.4 Session feedback audit

Current implementation:

- session_feedback stores srpe (1–10), duration_min (>0, ≤600), note, recorded_at; append-only; at least one field must be non-null.
- session also carries duration_min, duration_basis (measured / unavailable), session_rpe, session_rpe_recorded.
- workout_session also carries duration_min, duration_source (measured / manual), session_rpe, session_rpe_recorded, notes.
- workout.end requires an sRPE or an explicit "not recorded"; duration defaults to the measured clock, with manual override.
- The end screen shows workout_session values, not a merged session_feedback read.

Audit findings:

1. **Three copies of the same facts.** session_feedback, session and workout_session can disagree. A canonical read policy is required.
2. **Row-wise append-only feedback loses fields.** A correction that supplies only sRPE creates a latest row with a null duration. Reading "the latest row" then makes session load unknown even though an earlier row had the duration. The read must merge **per field**, taking the latest non-null value of each.
3. **Manual duration is mislabelled as measured.** workout._materialise writes duration_basis = 'measured' unconditionally, and history.py does the same on edit. The session schema has no manual value. This affects the rubric's SESSION_DURATION item and attendance. The monitoring layer must label duration_source from workout_session when available and must not silently treat manual as objective.
4. **Immediate sRPE is not the 30-minute protocol.** The UI asks at the end. Label it.
5. **No productivity field.** This is the only genuine capture gap in Domain G.
6. **No interruption field.** Only duration and notes. Do not infer an interruption.

### 2.5 Existing systems that must remain conceptually separate

| System | What it measures | What it must not become |
|---|---|---|
| Programme critique (critique/rubric.py) | Adherence and execution against the programme, with a weighted composite over measurable items | A workout workload, physiological stimulus, fatigue, strength-development or recovery score. The composite is an adherence index, not a load. |
| Weekly volume ledger (features/volume.py) | Working/hard sets by pattern against configurable MEV/MAV/MRV landmarks | A measured personal threshold. The landmarks are assumptions. Do not duplicate the weekly computation in the session summary. |
| Hard-set exposure (features/exposure.py) | A 7/28-day ACWR-shaped descriptive ratio, with abstention | An injury-risk model. It is contested and must remain descriptive. |
| High-intensity exposure (features/high_intensity_exposure.py) | Tests, max attempts, competition and unplanned near-max work, separate from volume | Ordinary hypertrophy volume. Do not count a test as a working set for dose. |
| Exercise demands (features/demands.py) | Qualitative, dimension-specific claims with provenance | A spinal-load measurement or an aggregate score. unknown is not low. |
| Spinal cost (rules/registry.py) | Ordinal exposure with bounded policy factors against a weekly cap | Lumbar compression/shear in newtons, or an injury probability. |
| Fitness-fatigue (features/fatigue_fitness.py) | A shadow diagnostic that was rejected retrospectively | A load controller, or a reason to adopt new metrics. |

### 2.6 Existing e1RM computations: four implementations, four answers

This is the most important architectural finding for Domain C.

| Location | Window | Aggregation | Decay | Calibration | Override | Exercise applicability |
|---|---|---|---|---|---|---|
| prescribe/engine.py::_latest_e1rm | 84 days, robust 28 days | median (default), best_usable, most_recent | Yes, per set | Yes | Yes, wins | Uses e1rm_kg, so applicability is respected |
| features/e1rm_calibration.py::build | 84 days | max per lift | Yes, applied once to the max | Reports correction | Reports | Uses e1rm_kg |
| features/baseline.py::lift_baselines | 84 days for window, all-time for best | max | No | No | No | Uses e1rm_kg |
| features/progress.py::_session_lift_e1rms | Per session | max per exercise | No | No | No | **Does not check e1rm_applicable**; computes for RDL, back extension, etc. |
| features/fatigue_fitness.py | Per session | max per canonical lift | No | No | No | Uses e1rm_kg |

Consequences:

- A "pre-workout e1RM" implemented with any of these would give a different number.
- e1rm_calibration reports latest_e1rm as the maximum over the window but latest_on as the latest date in the group, so the displayed date can belong to a different set than the value. That is a labelling defect, not a calculation-defining one, but it matters for source transparency.
- progress already violates the taxonomy's e1rm_applicable: false decision.
- The new monitoring layer must **not** add a fifth computation. It must call one shared selector with an explicit cutoff and estimator.

### 2.7 Existing plan snapshot: a free extension point

workout_session.plan_json freezes the prescription shown at start. It is JSON, so new fields can be added **without a migration**. Today _item_dict and PrescriptionItem.as_rows expose e1rm_source_sets but not the e1RM value, the reference, or the planned intensity. The monitoring layer needs the load base; the cleanest fix is to add e1rm_kg, e1rm_ref, e1rm_quality, e1rm_age_days and intensity to the plan item dict at generation time. Old snapshots without these fields can be recomputed with a **strict pre-session cutoff** and flagged reconstructed.

### 2.8 Test and fixture landscape

The suite already has focused tests for e1RM, RIR, load, exposure, spinal cap, high-intensity exposure, session feedback, workout lifecycle, history, progress, critique and the web API. The monitoring work should extend those patterns:

- synthetic make_training / make_readiness fixtures (never data/raw);
- pure-function tests for definitions;
- API contract tests for the summary and trend endpoints;
- no golden prescription changes unless a shared e1RM refactor accidentally changes behaviour.

### 2.9 Data sufficiency (qualitative, from the local store)

The local store contains several years of training history and dense main-lift records, but the monitoring layer must be designed for the **actual** coverage, not an ideal one:

- **Main lifts** have dense history; **variation/accessory** lifts are sparser and more irregular.
- **RIR** is present on essentially all imported working sets, but RIR 4 is almost absent and RIR 5 is common. Live-workout RIR is optional.
- **Session feedback** covers only a subset of sessions; older sessions were intentionally left blank. Session-load trends must show coverage, not assume completeness.
- **Measured e1RM tests** are absent or very few. The calibration report may have no points, so there is no athlete-specific e1RM error estimate yet. The 4.2% population CV is a reference, not a personal calibration.
- **Per-rep velocity** is sparse. Mean velocity exists on some sets. Power data is essentially box jumps; there is no jump height or contact time.
- **High-intensity exposures** may be absent. A zero is a valid zero only when the recording path was available.
- **Trap-bar history** starts after the documented switch, so trap-bar/sumo ratios are not contemporaneous over most of the record.

This is why Phase 2 must show coverage and "unavailable" states prominently, and why Phase 4 is exploratory.

### 2.10 Extension versus genuine gap

| Category | Items |
|---|---|
| Exists and is reused unchanged | clean_set and load resolution; RIR classes; Epley/Epley+RIR; measured-test calibration; age decay; workout plan snapshot and completion comparison; volume ledger; hard-set exposure; high-intensity exposure; demand catalogue; spinal registry; session_form_rating; progress dashboard; rubric |
| Exists but requires a bounded extension | e1RM selector (extract a shared function with a session cutoff); session feedback (per-field merge and timing label); plan JSON (add e1RM value/reference/quality/intensity at generation); bodyweight total read for added-load rows; power classification (config, not names) |
| Genuinely missing | session-level e1RM pre/post summary; relative intensity; exercise-specific tonnage report; session hard-set/near-failure summary; session load AU; configured relative-strength ratios; longitudinal e1RM series and rolling median; comparable-session comparison; power set-to-set retention; productivity field; structured power quality-stop event |
| Data structures sufficient? | Yes for Domains A, B, C, E (counts and retention), F, and D (via config). No for G without one nullable productivity column. No for within-set velocity loss or measured spinal load, which are explicitly excluded. |

The free-text session_feedback.note is **not** a substitute for a productivity field: it is unvalidated free text, cannot be queried as an ordinal scale, and would conflate a subjective judgement with a comment. If Domain G is approved, the one nullable integer column is the minimum sufficient change.

**Recommendation on sRPE timing.** Keep the single end-of-workout prompt. It is the lowest-friction option and preserves completion rates. Label the value "immediate sRPE" and do not claim the 30-minute protocol. If the athlete wants the validated timing, add an optional "Record 30-minute sRPE" action on the review screen and store a timing field; do not make the delayed value mandatory. Until then, any session-load trend mixes immediate values and must say so.

---

## 3. Proposed monitoring architecture

### 3.1 Principles

1. **Separate constructs, shared data.** One clean_set frame feeds every domain. The domains are composed for display, never arithmetically combined.
2. **Completed work only.** Prescribed, modified and actual are all shown; only actual counts toward dose.
3. **No new controller.** Nothing here changes a load, set, RIR, deload or exercise selection.
4. **No hidden defaults.** Every eligibility rule, window, band and threshold is named, configurable and marked as evidence or assumption.
5. **Unknown is a first-class result.** It is rendered as "Unavailable" or "Not recorded", never 0.
6. **Recompute, do not persist.** Derived metrics are computed on read from immutable rows. A cached view is optional, keyed to the database version.
7. **One definition per concept.** If a definition is needed in two places, it lives in domain/ or features/ and is imported.
8. **Transparency over polish.** Every headline number can be opened to its source rows.

### 3.2 Module layout (proposed)

| Module | Responsibility | Layer |
|---|---|---|
| features/e1rm_source.py (new) | One e1RM selector: eligibility, window, estimator, decay, calibration, override, cutoff | features |
| features/monitoring.py (new) | Pure definitions: completion, dose, relative intensity, RIR distribution, hard sets, tonnage, session load, power, spinal, productivity | features |
| features/strength_trend.py (new, or part of monitoring) | Per-session e1RM observations, rolling median, series breaks, sparse-data rules | features |
| features/relative_strength.py (new) | Configured ratio pairs, date comparability, trend | features |
| config/monitoring.v1.yaml (new) | Bands, windows, thresholds, flags, display policy | config |
| config/strength-relationships.v1.yaml (new) | Explicit numerator/denominator relationships | config |
| web/server.py | New read-only routes; no computation | web |
| web/static/summary.js (new) or workout.js extension | Rendering only | web |
| cli.py | summary / performance commands calling the same core | CLI |

features/monitoring.py must not import prescribe or web. features/e1rm_source.py may import domain, store.queries and taxonomy utilities, but **not** prescribe. The engine imports the feature; the dependency arrow does not reverse.

### 3.3 The two e1RM quantities

| Quantity | Purpose | Estimator | Window | Cutoff | Used by |
|---|---|---|---|---|---|
| load_base_e1rm | Denominator for relative intensity; the load the prescription was solved from | Prescription selector: median by default, fallback best_usable | 84 days outer, 28 days robust | Strictly before the session; override in force | A2 relative intensity; plan-drift check |
| pre_best_e1rm | Best recent demonstrated performance, comparable to today's best set | Highest eligible set-level estimate, age-decayed to today | 84 days | Strictly before the session | C1/C3 within-session change |
| post_best_e1rm | Best demonstrated performance in the session | Highest eligible set-level estimate | Current session only | Current session | C2/C3, longitudinal series |

Why two pre values: the prescription's median is a **robust central** estimate, while the session's best set is a **maximum**. Comparing a maximum to a median creates a positive bias even when nothing changed. Using the best recent set for both sides makes the change like-for-like. Using the median for relative intensity keeps the percentage consistent with the load the athlete was actually prescribed. The UI must name them differently and never show one while implying the other.

### 3.4 Data flow for a completed workout

    workout_session (plan_json snapshot, plan_modified_json, events)
            │
            ├── actual sets → materialised clean_set (same session_id)
            │
            ├── session_feedback (sRPE, duration, note, productivity)
            │
            ├── high_intensity_exposure (linked by set/date)
            │
            └── monitoring.summary(conn, session_id)
                     ├── completion: _comparison(original/modified/actual)
                     ├── strength: e1rm_source before/after
                     ├── dose: clean_set working sets, tonnage, RIR, relative intensity
                     ├── special: power, high-intensity, spinal (registry)
                     ├── feedback: merged sRPE/duration → AU, productivity
                     └── comparison: comparable prior sessions (if any)

**Critical ordering rule:** the summary is computed **after** materialisation, but the pre-session estimate must exclude the current session. The cutoff is by session_id and by date, not by "today". See §5.3.

### 3.5 What is persisted

Nothing new, except session_feedback.productivity if approved. All monitoring values are derived. This avoids a second source of truth and makes corrections (append-only clean_set supersedes) automatically flow through.

If caching is needed, use an in-process cache keyed by (database_path, mtime_ns, size, session_id), as fatigue_fitness.compute_cached already does. Do not write a cache table.

---

## 4. Exact metric definitions and formulas

### 4.1 Status vocabulary

Every metric returns one of these statuses. The UI must render them distinctly.

| Status | Meaning | Example |
|---|---|---|
| observed | A logged fact | 14 completed working sets |
| estimated | A formula result with a method tag | e1RM 156.0 kg (Epley+RIR) |
| unknown | Data that should exist but does not | session RPE not recorded |
| not_applicable | The quantity has no meaning for this exercise/set | e1RM for a plank |
| invalid | Data present but fails validation | 21-rep set for e1RM; negative load |
| unavailable | Data exists but eligibility prevents use | e1RM older than 84 days; ratio dates too far apart |
| zero | A real measured zero | 0 hard sets when all working sets have RIR 5 |

A metric must not collapse unknown, unavailable and zero into one value.

### 4.2 Common rules

- **Completed work** = clean_set rows with voided = 0, session.voided = 0, not superseded, is_working_set = 1.
- **Warm-up** = rir_class == "warmup" (RIR 6, DEC-RIR-01). Excluded from every dose, e1RM, relative-intensity and hard-set metric; counted only as "warm-up sets" for visibility.
- **Test/high-intensity set** = a set linked to a high_intensity_exposure by set_id or by an exact (session_id, exercise_id) match. It remains a working set for completion but is excluded from the ordinary RIR/relative-intensity distribution and shown in "Special exposure". If it cannot be linked, it stays in the ordinary distribution and the summary says "possible test not linked" rather than guessing. A linked test set still counts once in the completed-set and hard-set totals (the exposure row is not added again), but it is shown in Special exposure and kept out of the ordinary RIR/relative-intensity distribution.
- **Timed set** (reps_unit = seconds) is not a repetition and has no tonnage. It counts as a working set and as time, not reps.
- **Bodyweight**:
  - bodyweight_total: load_kg is total mass; use it for e1RM and relative intensity.
  - added: load_kg is the added load; total mass = added + bodyweight for e1RM/relative intensity; progression and tonnage use the added load only (DEC-LOAD-02).
  - unknown: no e1RM, no relative intensity, no tonnage.
  - Bodyweight comes from the merged readiness row on the session date or the nearest within ±7 days; if absent, the total is unknown. Do not guess.
- **Exercise identity**: exact exercise_id for e1RM and ratios. The only documented history equivalence is history_equivalent_of (currently hyperextension → back extension, DEC-BACKEXT-02); use it only where the app already does, and label the merge. Never merge trap bar/sumo/conventional, SSB/competition/high-bar/front, or bench/narrow/pause/DB/machine.
- **No imputation**: never fill a missing RIR, load, duration or RPE from another field. The existing Epley fallback for a missing RIR is a **formula convention**, not an imputation; monitoring must treat it as a separate, lower-quality method and must not headline it.

### 4.3 Metric catalogue

The table below is the normative definition. "Type" uses D = descriptive, I = inferential, P = predictive. No metric in this specification is P.

| # | Metric | Definition / formula | Inputs | Unit | Eligibility | Missing behaviour | Key flags | Comparability | Known limits | Type | UI | May influence programming? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1.1 | Completed working sets | Count of working clean_set rows in the session, excluding warm-ups and superseded rows | clean_set | sets | Valid session; is_working_set | unknown if no set rows; zero only if a session exists with no working sets and the absence is real | WARMUP_EXCLUDED | Same session only | A "set" is a logged row; a drop set or cluster may be one or several rows by logging convention | D | Summary card 1 | No |
| A1.2 | Completed repetitions | Sum of reps over working sets with reps_unit = reps | clean_set | reps | Working sets only | Exclude timed sets; unknown if no rep-bearing sets | TIMED_SETS_EXCLUDED | Same exercise/session | Partial reps are not captured; a failed rep is not a row | D | Card 1 | No |
| A1.3 | Exercise tonnage | Σ(external_load_kg × reps) over working sets of one exercise | clean_set | kg | Loadable, non-time-based, external/added load present | Sum known sets; report coverage; not_applicable if all undefined | TONNAGE_PARTIAL | **Within exercise only**; not across exercises | Ignores bodyweight, ROM, tempo, mechanics | D | Card 3, per exercise | No |
| A1.4 | Session tonnage (optional) | Sum of A1.3 over exercises | clean_set | kg | At least one tonnage-bearing set | unknown if none; partial otherwise | TONNAGE_PARTIAL | Only sessions with high exercise overlap; never a universal workload | Exercise-mix dependent; bodyweight excluded | D | Advanced only | No |
| A1.5 | Hard sets | Count of working sets with 0 ≤ rir ≤ effort_max_rir (config default 4) | clean_set, exposure config | sets | Working sets with known RIR | If any working set has unknown RIR, report known_hard and unknown_rir; do not call the total 0 | RIR_UNKNOWN | Same exercise/session; weekly comparison via exposure | RIR error; RIR 4 nearly unused locally | D | Card 3 | No |
| A1.6 | Near-failure sets | Count of working sets with rir ≤ 2 | clean_set | sets | Known RIR | Same as A1.5 | RIR_UNKNOWN | Same exercise/session | Not a measure of stimulus; RIR error | D | Card 3 | No |
| A1.7 | Pattern distribution | Count of working sets per volume_target_key(pattern) | clean_set, taxonomy, volume config | sets | Working sets | unknown pattern bucket if taxonomy missing | PATTERN_UNKNOWN | Same pattern grouping as the ledger | Grouping is a config decision, not a measurement | D | Card 3 | No |
| A2.1 | Load-base e1RM | Prescription selector: highest-priority override, else median of eligible set e1RMs in the 28-day robust window, else best usable in 84 days; age-decayed; calibration factor; **strictly before the session** | clean_set, e1rm_override, calibration, decay | kg | Exercise e1rm_applicable; load basis resolvable; eligible set | unknown/unavailable if no eligible estimate | E1RM_STALE, E1RM_OVERRIDE, E1RM_CALIBRATED, E1RM_RECONSTRUCTED | Exact exercise only | Formula error, decay assumption, median is not a max | D | Card 3, details | No (already used by prescription) |
| A2.2 | Relative intensity (set) | load_used_kg / load_base_e1rm_kg | A2.1, set load, load basis, bodyweight | fraction / % | Load base known; set load resolvable; working set; not a warm-up; not a test; e1RM applicable | unknown if either side missing; not_applicable for non-e1RM exercises | RI_NO_DENOM, RI_LOAD_UNKNOWN | **Within exercise and same load basis**; never across exercises | Load base error propagates directly; bodyweight convention | D | Card 3 | No |
| A2.3 | Relative-intensity distribution | Counts of working sets in configured bands (<60%, 60–<70%, 70–<80%, 80–<90%, ≥90%) + unknown count | A2.2 | sets | As A2.2 | Excluded sets are reported, not silently dropped | RI_PARTIAL_COVERAGE | Same exercise | Bands are display bins, not validated thresholds; 80% anchored to ACSM 2026 strength finding | D | Card 3 | No |
| A3.1 | RIR distribution | Counts at RIR 0,1,2,3,4,5, missing, warm-up | clean_set | sets | Working sets; exclude power/test | Missing is its own bin, not zero | RIR_UNKNOWN, RIR_OFF_SCALE | Same exercise/session | Self-report error; ordinal, do not average | D | Card 3 | No |
| A3.2 | RIR coverage | known_RIR_working_sets / working_sets | clean_set | fraction | Working sets | unknown if no working sets | RIR_UNKNOWN | Same session | A high coverage does not mean accurate RIR | D | Card 3, advanced | No |
| A4.1 | Exercise tonnage | Same as A1.3 | — | kg | — | — | — | Within exercise | See A1.3 | D | Card 3 | No |
| B1.1 | Session RPE | Latest non-null srpe for the session, with source and timing | session_feedback, session, workout_session | 1–10 | Session completed | unknown; never 0 | FEEDBACK_LATE, SRPE_IMMEDIATE | Within athlete only | Perceived, not objective; immediate vs 30-min | D | Card 5 | No |
| B1.2 | Duration | Latest non-null duration_min, with source (measured / manual / unavailable) | Same | minutes | Session completed | unknown if absent | DURATION_MANUAL | Within athlete only | Manual may include idle time; imported rows have no clock | D | Card 5 | No |
| B1.3 | Session load | srpe × duration_min | B1.1, B1.2 | AU | Both known | unknown if either missing; never 0 | SESSION_LOAD_UNKNOWN, FEEDBACK_LATE | Within athlete, same feedback protocol | Internal load, not physiological stress; arbitrary units | D | Card 5 | No |
| C1.1 | Pre-session best e1RM | Highest eligible set-level e1RM in the 84 days **strictly before** the session, age-decayed to the session date | clean_set, decay, calibration | kg | e1rm_applicable; quality ok preferred; load basis resolvable | unavailable if none | E1RM_STALE, E1RM_DEGRADED, E1RM_PRE_RECONSTRUCTED | Exact exercise only | Single-set max is noisy; decay assumption | D | Card 2 | No |
| C2.1 | Post-session best e1RM | Highest eligible set-level e1RM in the current session | clean_set | kg | Same as C1.1, current session only | unavailable if none | E1RM_POST_MISSING, E1RM_DEGRADED | Exact exercise only | Best-of-set max; fatigue/back-off selection | D | Card 2 | No |
| C3.1 | e1RM change (kg) | post_best − pre_best | C1.1, C2.1 | kg | Both ok | unavailable if either missing | E1RM_CHANGE_LOW_CONFIDENCE | Same exercise, same general method | Difference of two estimates, not a measured change | D | Card 2 | No |
| C3.2 | e1RM change (%) | 100 × (post_best − pre_best) / pre_best | C1.1, C2.1 | % | Both ok; pre > 0 | unavailable | Same | Same | Small values are noise; 4.2% population CV reference | D | Card 2 | No |
| C4.1 | Source set | The set_id, load, reps, RIR, exercise, method, quality, flags of the post estimate | clean_set | row | C2.1 known | unknown | E1RM_DEGRADED | Same exercise | One set can be an outlier | D | Expandable details | No |
| C5.1 | Exercise identity | Exact exercise_id, with display and documented equivalence | taxonomy | id | — | unknown if unresolved | IDENTITY_EQUIVALENT | Exact only, except documented history equivalence | Variant differences are real | D | Card 2/3 | No |
| C6.1 | e1RM observation | Per-session best eligible e1RM for one exercise | clean_set | kg | ok sets only for the primary series; degraded points shown separately | Gap, not interpolation | E1RM_DEGRADED | Exact exercise | Selection of best set; sparse | D | Performance view | No |
| C6.2 | Rolling median | Median of the last 3 observations (configurable) | C6.1 | kg | ≥3 observations | No line below 3; points only | SPARSE_SERIES | Exact exercise | Descriptive smoother, not a model | D | Performance view | No |
| D1.1 | Relative-strength ratio | 100 × numerator_e1RM / denominator_e1RM | C1.1/C6.1 for both, config relationship | % | Both eligible, both ok, date gap ≤ configured, both within max age | unavailable if either missing or stale | RATIO_GAP, RATIO_SPARSE, RATIO_ONE_SIDED | Explicitly configured pair only | Ratio of two noisy estimates; no diagnostic validity | D | Performance view; max 2 on summary | No |
| D1.2 | Ratio dates/gap | Numerator date, denominator date, absolute gap | C1.1/C6.1 | days | As D1.1 | unknown | RATIO_GAP | Same pair | A large gap makes the ratio historical, not current | D | Ratio detail | No |
| D1.3 | Ratio trend | Paired observations over time; no interpolation | D1.1 | % | ≥2 paired observations for a line; ≥5 for a change statement | Points only if sparse | SPARSE_SERIES | Same pair | Selection and measurement drift | D | Performance view | No |
| E1.1 | Power sets | Count of working sets on power-classified exercises (pattern == power_jump) | clean_set, taxonomy | sets | Power-classified exercise | unknown if classification missing; zero is valid if classification is complete | POWER_CLASS_UNKNOWN | Same exercise/session | Taxonomy coverage; Olympic lifts absent | D | Card 4 | No |
| E1.2 | Power repetitions | Sum of reps on power sets | clean_set | reps | Power sets | As E1.1 | — | Same exercise | Reps are not a quality measure | D | Card 4 | No |
| E1.3 | Set-to-set velocity retention | last_set_mean_velocity / first_set_mean_velocity for the same exercise and load | clean_set | % | ≥2 power sets, same exercise and load, velocity_present | unavailable if not measurable | POWER_VELOCITY_PARTIAL | Same exercise/load/equipment | Mean velocity only; no within-set loss; load must match | D | Card 4 | No |
| E1.4 | Power quality stop | Whether the athlete recorded a quality stop (height/technique/velocity drop) | workout_event payload or explicit flag | yes/no/not recorded | Power set | unknown; never inferred from velocity | POWER_QUALITY_UNRECORDED | Same exercise | Current prescription has text, not a structured event | D | Card 4 | No |
| E1.5 | Within-set velocity loss | Not computable from a mean | — | — | — | unavailable | VELOCITY_LOSS_UNAVAILABLE | — | A mean has no within-set variance | D | "Not available" | No |
| F1.1 | Spinal exposures | Per (session, exercise) effective ordinal cost from weekly_spinal_costs | clean_set, rule params, taxonomy | ordinal units | Working sets on high_fatigue_spinal exercises | zero if none and sets are present; unknown if no sets | SPINAL_UNRATED | Same rule/config; weekly ledger | Ordinal, not load; policy factors are assumptions | D | Card 4 | No |
| F1.2 | Heavy spinal sets | Working sets on high_fatigue_spinal exercises with rir ≤ 1, last 4 weeks | features/heavy_spinal | sets | Known RIR | unknown if RIR missing | RIR_UNKNOWN | Same window as the advisory | Context only; no cap effect | D | Card 4 / weekly | No |
| F1.3 | Axial demand mix | Counts of working sets by axial_spinal level (high/moderate/low/unknown) | features/demands | sets | Working sets | unknown count is explicit | SPINAL_UNRATED | Same dimension only | Qualitative; unknown ≠ low | D | Card 4, advanced | No |
| G1.1 | Productivity | Single optional item: 1–5 | session_feedback.productivity (new) | 1–5 | Session completed | unknown if skipped; never 0 | PRODUCTIVITY_NOT_RECORDED | Within athlete only | Single item, unvalidated; subjective | D | Card 5 | No |
| H1.1 | Feedback completeness | Which of sRPE, duration, productivity are present | Same | booleans | Session completed | unknown | — | Same session | — | D | Card 5 | No |
| H2.1 | Comparable-session summary | Median of a metric over up to 5 prior comparable sessions | clean_set, session type, main lifts | metric unit | Comparability rule (§10.3) | unavailable if <3 comparable sessions | COMPARISON_WITHHELD | Same session type + common main lift + no deload/minimum/technique | Still observational; exercise mix varies | D | Card 6 | No |

### 4.4 Detailed notes on the contentious metrics

#### A1.3/A4.1 Tonnage

Tonnage is external load × reps. It is meaningful **within one exercise** across sessions when the execution, equipment and ROM are stable. It is not a universal workload:

- a 100 kg bench rep and a 100 kg squat rep do not represent the same mechanical work;
- bodyweight movements exclude body mass by design, so a pull-up session can look small;
- ROM, tempo and technique change the work without changing load × reps;
- a substitution changes the exercise identity and breaks the comparison.

Therefore: show tonnage per exercise on the session summary and in exercise-specific trends. Do **not** show a session "total workload" as a headline. If a total is shown at all, label it "sum of external load × reps (not comparable across exercise mix)" and restrict comparisons to sessions with high exercise overlap.

#### A2.2 Relative intensity

The denominator is load_base_e1rm, not the post-session best. It must be the estimate that was available **before** the session. If the frozen plan snapshot carries the e1RM used, use it; otherwise recompute with the strict cutoff and flag reconstructed.

Bands (proposed ASSUMPTION-58, to be registered):

| Band | Range | Interpretation |
|---|---|---|
| Very light | <60% | Warm-up/technique or high-rep accessory |
| Light | 60–<70% | Accessory/hypertrophy |
| Moderate | 70–<80% | Mixed |
| Heavy | 80–<90% | Strength-oriented; ACSM 2026 found ≥80% 1RM enhanced voluntary strength at group level |
| Near-max | ≥90% | Maximal/near-max; often a test |

The 80% cut is anchored to the ACSM overview of reviews. The other cuts are **display bins**, not physiological thresholds. Do not label a set "hypertrophy" or "strength" solely from its band; the adaptation depends on volume, effort, frequency and the individual.

#### A3.1 RIR distribution

RIR is an ordinal self-report with error that grows with distance from failure (Zourdos 2021: roughly 2 reps at 1 RIR, 3.7 at 3 RIR, 5 at 5 RIR in the squat; Refalo 2024 shows similar issues in the bench). Therefore:

- show counts per RIR value, not a mean;
- show missing and warm-up separately;
- do not convert RIR to a "proximity-to-failure score";
- do not infer RIR from velocity or reps;
- do not treat RIR 5 as a hard set;
- do not call RIR 4 "hard" with confidence when it is almost never used in the actual log (it is a config threshold, not a measured behaviour).

#### B1.3 Session load

session_load_au = sRPE × duration_min. Both inputs are required. This is an **internal-load** measure in arbitrary units. It reflects perceived session demand, not objective physiological stress. It must not be added to tonnage, hard sets or e1RM change. It must not be compared across athletes.

Missingness:

- sRPE missing → unknown.
- duration missing → unknown.
- both present → compute; label duration source and sRPE timing.
- late feedback → compute; flag FEEDBACK_LATE; do not correct.
- interrupted or unusually long → compute from the recorded duration; flag LONG_SESSION if >2× the recent comparable median (descriptive only); do not split or truncate.
- imported session with no feedback → unknown, never 0.

#### C1/C2 e1RM methodology

Formula: load × (1 + (reps + rir)/30) for an RIR-adjusted estimate; load × (1 + reps/30) only as the plain Epley fallback. The RIR-adjusted form is an approximation (ASSUMPTION-03 in the existing code), not a validated equation.

Eligibility for the **monitoring headline**:

1. exercise_id is canonical and e1rm_applicable is true.
2. is_working_set and rir_class == "effort" (not warm-up, not RIR 6).
3. reps_unit == "reps" and 1 ≤ reps ≤ 20.
4. 0 ≤ rir ≤ 5; RIR 0 is allowed and flagged SUSPECT_RIR.
5. reps + rir ≤ 20 for an RIR-adjusted estimate. **This is a new guard**: the current add_e1rm checks only reps, so 20 reps + RIR 5 produces an effective 25-rep extrapolation. Reject it for the headline.
6. load > 0; load_basis in external / bodyweight_total / added.
7. For bodyweight_total or added, total mass is resolvable; otherwise unavailable.
8. No REPS_TYPO, SECONDS_NOT_REPS or LOAD_BASIS_UNKNOWN flag.
9. Not a set that the session summary classifies as a power set (no RIR target; e1RM for a jump is not meaningful unless loaded and e1rm_applicable).

Quality:

- ok: reps ≤ 10 and rir ≤ 3. This is the headline-eligible band.
- degraded: reps 11–20 or rir 4–5. Show with a warning; do not use for Δ or a new PR.
- invalid: fails any eligibility rule.

Why rir ≤ 3 for ok: RIR error grows with distance from failure, RIR 4 is nearly absent in the local log, and Robinson 2024's strength models show a plateau across a wide estimated-RIR range while hypertrophy favours closer-to-failure work. This is a **display-quality rule**, not a claim that RIR 4–5 sets are useless.

The existing prescription must keep its current e1RM behaviour (including degraded sets) to avoid changing loads. The stricter quality rule applies to the **new monitoring headline**, not to the load solver.

#### C3 interpretation

- **Improved post e1RM**: "Best estimate today was higher than the best recent estimate." Add: "This is an estimate from one or more sets; it is not evidence that strength increased during the session."
- **Lower post e1RM**: "Best estimate today was lower than the best recent estimate." Add possible explanations: fatigue, set selection, RIR error, technique, equipment, readiness. Do not say "you lost strength".
- **No change**: if |Δ%| < 4.2%, say "within typical 1RM test–retest variation; no clear change". If ≥ 4.2%, say "larger than typical test–retest variation, but still an estimate". The 4.2% is the median CV from Grgic 2020, a population reference, not an individual threshold.
- **New personal best**: compare the post raw estimate with the all-time raw best (same exercise, ok quality). If higher, "new best estimate" and show the previous best/date. Do not call it a competition PR; it is an estimate.
- **Different rep range**: label the source reps/RIR. A 3-rep estimate and a 10-rep estimate have different error. Do not compare them without the label.
- **After a long interruption**: if the pre estimate is >28 days old, label "after a break" and show the decay factor. Do not interpret the change as adaptation; the pre is a decayed prediction.

#### D1 ratios

The ratio is 100 × e1RM(numerator) / e1RM(denominator). Both sides must be eligible, ok estimates, within max_age_days of the evaluation date, and within max_gap_days of each other. Defaults are proposed assumptions (ASSUMPTION-59): max_gap_days = 14, max_age_days = 42. The gap is a product judgement: short enough that both reflect the same training period, long enough to occur at 2–3 sessions/week. It is not a validated window. If the gap is larger, show the ratio as historical with both dates and a warning, or withhold it.

Do not use raw training loads as substitutes for e1RM. Do not infer a relationship from programme_slot_of, vbt_family or names. Configure each pair explicitly.

#### E1 power

Power work is classified by pattern == power_jump today. The taxonomy does not include Olympic lifts; if they are added, the classification must be extended in config, not by name matching. Power sets are quality-limited, not RIR-scored (DEC-POWER-02). Count them, show the stop rule text, and exclude them from the ordinary RIR/relative-intensity distributions.

velocity_mps is a **mean per set**. It cannot yield within-set velocity loss. Set-to-set retention is possible when the same exercise and load are repeated. If the load changes between sets, do not compute retention; report unavailable.

A structured quality-stop event does not exist. quality_stop is a text field on the prescription item and effort_model = quality marks the item. Until an explicit event/flag is recorded, power_quality_stop = unknown, not "met".

#### F1 spinal

Use weekly_spinal_costs from the rule registry. It creates one exposure per (session, exercise) for high_fatigue_spinal exercises, applies bounded set-count and mean-%e1RM policy factors, and sums per ISO week against the configured cap. The session summary should show:

- the session's exposures with their effective cost;
- the weekly total and cap position;
- the heavy-spinal advisory count (RIR ≤1) as context;
- the axial demand level from the demand catalogue, with unknown count.

Do not sum per-set costs into a new "spinal load". Do not describe the result as lumbar compression or shear. Do not use it as an injury predictor.

#### G1 productivity

Exact wording:

> **How productive did this session feel?**
>
> 1. Not at all productive
> 2. Slightly productive
> 3. Moderately productive
> 4. Very productive
> 5. Extremely productive
>
> *Optional. This is your own judgement, not a training-load measure.*

Store 1–5; null if skipped. Do not use a 0. Do not compute a session "quality" or "stimulus" from it. Do not require it to end the workout. Do not feed it into prescription, deload or selection. Report the distribution; a mean or median is acceptable only as a descriptive summary of an ordinal item, with that caveat.

---


## 5. e1RM pre/post-workout methodology (normative)

### 5.1 Definitions

- E = a set-level e1RM estimate in kg.
- Q(E) = quality class (ok / degraded / invalid).
- D(E, t) = age-decay factor from features/e1rm_decay at date t.
- C = calibration factor for the lift, if MOD-E1RM-001 is in force; otherwise 1.0.
- O = the override in force on the session date, if any.

pre_best_e1rm(session):

1. Take all clean_set rows with the same exercise_id, e1rm_applicable, eligible per §4.4, and **strictly before** the session (see §5.3).
2. Keep rows with date >= session_date − 84 days.
3. If an override O is in force on the session date, it wins: pre_best = O.e1rm_kg × D(O, session_date), source = override.
4. Otherwise compute E_i × D(E_i, session_date) × C for each eligible set.
5. Restrict to Q = ok if any exist; otherwise use degraded and flag.
6. pre_best = max(effective). Tie-break: most recent date, then highest set_id.
7. If no eligible row: unavailable.

post_best_e1rm(session):

1. Take all clean_set rows with session_id == current, same exercise, eligible per §4.4.
2. Compute E_i × C (no decay; age 0).
3. Restrict to Q = ok if any exist; otherwise degraded and flag.
4. post_best = max(E_i). Tie-break: most recent set_id.
5. If none: unavailable.

load_base_e1rm(session):

- If the frozen plan snapshot has e1rm_kg, use it (with e1rm_ref, quality, age).
- Else recompute with the prescription selector (median default) on history strictly before the session, including override, decay and calibration.
- If none: unavailable.

### 5.2 Which value goes where

| Display | Value | Why |
|---|---|---|
| "Best recent estimate" | pre_best_e1rm | Comparable to "best today" |
| "Best estimate today" | post_best_e1rm | Same estimator |
| "Change during this session" | post_best − pre_best | Same estimator, both maxima |
| "Relative intensity" | load_base_e1rm | The load was solved from this estimate |
| "Planned intensity" (if shown) | plan item intensity | The prescription's own number |
| "Personal best estimate" | all-time raw best, same exercise | A record, not a decayed prediction |

Do **not** use pre_best as the relative-intensity denominator. Do **not** use load_base as the pre-change baseline. The UI labels must make the distinction obvious.

### 5.3 The cutoff rule (the circularity guard)

The session summary is computed after materialisation, so the current session's sets are already in clean_set. A naive date <= session_date filter would include them and inflate pre_best.

The rule:

- Exclude session_id == current_session_id always.
- Include occurred_on < session_date.
- For occurred_on == session_date, include a set only if it belongs to a **different session** whose workout_session.started_at is earlier than the current workout's started_at. If either timestamp is missing (imported rows), exclude same-date sets.
- Never use a set from the current session, even if its date is earlier (e.g., a workout that spans midnight).

This rule must have a regression test: compute pre_best, add the current session's sets, recompute, and assert equality.

### 5.4 planned vs reconstructed load base

- If plan_json has e1rm_kg, e1rm_ref, e1rm_quality, e1rm_age_days, mark source = planned.
- Else recompute and mark source = reconstructed.
- If both exist and differ by more than the lift's noise band (or 4.2% if unknown), show a plan_drift note: "The plan was generated from X kg; the estimate immediately before the session was Y kg." Do not silently pick one.

### 5.5 Worked examples

See §16.4–§16.5.

---

## 6. Longitudinal e1RM methodology

### 6.1 Observation

One point per (exercise_id, session_id): the session's post_best_e1rm. Use the same eligibility and quality rules as §5. Do not use the load-base median, and do not use the 84-day "best" repeatedly (that would create a step function, not a series).

### 6.2 Series breaks

Break the series when any of these changes:

- exercise_id (including a substitution);
- equipment or load basis (bar, SSB, trap bar, dumbbells, machine, belt, ROM convention);
- the documented history equivalence (only where the app already merges, e.g. hyperextension → back extension); show a marker;
- a change in the rep/RIR protocol that makes the estimates non-comparable (e.g., a switch from 5s to 1s).

Do not interpolate across a break. Do not silently concatenate trap bar and sumo. Show a vertical marker and a note.

### 6.3 Smoothing

Default: **rolling median of the last 3 observations**. It is simple, robust to one bad session, does not assume a functional form, and handles irregular spacing because it is observation-based. Alternatives:

| Method | Advantage | Disadvantage | Verdict |
|---|---|---|---|
| Last observation | No lag | Noisy; one bad day dominates | Use as the raw point |
| Rolling median of 3 | Robust, simple, explainable | Lags a real change by ~1 session | **Default** |
| Rolling median of 5 | More robust | More lag; hides short blocks | Offer as an option |
| Linear regression | Summarises slope | Assumes linearity; sensitive to outliers; encourages over-interpretation | Do not default |
| Spline/state-space | Flexible | Overfits sparse data; unvalidated; dependency | Do not implement |
| Fitness-fatigue | Mechanistic | Rejected retrospectively; non-identifiable (Marchal 2025) | Do not connect |

No interpolation. No extrapolation. If there are fewer than 3 observations, show points only. If there are fewer than 5, do not state a trend change.

### 6.4 Display

- Raw points: one dot per session, tooltip with date, load, reps, RIR, quality.
- Trend: rolling median line, dashed to signal "smoothed".
- Y-axis: kg, zero not forced (strength changes are small); label the unit.
- X-axis: date, with gaps; do not compress gaps to equal spacing without saying so.
- Series breaks: vertical line + label.
- Sparse state: "3 observations; no trend line yet."
- Confidence: high / moderate / low / unavailable based on quality, recency and count. No numeric confidence.

### 6.5 Interpretation

- "The latest estimate is above/below the recent median" — descriptive.
- "The trend over the last N observations is upward/downward" — only with ≥5 observations and a clear separation; still not proof of adaptation.
- "No clear change" if the change is within the 4.2% reference band.
- "After a break" if the gap is ≥28 days; show the gap and the decay.
- "Exercise changed" if the series broke; do not compare across the break.

### 6.6 Accessory and variation lifts

The same method applies, but the data are sparser. Do not lower the eligibility bar to create a line. Show "insufficient observations" rather than a misleading trend. Do not compare an accessory's e1RM to a main lift's e1RM as if they were the same quantity; that is Domain D, with its own rules.

---

## 7. Accessory-to-main-lift ratio methodology

### 7.1 Configuration, not inference

Create config/strength-relationships.v1.yaml with entries like:

    schema_version: "1.0.0"
    relationships:
      - id: front_squat_to_competition_squat
        label: "Front squat / competition squat"
        numerator: front_squat
        denominator: competition_squat
        relationship_type: variant_to_main
        max_gap_days: 14        # ASSUMPTION-59
        max_age_days: 42        # ASSUMPTION-59
        min_observations: 2
        notes: "Descriptive relative performance only; not a weakness diagnosis."

Required fields: id, numerator, denominator, relationship_type, max_gap_days, max_age_days, min_observations, notes. Validate:

- both ids exist in the taxonomy;
- numerator ≠ denominator;
- no duplicate (numerator, denominator) pair;
- max_gap_days > 0, max_age_days >= max_gap_days;
- relationship_type is one of a small enum (variant_to_main, accessory_to_main, equipment_variant, range_variant);
- notes is non-empty.

Do **not** use programme_slot_of as the relationship graph. It is a prescription-slot hint (currently one entry), not a strength comparison. Do **not** use vbt_family; it pools load-velocity data for calibration, not strength.

### 7.2 Calculation and comparability

ratio = 100 × e1RM(numerator) / e1RM(denominator).

Both sides:

- exact configured exercise ids;
- Q = ok;
- within max_age_days of the evaluation date;
- date gap ≤ max_gap_days for a **contemporaneous** ratio;
- ≥ min_observations eligible observations per side for a "current" ratio (otherwise "provisional" with the count).

If the gap is larger but both are within max_age_days, show a **historical** ratio with both dates and a warning. If either is stale or missing, unavailable.

### 7.3 Display

| Field | Example |
|---|---|
| Ratio | 75.5% |
| Numerator | Front squat 123.3 kg (2026-10-20) |
| Denominator | Competition squat 163.3 kg (2026-10-23) |
| Gap | 3 days |
| Quality | both ok; 2 and 4 observations |
| Confidence | moderate |
| Trend | paired points only; no target line |

Do not show a target band. Do not colour a low ratio as "bad". Do not rank the athlete against a population.

### 7.4 Interpretation and limitations

A ratio is influenced by anthropometry, technique, execution, ROM, equipment, specialisation, fatigue and e1RM error. A low ratio does not identify a weak muscle. A change in ratio does not establish that the accessory caused a change in the main lift. The existing evidence review PARENT-VARIANT-WEAKNESS-EVIDENCE.md already reached this conclusion; this specification adopts it rather than reopening it.

Labels: "relative performance", "ratio of estimates", "descriptive". Never "weakness", "imbalance", "diagnostic", "injury risk" or "target".

### 7.4a What a ratio can and cannot be used for

| Use | Status | Reason |
|---|---|---|
| Descriptive individual monitoring | **Supported as a display** | It is the ratio of two explicitly configured estimates, with dates and quality. It can prompt a review of technique, equipment, familiarity or fatigue. |
| Population reference values | **Not appropriate** | There are no validated individual norms; anthropometry, technique, ROM, equipment and specialisation differ. |
| Evidence that a ratio predicts or explains main-lift performance | **None found** | The literature supports task specificity and performance profiling, not a causal or diagnostic ratio. Any longitudinal association is an exploratory hypothesis. |

### 7.5 Future analysis (Domain D6)

Only after enough paired observations:

- pre-register the question: "Are changes in the ratio associated with subsequent main-lift performance?"
- use chronological out-of-sample validation;
- compare against simple baselines (last observation, rolling median, main-lift trend);
- report n, missingness, effect size and stability;
- no causal language;
- no automatic exercise selection, volume change or "weakness" targeting.

---

## 8. Data-quality and missing-data rules

### 8.1 Zero, missing, unknown, not applicable, invalid, estimated

| Value | Meaning | Rendering | Example |
|---|---|---|---|
| 0 | A real measured zero | 0 | 0 power sets in a non-power session |
| Missing | No value was recorded | "Not recorded" | sRPE blank |
| Unknown | A value should exist but cannot be determined | "Unknown" | hard sets when all RIR are missing |
| Not applicable | The quantity has no meaning | "Not applicable" | e1RM for a plank |
| Invalid | A value exists but fails validation | "Excluded: invalid" | 21-rep e1RM |
| Estimated | A formula result | "Estimated" + method | e1RM 156.0 kg (Epley+RIR) |

Do not convert missing to zero. Do not convert unknown to zero. Do not render an empty cell as a dash without a legend.

### 8.2 Metric-specific missing-data behaviour

| Situation | Behaviour |
|---|---|
| No session feedback | sRPE, duration, session load, productivity = unknown; card 5 says "Not recorded" with an "Add feedback" link. |
| sRPE only | session load = unknown until duration is added; do not use a default duration. |
| Duration only | session load = unknown until sRPE is added. |
| Feedback entered late | compute; FEEDBACK_LATE if recorded >24 h after ended_at for a live workout; imported sessions have no timing, so the flag is not_applicable. |
| Manual duration | compute; DURATION_MANUAL; do not call it measured. |
| Interrupted session | compute from recorded duration; LONG_SESSION if >2× recent comparable median; no automatic adjustment. |
| RIR missing on a working set | hard set = unknown for that set; RIR distribution has a missing bin; e1RM headline excludes it. |
| RIR 6 | warm-up; excluded from dose, e1RM, RI, hard sets; counted separately. |
| Load basis unknown | e1RM/RI/tonnage = not applicable; set still counts for completion. |
| Bodyweight unknown | e1RM/RI = unavailable for bodyweight lifts; set still counts. |
| No eligible post set | post e1RM = unavailable; do not substitute another exercise or a warm-up. |
| No eligible pre set | pre e1RM = unavailable; do not use post as pre. |
| e1RM older than 84 days | unavailable; show the last date and "too old". |
| Tonnage partial | sum known sets; show known/total; never impute. |
| Ratio one side missing | unavailable. |
| Ratio gap too large | unavailable or historical with warning. |
| Power quality not recorded | unknown, not "met". |
| No power work | 0 if the session's exercise classification is complete; unknown if classification is missing. |
| No spinal exposures | 0 if working sets are present and all are classified; unknown if no sets or classification missing. |
| Productivity skipped | unknown; never 0. |

### 8.3 Data-quality flags (derived, not stored)

E1RM_PRE_MISSING, E1RM_PRE_RECONSTRUCTED, E1RM_POST_MISSING, E1RM_DEGRADED, E1RM_REPS_RIR_OVER_CAP, E1RM_NO_RIR, E1RM_LOAD_BASIS_UNKNOWN, E1RM_BODYWEIGHT_UNKNOWN, E1RM_STALE, E1RM_OVERRIDE, E1RM_CALIBRATED, E1RM_CHANGE_LOW_CONFIDENCE, RI_NO_DENOM, RI_PARTIAL_COVERAGE, TONNAGE_PARTIAL, SESSION_LOAD_UNKNOWN, FEEDBACK_LATE, DURATION_MANUAL, LONG_SESSION, RIR_UNKNOWN, RIR_OFF_SCALE, POWER_CLASS_UNKNOWN, POWER_QUALITY_UNRECORDED, POWER_VELOCITY_PARTIAL, VELOCITY_LOSS_UNAVAILABLE, SPINAL_UNRATED, RATIO_GAP, RATIO_SPARSE, RATIO_ONE_SIDED, COMPARISON_WITHHELD, PRODUCTIVITY_NOT_RECORDED.

These are **derived display flags**, not new persisted state. Do not reuse an existing ingest flag for a different meaning.

### 8.4 Warm-up, working, failed, partial, testing and substitution

| Case | Handling |
|---|---|
| Warm-up (RIR 6) | Excluded from all dose/e1RM/RI/hard-set metrics. Show count and share as a coaching signal. |
| Working set | is_working_set = 1; RIR known or missing. |
| Failed set (RIR 0) | Included; flagged SUSPECT_RIR; eligible for e1RM; not a warm-up. |
| Partial set / missed reps | No field; count actual reps; report completion status under; do not infer a partial ROM. |
| Testing attempt | Separate high_intensity_exposure; if also a clean_set, count once for completion but not as ordinary volume; exclude from the RIR/RI distribution when linked; show in Special exposure. |
| Substitution | Compare against the modified plan; show the swap event and the original slot; do not map e1RM across exercises. |
| Abandoned workout | No materialised session; no summary. |
| Technique session | No template; show duration/feedback only; no completion/strength sections. |
| Minimum session (MOD-MIN-001) | Show the target/estimate/measured block; do not compare dose to a full session. |
| Deload (MOD-DELOAD-001) | Show a badge; withhold or restrict historical comparisons. |

---


## 9. Workout-end UI specification

### 9.1 Principles

- **Mobile-first**: design for a 390 px portrait viewport; landscape uses a two-column grid only where it does not squeeze tables.
- **Three primary numbers per card**, maximum. Everything else is progressive disclosure.
- **No composite score.** Do not add a single "workout score", "quality score" or "stimulus score".
- **No false precision.** Round kg to 0.5, percentages to 1 decimal, AU to whole numbers. Do not show 4 significant figures for an estimate.
- **No colour-only meaning.** Pair colour with text ("above", "within", "unavailable").
- **No inline handlers.** Use data-action plus event delegation and escaped attributes (AGENTS §7.8).
- **Accessible**: labels, aria-live for async updates, 44 px touch targets, focus states.

### 9.2 Information hierarchy

| Tier | Content | Always visible? |
|---|---|---|
| 1 | Completion, strength performance, feedback summary | Yes |
| 2 | External dose (sets, tonnage per exercise, RIR, relative intensity, hard sets) | Yes, condensed |
| 3 | Special exposure (power, high-intensity, spinal) | Yes, condensed; details expandable |
| 4 | Historical comparison | Only if ≥3 comparable sessions |
| 5 | Ratios | At most 2, only if contemporaneous and reliable; otherwise a link |
| 6 | Source sets, excluded sets, methods, flags | Expandable |
| 7 | Full historical analysis | Separate Performance view |

### 9.3 Wireframe (iPhone portrait)

    ┌──────────────────────────────────────────────┐
    │  WORKOUT SUMMARY                 Tue 28 Oct │
    │  Bench + Squat · 65 min · sRPE 7 · 455 AU   │
    │  Productivity 4/5                            │
    ├──────────────────────────────────────────────┤
    │  1  COMPLETION                    3/4 items  │
    │  ████████████████░░  14/16 sets · 62/70 reps │
    │  Bench press       complete        4/4       │
    │  Competition squat under           3/4       │
    │  Back extension    complete        3/3       │
    │  [substitution: none]                        │
    ├──────────────────────────────────────────────┤
    │  2  STRENGTH PERFORMANCE                     │
    │  Bench press                                 │
    │  best recent   156.0 kg   20 Oct             │
    │  best today    158.7 kg   set 2: 140×3 @2    │
    │  change        +2.7 kg  (+1.7%)              │
    │  ≈ within typical test–retest variation      │
    │  [Why this set?]  [All eligible sets]        │
    ├──────────────────────────────────────────────┤
    │  3  TRAINING DOSE                            │
    │  Bench press   3 sets · 1,980 kg tonnage     │
    │  Relative intensity  [80%][85%][70%]         │
    │  RIR  0:0  1:1  2:2  3:0  4:0  5:0  ?:0      │
    │  Hard sets 3 · near failure 3 · unknown 0    │
    │  Patterns  push 3 · squat 3 · hinge 3        │
    ├──────────────────────────────────────────────┤
    │  4  SPECIAL EXPOSURE                         │
    │  Power      3 sets · 15 reps · retention 94% │
    │  Quality    not recorded                     │
    │  High int.  none                             │
    │  Spinal     trap bar 2.0 · back ext 0.85 ... │
    │             weekly 4.0 / 6.0                 │
    ├──────────────────────────────────────────────┤
    │  5  HOW IT FELT                              │
    │  sRPE 7 (immediate) · 65 min (measured)      │
    │  Session load 455 AU                         │
    │  Productive 4/5                              │
    ├──────────────────────────────────────────────┤
    │  6  COMPARED WITH 3 COMPARABLE SESSIONS      │
    │  sets 14 vs 15 (median) · hard 8 vs 9        │
    │  top set 85% vs 84% · session load 455 vs 470│
    │  [View all]                                  │
    ├──────────────────────────────────────────────┤
    │  [Review workout]  [Record e1RM]  [Details]  │
    └──────────────────────────────────────────────┘

### 9.4 Component-level specification

**Header**

- Date, session type label, duration, sRPE, session load AU, productivity.
- If any is missing: "Not recorded", with an "Add feedback" link that opens the existing review flow.
- Do not show the rubric composite.

**Section 1 — Completion**

- Progress bar: completed working sets / planned working sets (modified plan), plus reps if available.
- Per-item table: exercise display name, status (complete / under / over / missing / extra), actual/planned sets, actual reps.
- Substitution badge: "Substituted for X" from the plan/event, if applicable.
- "Original prescription" disclosure: the existing original_comparison table, unchanged.
- Do not count a missing item as zero dose.

**Section 2 — Strength performance**

- One row per main lift that has either a pre or post estimate; not every accessory.
- Columns: exercise, best recent (date), best today (source set), Δ kg, Δ %, interpretation badge.
- Interpretation badges: clear increase, clear decrease, within typical variation, low confidence, unavailable. "Clear" means |Δ%| ≥ 4.2% and both estimates ok; it still does not mean adaptation.
- [Why this set?] expands: load, reps, RIR, exercise, method, quality, flags, decay factor, calibration factor, source (planned/reconstructed/override).
- [All eligible sets] expands a table with each set's e1RM and exclusion reason (warm-up, RIR missing, reps >10, reps+rir >20, load basis unknown, quality degraded, test-linked).
- If no post set: "No eligible set today" + the reason. If no pre: "No recent eligible estimate" + the last date if any.
- Do not label the change "strength gain" or "PR" unless the PR rule is met (and then "new best estimate", not "competition PR").

**Section 3 — External training dose**

- Per-exercise table: sets, reps, tonnage (with coverage), hard sets, near-failure sets, RIR distribution summary.
- Relative-intensity distribution: counts per band + unknown count. Use a small stacked bar or a table; do not use a single average without the distribution.
- Pattern distribution: counts by volume_target_key; do not compare to MEV/MAV here (weekly context is elsewhere).
- "Tonnage is external load × reps; compare within an exercise only."
- If any set has no load base, show "N sets uncategorised".

**Section 4 — Special exposure**

- Power: sets, reps, exercise, set-to-set retention if measurable, quality stop status. "Within-set velocity loss is not available from mean velocity."
- High-intensity: list exposures linked to the session, kind, exercise, intensity class, guard status. "Not counted as working volume."
- Spinal: per-exercise effective cost, weekly total/cap, heavy-spinal count, axial demand mix with unknown count. Label "ordinal exposure, not lumbar load".
- If no special exposure: "None recorded" — a valid zero if the session's classification is complete.

**Section 5 — Feedback**

- sRPE, duration with source, session load AU, productivity.
- "sRPE is immediate, not the 30-minute protocol" helper.
- "Session load is sRPE × minutes in arbitrary units; it is not a physiological measurement."
- Missing values show "Not recorded" and an action, never 0.
- Productivity helper: "Optional self-report; not used for prescription."

**Section 6 — Historical comparison**

- Only if ≥3 comparable sessions (§10.3).
- Show median of the prior comparisons, n, and the comparison key ("same session type + common main lift").
- Withhold for deload, technique, minimum sessions or <50% exercise overlap.
- Do not compare by date proximity alone.

**Section 7 — Actions**

- "Review workout" (existing).
- "Record an e1RM" (existing test/override flow).
- "Performance" (link to the historical view).
- "Details" (source sets, methods, flags).

### 9.5 Landscape and tablet

- Two columns: left = completion + strength; right = dose + special + feedback.
- Tables keep horizontal scroll within .table-scroll; the page itself must not scroll horizontally.
- The header remains one line; the action bar remains at the bottom of the content, not fixed over the safe area.

### 9.6 Copy rules

| Do say | Do not say |
|---|---|
| "Best recent estimate" | "Current max" |
| "Best estimate today" | "New 1RM" |
| "Change during this session" | "Strength gain" |
| "Within typical test–retest variation" | "No progress" |
| "Estimated from Epley + RIR" | "Measured" |
| "Unavailable" | "0" or "—" without explanation |
| "Hard sets (RIR ≤ 4)" | "Effective sets" |
| "Session load (AU)" | "Training stress" |
| "Ordinal spinal exposure" | "Spinal load" |
| "Relative performance ratio" | "Weakness ratio" |

---

## 10. Historical monitoring and analysis

### 10.1 Trends

The Performance view (new top-level page, or a section under Outcomes) should support:

- exercise-specific e1RM observations and rolling median;
- exercise-specific tonnage and hard-set counts;
- relative-intensity distribution over time;
- session load AU over time, with sRPE coverage;
- power sets/reps and set-to-set retention;
- axial/spinal exposure over time;
- configured ratios and their paired observations.

Filters: date range, exercise, session type, include/exclude deloads, minimum quality. Always show n and coverage. Never interpolate.

### 10.2 Dose–response (exploratory)

Define a small, pre-registered set of exposures and outcomes:

| Exposure | Outcome | Lag |
|---|---|---|
| Session load AU | Next-session best e1RM (same lift) | 1 session |
| Hard sets (per pattern) | Next-session best e1RM (same lift) | 1 session, 1 week |
| Relative-intensity distribution (e.g., sets ≥80%) | Next-session best e1RM | 1 session |
| Spinal effective cost | Next-session best e1RM / sRPE | 1 session |
| Power sets | Next-session jump/speed if available | 1 session |
| Productivity | Next-session performance / sRPE | 1 session |

Method: within-lift, within-athlete descriptive comparisons; report n, missingness, effect size, and uncertainty. Do not use causal language. Do not fit a complex model to sparse data. If a model is ever attempted, it needs chronological out-of-sample validation against the baselines in §12.3.

### 10.3 Comparable-session comparison

A prior session is comparable when **all** hold:

1. same session_type (or a documented equivalent);
2. at least one common main lift;
3. not a deload, technique or minimum session;
4. within the last 8 weeks (config);
5. exercise overlap ≥50% by working sets;
6. at least 3 prior comparable sessions.

Do not compare sessions merely because they are a week apart. Do not compare a squat day to a hinge day. Do not compare a full session to a minimum session.

Metrics to compare: completed working sets, hard sets, top-set relative intensity, session load AU (if both have feedback), post e1RM (same lift). Show medians, not means, and n.

### 10.4 Recovery and fatigue associations

Investigate whether session load, hard sets, relative intensity or spinal cost are associated with subsequent performance. Do not assume a high load impairs performance. Account for:

- days between sessions;
- exercise-specific exposure (a heavy squat does not necessarily affect bench);
- training frequency;
- exercise selection and substitutions;
- training interruptions;
- missing observations;
- readiness and sleep, if available.

Report descriptive associations; no causal claims. A null result is a result.

### 10.5 Programme evaluation

The system can describe:

- 2 vs 3 sessions/week attendance and dose;
- volume changes;
- exercise substitutions;
- missed sessions and interruptions;
- periodisation blocks;
- ratio changes.

It cannot, from observational data alone, establish that one configuration is better. Confounding by readiness, selection, life stress and time is severe. Use the existing attendance, outcomes, prospective and reviews features; do not build a parallel experiment engine. No automatic programming recommendations.

---

## 11. Scientific evidence review

### 11.1 Evidence grades

| Grade | Meaning |
|---|---|
| A | Systematic review / meta-analysis / overview of reviews |
| B | Randomised or controlled trial |
| C | Observational, measurement or validation study |
| D | Biomechanical/mechanistic study |
| E | Narrative review, expert consensus or proposal |
| F | Engineering/product judgement |

A grade describes the **source**, not the strength of the inference for this athlete. A group-level meta-analysis does not validate an individual metric.

### 11.2 Required sources, verified

| # | Verified record | Design | What it supports | What it does not support | Grade |
|---|---|---|---|---|---|
| 1 | Currier BS, D'Souza AC, Singh MAF, Lowisz CV, Rawson ES, Schoenfeld BJ, Smith-Ryan AE, Steen JP, Thomas GA, Triplett NT, Washington TA, Werner TJ, Phillips SM. **American College of Sports Medicine Position Stand. Resistance Training Prescription for Muscle Function, Hypertrophy, and Physical Performance in Healthy Adults: An Overview of Reviews.** Med Sci Sports Exerc. 2026;58(4):851–872. DOI 10.1249/MSS.0000000000003897. PMID 41843416. | Overview of 137 systematic reviews, >30,000 participants | Resistance training improves strength, size, power, endurance, velocity, gait, balance and function. Strength was enhanced by ≥80% 1RM, full ROM, 2–3 sets, at the start of sessions, ≥2 sessions/week. Hypertrophy was enhanced by ≥10 sets/week and eccentric overload. Power was enhanced by 30–70% 1RM, low-to-moderate volume (≤24 reps·sets), Olympic-style lifting and fast concentric power training. Failure, equipment, complexity, set structure, TUT, BFR and periodisation did not consistently affect outcomes. | It does not validate an individual's %1RM, an e1RM formula, a session score or a ratio. The recommendations are group-level and heterogeneous. "Power" is not the same as box-jump quality. | A |
| 2 | Sweet TW, Foster C, McGuigan MR, Brice G. **Quantitation of resistance training using the session rating of perceived exertion method.** J Strength Cond Res. 2004;18(4):796–802. DOI 10.1519/14153.1. PMID 15574104. | Controlled validation, 20 habituated adults, aerobic and resistance bouts | Session RPE collected 30 min after exercise tracked relative intensity; resistance session RPE increased with %1RM despite less total work. Supports sRPE as an internal-load measure and the 30-min timing. | It does not validate an immediate end-of-workout rating, a session-load AU threshold, or a fatigue model. The sample is small and short-term. | B |
| 3 | Helms ER, Kwan K, Sousa CA, Cronin JB, Storey AG, Zourdos MC. **Methods for Regulating and Monitoring Resistance Training.** J Hum Kinet. 2020;74:23–42. DOI 10.2478/hukin-2020-0011. PMID 33312273. | Narrative review of 90 studies, 11 themes | Many monitoring methods exist; physiological, performance and perceptual measures can correlate strongly with performance, but practical methods are limited. Velocity, RIR-based RPE and jump height are practical; evidence for enhancing performance is preliminary. | It does not establish one best method or validate a composite. "Strong correlation" is not causal or individual-level. | E |
| 4 | Pelland JC, Robinson ZP, Remmert JF, Cerminaro RM, Benitez B, John TA, Helms ER, Zourdos MC. **Methods for Controlling and Reporting Resistance Training Proximity to Failure: Current Issues and Future Directions.** Sports Med. 2022;52(7):1461–1472. DOI 10.1007/s40279-022-01667-2. PMID 35247203. | Narrative/critical review | Proximity to failure has no consistent quantification. %1RM prescription produces wide per-set RIR variation; velocity loss–RIR relationships vary by set, load and exercise; self-reported RIR is subjective and often unreported. | It does not validate RIR as precise, velocity loss as a universal RIR proxy, or a single prescription method. | E |
| 5 | Robinson ZP, Pelland JC, Remmert JF, Refalo MC, Jukic I, Steele J, Zourdos MC. **Exploring the Dose-Response Relationship Between Estimated Resistance Training Proximity to Failure, Strength Gain, and Muscle Hypertrophy: A Series of Meta-Regressions.** Sports Med. 2024;54(9):2209–2231. DOI 10.1007/s40279-024-02069-2. PMID 38970765. | Exploratory multilevel meta-regressions | Strength gains were similar across a wide estimated-RIR range; hypertrophy tended to improve closer to failure. Supports keeping strength and hypertrophy interpretations distinct and a buffer rather than a tight RIR veto. | Estimated RIR was inferred from study descriptions, not measured; model fit was modest; it does not validate an individual's RIR or a specific target. | A |
| 6 | Pareja-Blanco F, Loturco I. **Level of Effort: A Practical Approach for Resistance Training Monitoring and Prescription.** J Hum Kinet. 2026;102:259–266. DOI 10.5114/jhk/221229. PMID 42211812. | Conceptual/practical proposal | Argues that identical RIR values may not represent equivalent stimuli across rep ranges; proposes "level of effort" as reps performed / max reps, quantified via fastest-rep velocity and velocity loss. | It is a proposal, not a validated monitoring metric. It does not establish that the composite predicts adaptation, nor that velocity loss is accurate for every lift (see the hex-bar evidence). | E |
| 7 | Sousa CA, Zourdos MC, Storey AG, Helms ER. **The Importance of Recovery in Resistance Training Microcycle Construction.** J Hum Kinet. 2024;91(Spec Issue):205–223. DOI 10.5114/jhk/186659. PMID 38689583. | Review of 24 studies | Failure may lengthen recovery; higher volume increases recovery demands; lower-body, multi-joint, eccentric and lengthened-position work may need longer; individual variation is wide. Supports cautious recovery interpretation and not assuming a high load always impairs performance. | It does not provide individual recovery windows or validate a session-load threshold. | E |
| 8 | Marchal A, Benazieb O, Weldegebriel Y, Méline T, Imbach F. **Statistical flaws of the fitness-fatigue sports performance prediction model.** Sci Rep. 2025;15:3706. DOI 10.1038/s41598-025-88153-7. PMID 39881202. | Bayesian re-analysis of two datasets with cross-validation | The fitness-fatigue model was ill-conditioned; fitness and fatigue parameters were poorly identifiable; adding fatigue parameters did not improve out-of-sample prediction (p > 0.40). Supports rejecting complex forecasting and requiring out-of-sample validation. | It does not prove every fatigue model is useless; it shows this model class is fragile on these data. | A/C |
| 9 | Scott BR, Duthie GM, Thornton HR, Dascombe BJ. **Training Monitoring for Resistance Exercise: Theory and Applications.** Sports Med. 2016;46(5):687–698. DOI 10.1007/s40279-015-0454-0. PMID 26780346. | Narrative review | Resistance training is complex; volume load, perceived intensity and subjective questionnaires are useful; no consensus on how to integrate them; velocity may be valuable. Supports a multi-dimensional, non-composite approach. | It does not validate a universal metric or a combined score. | E |

### 11.3 Additional sources used

| # | Verified record | Supports | Grade |
|---|---|---|---|
| 10 | Day ML, McGuigan MR, Brice G, Foster C. Monitoring exercise intensity during resistance training using the session RPE scale. J Strength Cond Res. 2004;18(2):353–358. DOI 10.1519/R-13113.1. PMID 15142026. | Session RPE reliability across resistance-training intensities (ICC 0.88). | B |
| 11 | Grgic J, Lazinica B, Schoenfeld BJ, Pedisic Z. Test-Retest Reliability of the One-Repetition Maximum (1RM) Strength Assessment: a Systematic Review. Sports Med Open. 2020;6(1):31. DOI 10.1186/s40798-020-00260-z. PMID 32681399. | 32 studies, median ICC 0.97, median CV 4.2%. The 4.2% reference band for "within typical variation". | A |
| 12 | Zourdos MC, Goldsmith JA, Helms ER, et al. Proximity to Failure and Total Repetitions Performed in a Set Influences Accuracy of Intraset Repetitions in Reserve-Based Rating of Perceived Exertion. J Strength Cond Res. 2021;35(2S):S158–S165. DOI 10.1519/JSC.0000000000002995. | RIR error grows with distance from failure (~2 reps at 1 RIR, ~3.7 at 3, ~5 at 5 in the squat). | B |
| 13 | Refalo MC, Remmert JF, Pelland JC, Robinson ZP, Zourdos MC, Hamilton DL, Fyfe JJ, Helms ER. Accuracy of Intraset Repetitions-in-Reserve Predictions During the Bench Press Exercise in Resistance-Trained Male and Female Subjects. J Strength Cond Res. 2024;38(3):e78–e85. DOI 10.1519/JSC.0000000000004653. PMID 37967832. | RIR prediction error is a property of the method, not just experience. | B |
| 14 | Reynolds JM, Gordon TJ, Robergs RA. Prediction of one repetition maximum strength from multiple repetition maximum testing and anthropometry. J Strength Cond Res. 2006;20(3):584–592. DOI 10.1519/R-15304.1. PMID 16937972. | 1RM prediction from multiple-RM testing has non-trivial standard error; accuracy varies by lift. | C |
| 15 | Mayhew JL, Johnson BD, Lamonte MJ, Lauber D, Kemmler W. Accuracy of prediction equations for determining one repetition maximum bench press in women before and after resistance training. J Strength Cond Res. 2008;22(5):1570–1577. DOI 10.1519/JSC.0b013e31817b02ad. PMID 18714230. | Prediction accuracy is population- and training-state-dependent; a single equation is not a measurement. | C |
| 16 | Jukic I, Castilla AP, Ramos AG, Van Hooren B, McGuigan MR, Helms ER. The Acute and Chronic Effects of Implementing Velocity Loss Thresholds During Resistance Training: A Systematic Review, Meta-Analysis, and Critical Evaluation of the Literature. Sports Med. 2023;53(1):177–214. DOI 10.1007/s40279-022-01754-4. PMID 36178597. | Velocity-loss thresholds trade volume against fatigue; higher loss is not automatically better. | A |
| 17 | Spitz RW, Gonzalez AM, Ghigiarelli JJ, Sell KM, Mangine GT. Load-Velocity Relationships of the Back vs. Front Squat Exercises in Resistance-Trained Men. J Strength Cond Res. 2019;33(2):301–306. DOI 10.1519/JSC.0000000000002962. PMID 30688871. | Front and back squat do not share a load–velocity relationship; variants are not interchangeable. | B |
| 18 | Lockie RG, Callaghan SJ, Moreno MR, et al. Relationships between Mechanical Variables in the Traditional and Close-Grip Bench Press. J Hum Kinet. 2017;60:19–28. DOI 10.1515/hukin-2017-0109. PMID 29339982. | Close-grip and traditional bench differ mechanically; supports separate identity. | B |
| 19 | Herrera-Bermudo JC, Puente-Alcaraz C, Díaz-Sánchez P, González-Badillo JJ, Rodríguez-Rosell D. Influence of Grip Width on the Load-Velocity Relationship and 1RM in the Bench Press. J Strength Cond Res. 2024;38(12):2013–2021. DOI 10.1519/JSC.0000000000004920. PMID 39178098. | Grip width changes the load–velocity relationship and 1RM; equipment/execution changes break comparability. | B |
| 20 | Parkinson AO, Apps CL, Morris JG, Barnett CT, Lewis MGC. The Calculation, Thresholds and Reporting of Inter-Limb Strength Asymmetry: A Systematic Review. J Sports Sci Med. 2021;20(4):594–617. DOI 10.52082/jssm.2021.594. PMID 35321131. | Strength-ratio calculation, thresholds and reporting are inconsistent; supports no universal ratio target. | A |
| 21 | Impellizzeri FM, Tenan MS, Kempton T, Novak A, Coutts AJ. Acute:Chronic Workload Ratio: Conceptual Issues and Fundamental Pitfalls. Int J Sports Physiol Perform. 2020;15(6):907–913. DOI 10.1123/ijspp.2019-0864. PMID 32502973. | ACWR has conceptual and statistical problems; supports descriptive-only use. | E |
| 22 | Morán-Navarro R, Pérez CE, Mora-Rodríguez R, et al. Time course of recovery following resistance training leading or not to failure. Eur J Appl Physiol. 2017;117(12):2387–2399. DOI 10.1007/s00421-017-3725-7. PMID 28965198. | Failure slowed recovery of jump height and bar velocity at 24–48 h versus equal-volume non-failure sets. | B |
| 23 | Balachandran AT, Steele J, Angielczyk D, et al. Comparison of Power Training vs Traditional Strength Training on Physical Function in Older Adults: A Systematic Review and Meta-analysis. JAMA Netw Open. 2022;5(5):e2211623. DOI 10.1001/jamanetworkopen.2022.11623. PMID 35544136. | Power training modestly improves physical function vs traditional strength training in older adults (low certainty). Supports a separate power domain, but the population is older adults. | A |
| 24 | El Hadouchi M, Kiers H, de Vries R, Veenhof C, van Dieën J. Effectiveness of power training compared to strength training in older adults: a systematic review and meta-analysis. Eur Rev Aging Phys Act. 2022;19:18. DOI 10.1186/s11556-022-00297-x. PMID 35953775. | Power training improves muscle power (SMD 0.99) and activity tests in older adults. Same population caveat. | A |
| 25 | Swinton PA, Stewart A, Agouris I, Keogh JW, Lloyd R. A biomechanical analysis of straight and hexagonal barbell deadlifts using submaximal loads. J Strength Cond Res. 2011. DOI 10.1519/JSC.0b013e3181e73f87. | Trap bar produced lower peak lumbar, hip and ankle moments; supports a lower ordinal spinal cost than a straight bar. | D |
| 26 | Hanen NC, Ben Mansour K, Ertel GN, Duchene Y, Gauchard GC. Biomechanical analysis of conventional and sumo deadlift. Front Bioeng Biotechnol. 2025. DOI 10.3389/fbioe.2025.1597209. | Sumo had lower erector spinae activation and more upright posture but greater frontal/transverse moments; supports ordinal, not a load measurement. | D |
| 27 | Cholewicki J, McGill SM, Norman RW. Lumbar spine loads during the lifting of extremely heavy weights. Med Sci Sports Exerc. 1991;23(10):1179–1186. DOI 10.1249/00005768-199110000-00012. | Heavy deadlifting loads the lumbar spine; sumo reduced but did not remove the load. Supports "axial demand is real", not a per-exercise score. | D |
| 28 | Wiedenmann T, Kunellis D, Rappelt L, Held S, Wicker P, Donath L. Trainability of repetitions-in-reserve estimation in younger and older adults: a parallel-group repeated-measures study. BMC Sports Sci Med Rehabil. 2026;18(1):375. DOI 10.1186/s13102-026-01997-y. PMID 42632893. | RIR estimation error decreases with practice (up to ~2.3 reps); supports a buffer, not a tight veto. | B |
| 29 | Moura RE, Bezerra da Silva RF, Gomes LMS, Ramos da Silva JL, Henrique RDS, Sousa FAB, Fonseca FS. Monitoring Bar Velocity to Quantify Fatigue in Resistance Training. Int J Sports Med. 2024;45(8):624–632. DOI 10.1055/a-2316-7966. PMID 38684188. | Back-squat mean propulsive velocity was sensitive to acute fatigue, especially at 40% and 80% 1RM; supports velocity as context. | B |
| 30 | Refalo MC, Helms ER, Trexler ET, Hamilton DL, Fyfe JJ. Influence of Resistance Training Proximity-to-Failure on Skeletal Muscle Hypertrophy: A Systematic Review with Meta-analysis. Sports Med. 2023;53(3):649–665. DOI 10.1007/s40279-022-01784-y. PMID 36334240. | No hypertrophy advantage for momentary failure over non-failure; no advantage of >25% over 20–25% velocity loss. Supports not treating failure as mandatory. | A |

### 11.4 What the evidence does not establish

- No source validates a **composite 0–100 workout score**.
- No source validates **cross-exercise e1RM ratios** as a weakness diagnosis or a predictor of main-lift performance. The evidence supports specificity and descriptive profiling, not diagnosis.
- No source validates **session load AU** as an objective physiological stress or a precise recovery dose.
- No source validates **mean velocity per set** as a within-set velocity-loss measure.
- No source validates **RIR** as precise enough to compare 1-rep differences.
- No source validates **productivity** as a workload or a predictor; it is a product hypothesis.
- No source validates **spinal_cost** as lumbar compression/shear or as an injury probability.

### 11.4a Evidence gaps specific to this proposal

| Question | What exists | What is missing |
|---|---|---|
| Does a within-session e1RM change measure adaptation? | No. It is a re-estimate from a different set. Indirect context: bar velocity is sensitive to acute fatigue (Moura 2024), and RIR error is large (Zourdos 2021; Refalo 2024). | No study validates a pre/post e1RM difference as a meaningful performance change, and none establishes a minimal detectable change for Epley+RIR. The 4.2% direct-1RM CV is a reference, not a validated e1RM threshold. |
| Does an accessory-to-main ratio explain main-lift performance? | Specificity evidence (Spitz 2019; Lockie 2017; Herrera-Bermudo 2024) and ratio-reporting inconsistency (Parkinson 2021). | No prospective study showing that a ratio change predicts a main-lift change, or that targeting a ratio improves the main lift. |
| Does session load AU predict recovery or adaptation? | sRPE is a reliable internal-load rating (Sweet 2004; Day 2004). | No resistance-training study validates AU thresholds, a dose-response curve, or an individual recovery window. |
| Does power quality relate to adaptation? | Power training improves power/function in older adults (Balachandran 2022; El Hadouchi 2022); velocity loss has trade-offs (Jukic 2023). | No validated field metric for jump quality in this athlete, and no within-set loss from mean velocity. |
| Does spinal ordinal cost predict injury? | Biomechanical load is real (Cholewicki 1991; Swinton 2011; Hanen 2025). | No validated mapping from the ordinal cost to injury probability; no individual load threshold. |

### 11.5 Evidence-to-design trace

| Design choice | Evidence | Grade | Confidence |
|---|---|---|---|
| Keep domains separate | Scott 2016; Helms 2020; ACSM 2026 | A/E | High |
| sRPE × duration as internal load | Sweet 2004; Day 2004 | B | Moderate |
| Label immediate sRPE | Sweet 2004; Day 2004 | B | High (the protocol difference is clear) |
| e1RM as estimate, not measurement | Reynolds 2006; Mayhew 2008; Grgic 2020 | C/A | High |
| 4.2% "typical variation" reference | Grgic 2020 | A | Moderate (population, not individual) |
| Best-set pre/post comparison | Measurement logic; no direct trial | F | Moderate |
| RIR distribution, no mean | Zourdos 2021; Refalo 2024; Pelland 2022 | B/E | High |
| Hard sets RIR ≤4 | Existing config; ACSM/Robinson | A/F | Moderate |
| Relative-intensity bands | ACSM 2026 (80%); other cuts product judgement | A/F | Low–moderate |
| Tonnage within exercise only | Mechanics; ACSM volume load discussion | F | High (as a limitation) |
| Power separate, 30–70% 1RM, low volume | ACSM 2026; Balachandran 2022; El Hadouchi 2022 | A | Moderate (population caveat) |
| No within-set velocity loss | DEC-VELOCITY-01; mean-only data | F | High |
| Spinal ordinal, not load | Swinton 2011; Hanen 2025; Cholewicki 1991; SPINAL-COST | D | High (as ordinal) |
| Ratios descriptive only | PARENT-VARIANT-WEAKNESS-EVIDENCE; Parkinson 2021; Spitz 2019 | A/E | High |
| No fitness-fatigue controller | Marchal 2025; RETROSPECTIVE-VALIDATION | A/C | High |
| Productivity optional, subjective | No direct validation | F | Low |

---


### 11.6 Direct links for the verified sources

- [ACSM 2026 overview of reviews](https://doi.org/10.1249/MSS.0000000000003897) · [PubMed 41843416](https://pubmed.ncbi.nlm.nih.gov/41843416/)
- [Sweet 2004, session RPE](https://doi.org/10.1519/14153.1) · [PubMed 15574104](https://pubmed.ncbi.nlm.nih.gov/15574104/)
- [Helms 2020, methods for regulating and monitoring](https://doi.org/10.2478/hukin-2020-0011) · [PubMed 33312273](https://pubmed.ncbi.nlm.nih.gov/33312273/)
- [Pelland 2022, proximity to failure](https://doi.org/10.1007/s40279-022-01667-2) · [PubMed 35247203](https://pubmed.ncbi.nlm.nih.gov/35247203/)
- [Robinson 2024, dose-response meta-regressions](https://doi.org/10.1007/s40279-024-02069-2) · [PubMed 38970765](https://pubmed.ncbi.nlm.nih.gov/38970765/)
- [Pareja-Blanco & Loturco 2026, level of effort](https://doi.org/10.5114/jhk/221229) · [PubMed 42211812](https://pubmed.ncbi.nlm.nih.gov/42211812/)
- [Sousa 2024, recovery in microcycle construction](https://doi.org/10.5114/jhk/186659) · [PubMed 38689583](https://pubmed.ncbi.nlm.nih.gov/38689583/)
- [Marchal 2025, statistical flaws of fitness-fatigue](https://doi.org/10.1038/s41598-025-88153-7) · [PubMed 39881202](https://pubmed.ncbi.nlm.nih.gov/39881202/)
- [Scott 2016, training monitoring for resistance exercise](https://doi.org/10.1007/s40279-015-0454-0) · [PubMed 26780346](https://pubmed.ncbi.nlm.nih.gov/26780346/)
- [Day 2004, session RPE scale](https://doi.org/10.1519/R-13113.1) · [PubMed 15142026](https://pubmed.ncbi.nlm.nih.gov/15142026/)
- [Grgic 2020, 1RM test-retest reliability](https://doi.org/10.1186/s40798-020-00260-z) · [PubMed 32681399](https://pubmed.ncbi.nlm.nih.gov/32681399/)
- [Zourdos 2021, intraset RIR accuracy](https://doi.org/10.1519/JSC.0000000000002995)
- [Refalo 2024, bench press RIR accuracy](https://doi.org/10.1519/JSC.0000000000004653) · [PubMed 37967832](https://pubmed.ncbi.nlm.nih.gov/37967832/)
- [Reynolds 2006, 1RM prediction](https://doi.org/10.1519/R-15304.1) · [PubMed 16937972](https://pubmed.ncbi.nlm.nih.gov/16937972/)
- [Mayhew 2008, bench press prediction equations](https://doi.org/10.1519/JSC.0b013e31817b02ad) · [PubMed 18714230](https://pubmed.ncbi.nlm.nih.gov/18714230/)
- [Jukic 2023, velocity-loss thresholds](https://doi.org/10.1007/s40279-022-01754-4) · [PubMed 36178597](https://pubmed.ncbi.nlm.nih.gov/36178597/)
- [Spitz 2019, front vs back squat load-velocity](https://doi.org/10.1519/JSC.0000000000002962) · [PubMed 30688871](https://pubmed.ncbi.nlm.nih.gov/30688871/)
- [Lockie 2017, traditional vs close-grip bench](https://doi.org/10.1515/hukin-2017-0109) · [PubMed 29339982](https://pubmed.ncbi.nlm.nih.gov/29339982/)
- [Herrera-Bermudo 2024, grip width and 1RM](https://doi.org/10.1519/JSC.0000000000004920) · [PubMed 39178098](https://pubmed.ncbi.nlm.nih.gov/39178098/)
- [Parkinson 2021, inter-limb asymmetry review](https://doi.org/10.52082/jssm.2021.594) · [PubMed 35321131](https://pubmed.ncbi.nlm.nih.gov/35321131/)
- [Impellizzeri 2020, ACWR pitfalls](https://doi.org/10.1123/ijspp.2019-0864) · [PubMed 32502973](https://pubmed.ncbi.nlm.nih.gov/32502973/)
- [Morán-Navarro 2017, recovery after failure](https://doi.org/10.1007/s00421-017-3725-7) · [PubMed 28965198](https://pubmed.ncbi.nlm.nih.gov/28965198/)
- [Balachandran 2022, power vs strength training](https://doi.org/10.1001/jamanetworkopen.2022.11623) · [PubMed 35544136](https://pubmed.ncbi.nlm.nih.gov/35544136/)
- [El Hadouchi 2022, power training review](https://doi.org/10.1186/s11556-022-00297-x) · [PubMed 35953775](https://pubmed.ncbi.nlm.nih.gov/35953775/)
- [Swinton 2011, straight vs hex bar](https://doi.org/10.1519/JSC.0b013e3181e73f87)
- [Hanen 2025, conventional vs sumo](https://doi.org/10.3389/fbioe.2025.1597209)
- [Cholewicki 1991, lumbar loads in heavy lifting](https://doi.org/10.1249/00005768-199110000-00012)
- [Wiedenmann 2026, RIR trainability](https://doi.org/10.1186/s13102-026-01997-y) · [PubMed 42632893](https://pubmed.ncbi.nlm.nih.gov/42632893/)
- [Moura 2024, bar velocity and fatigue](https://doi.org/10.1055/a-2316-7966) · [PubMed 38684188](https://pubmed.ncbi.nlm.nih.gov/38684188/)
- [Refalo 2023, proximity to failure and hypertrophy](https://doi.org/10.1007/s40279-022-01784-y) · [PubMed 36334240](https://pubmed.ncbi.nlm.nih.gov/36334240/)

## 12. Validation methodology

### 12.1 Stage 1 — Measurement validity

Test that the calculations reflect the data. Required unit tests:

| Test | Setup | Expected |
|---|---|---|
| Warm-up exclusion | RIR 6 set + RIR 2 set | Warm-up excluded from working sets, e1RM, RI, hard sets; counted as warm-up |
| Working-set classification | RIR null + RIR 5 | Both working; RIR null contributes to unknown; RIR 5 not hard |
| RIR off-scale | RIR -1, 7, 99 | Classified missing/off-scale; not hard |
| Load basis | external / bodyweight_total / added / unknown | Correct total/external/tonnage; unknown → not applicable |
| Bodyweight missing | added-load set, no bodyweight | e1RM/RI unavailable; set still counts |
| e1RM eligibility | 20 reps + RIR 5 | Rejected for headline (reps+rir >20) |
| e1RM eligibility | 11 reps @ RIR 2 | Degraded; not headline |
| e1RM eligibility | 3 reps @ RIR 0 | ok, flagged suspect |
| Pre/post separation | Compute pre, then add current sets, recompute | Pre unchanged |
| Same-date ordering | Two workouts same date, one earlier start | Earlier included; later not |
| Post source | Two eligible sets | Best selected; source set correct |
| Post missing | Only warm-up/unknown RIR | Unavailable, not 0 |
| Velocity quality | 0.000000 | velocity_present = false; not a measurement |
| Power exclusion | Box jump set | Not in RIR/RI/hard-set counts; counted in power |
| Substitution | Plan A, actual B | Completion against modified plan; original comparison shows A missing; no e1RM mapping |
| Partial workout | 3/4 sets | Status under; no zero dose |
| Missing feedback | No feedback row | Session load unknown; not 0 |
| Feedback merge | Row 1 sRPE+duration, row 2 sRPE only | sRPE from row 2, duration from row 1; flag |
| Manual duration | duration_source=manual | Session load computed; manual flag |
| Ratio gap | 40-day gap | Unavailable/historical; no current ratio |
| Ratio one-sided | Missing denominator | Unavailable |
| Spinal reuse | Session with 3 spinal exercises | Effective cost equals registry output |
| No composite | API payload | No score, workload, fatigue or quality scalar added |

Representative edge cases: empty session, one-set session, all-warm-up session, all-RIR-missing session, bodyweight-only session, test-only session, timed-only session, session with a 1015-rep typo (quarantined/flagged), session with a 0 load on an external lift, session with a negative load (invalid).

### 12.2 Stage 2 — Construct validity

Check that each metric behaves like what it claims:

- **External dose** changes only when completed working sets/reps/load change; it is invariant to prescribed changes.
- **Internal load** changes with sRPE and duration, and is independent of tonnage (except through perception).
- **e1RM** changes when the underlying set changes; it is invariant to unrelated exercises; it does not change when only the plan changes.
- **Relative strength** changes only when one of the two configured e1RMs changes; it is unavailable when either is stale.
- **Power exposure** counts only power-classified sets; it does not increase hypertrophy hard sets.
- **Axial/spinal exposure** equals the registry output; it is invariant to tonnage.
- **Productivity** is independent of every objective metric in the payload; it is not used in any calculation.

Add a **negative test**: search the API/UI payload for a composite key and assert absence. This is a permanent guardrail.

### 12.3 Stage 3 — Predictive validity

Only if a metric is claimed to predict. Requirements:

- chronological out-of-sample validation (walk-forward), never random splits;
- baselines: last eligible observation, rolling median of 3, comparable-session median, exercise-specific mean;
- report n, missingness, horizon, MAE (and RMSE/bias if useful), baseline comparison, stability across exercises and time periods;
- a complex model is retained only if it materially and consistently beats the baseline; "materially" must be defined before the analysis (e.g., ≥10% MAE reduction and no exercise with a worse result);
- no causal claims;
- no automatic prescription change.

The existing RETROSPECTIVE-VALIDATION.md and fatigue_fitness backtest are the precedent: a model that loses to persistence is not adopted.

### 12.4 Stage 4 — Prospective validation

Before any metric influences programming, collect prospectively:

- 12–16 weeks of sessions with sRPE, duration and productivity;
- measured 3RM/5RM tests for the main lifts (at least 3 per lift) to estimate e1RM bias;
- power quality-stop events and, where available, per-rep velocity;
- exercise substitutions and interruptions;
- a pre-registered analysis plan with a primary outcome and a small number of exposures.

Do not change prescriptions, deloads, exercise selection or injury rules during this period. Do not peek and adjust the plan without recording it.

### 12.5 Acceptance criteria for the measurement layer

- All Stage 1 tests pass.
- No existing golden prescription changes.
- No new composite scalar in any API response.
- Every "unavailable" state is rendered as such, not as 0.
- Every headline estimate exposes its method and source.
- ruff check . and python -m pytest pass at the end of the phase.

---

## 13. Phased implementation roadmap

### Phase 1 — Definitions and shared measurement core

**Scope**

- Extract the e1RM selector into features/e1rm_source.py.
- Add features/monitoring.py pure definitions and config/monitoring.v1.yaml.
- Add config/strength-relationships.v1.yaml (config only; no UI).
- Add conformance fixtures and Stage 1 tests.
- No user-visible feature, no migration.

**Dependencies**

- Agreement on §4–§8 definitions.
- Existing clean_set columns; no new data.

**Files**

- New: strength_coach/features/e1rm_source.py, strength_coach/features/monitoring.py, config/monitoring.v1.yaml, config/strength-relationships.v1.yaml, tests/test_monitoring_definitions.py, tests/test_e1rm_source_shared.py.
- Modified: strength_coach/prescribe/engine.py (import the shared selector; behaviour-preserving), strength_coach/features/derived.py (add the reps+rir guard for the monitoring path only, or a separate helper), strength_coach/features/progress.py (fix e1rm_applicable if the shared selector is used there).

**Schema changes**

- None.

**Testing**

- All existing e1RM/calibration/prescription tests.
- New tests for eligibility, cutoff, quality, missingness, and no-composite.
- Property test: pre estimate invariant to current-session sets.

**Acceptance criteria**

- Golden prescriptions byte-identical.
- The shared selector reproduces _latest_e1rm for the same inputs.
- Every metric has a definition, status and flag in the config.
- ruff and tests pass.

**Scientific limitations**

- Bands, windows and quality cuts are assumptions; register them.
- The 4.2% reference is population-level.

### Phase 2 — Descriptive workout summary

**Scope**

- API GET /api/workout/<id>/summary and CLI summary.
- UI sections 1, 2, 3, 5, and a condensed 4.
- e1RM pre/post, relative intensity, RIR distribution, hard sets, tonnage per exercise, session load AU.
- Optional productivity (see migration).

**Dependencies**

- Phase 1.
- Decision on productivity and on the 30-min sRPE protocol.

**Files**

- New: strength_coach/features/session_summary.py (or in monitoring), strength_coach/web/static/summary.js, tests/test_session_summary.py, tests/test_web_summary.py.
- Modified: strength_coach/web/server.py, strength_coach/cli.py, strength_coach/workout.py (plan JSON fields), strength_coach/web/static/workout.js (end form + render), strength_coach/web/static/index.html (markup), strength_coach/features/session_feedback.py (merge/productivity).

**Schema changes**

- ALTER TABLE session_feedback ADD COLUMN productivity INTEGER with CHECK (productivity IS NULL OR productivity BETWEEN 1 AND 5), if Domain G is approved. This is the only migration.
- If the 30-min protocol is adopted, add srpe_timing; otherwise do not.

**Testing**

- API contract, missing data, source transparency, manual duration, late feedback, productivity skip, no composite.
- UI rendering tests for "Unavailable"/"Not recorded".

**Acceptance criteria**

- The summary is read-only and deterministic.
- Every number is traceable to a set, feedback row or registry call.
- No automatic prescription change.
- The existing end-screen comparison is preserved.

**Scientific limitations**

- Within-session change is not adaptation.
- Session load is internal, not objective stress.
- Tonnage is exercise-specific.
- Power quality is not measurable from mean velocity.

### Phase 3 — Historical strength and workload trends

**Scope**

- Performance view: e1RM series, rolling median, exercise filters, series breaks.
- Dose trends: hard sets, relative intensity, tonnage per exercise, session load.
- Accessory-to-main ratios (configured, date-stamped).
- Comparable-session comparison.
- CLI performance with parity.

**Dependencies**

- Phase 2.
- Relationship config approved.

**Files**

- New: strength_coach/features/strength_trend.py, strength_coach/features/relative_strength.py, strength_coach/web/static/performance.js, tests/test_strength_trend.py, tests/test_relative_strength.py.
- Modified: web/server.py, cli.py, index.html, app.js (navigation).

**Schema changes**

- None.

**Testing**

- Sparse data: 1, 2, 3, 5 points.
- Series break on identity/equipment change.
- No interpolation.
- Ratio gap/staleness/one-sided.
- No target ratio, no ranking.

**Acceptance criteria**

- Trend lines only with ≥3 observations.
- No statement of change with <5 observations.
- Ratio unavailable when dates are too far apart.
- Every ratio displays both dates and both estimates.

**Scientific limitations**

- Rolling median is descriptive, not a model.
- Ratios have no diagnostic validity.
- Cross-exercise comparisons are limited by specificity.

### Phase 4 — Exploratory modelling

**Scope**

- Descriptive dose–response and recovery associations.
- Pre-registered, small set of exposures/outcomes.
- Reports, not controllers.
- Compare against simple baselines.

**Dependencies**

- Phase 3; enough data; a written pre-registration.

**Files**

- New: tools/monitoring_analysis.py (or a features/monitoring_analysis.py), docs/MONITORING-ANALYSIS.md (result report, when run).
- No UI or prescription changes.

**Schema changes**

- None.

**Testing**

- Unit tests for lag construction, missingness, baseline comparison.
- Reproducible output with a seed.

**Acceptance criteria**

- n, missingness, effect size and uncertainty reported.
- No causal language.
- No model retained without out-of-sample improvement over baselines.
- No automatic change.

**Scientific limitations**

- Observational; confounding; multiple comparisons; short series.

### Phase 5 — Prospective validation

**Scope**

- Collect the data needed to validate the metrics before any programming influence.
- Pre-register the analysis.
- No feature changes beyond capture.

**Dependencies**

- Phase 4; a decision that a metric is a candidate for prediction.

**Files**

- Capture changes only if justified: session_feedback.srpe_timing, structured power quality event, per-rep velocity capture.
- docs/MONITORING-PROSPECTIVE.md (protocol and results).

**Schema changes**

- Only if a capture gap is proven (e.g., sRPE timing, structured quality stop). Do not add speculative fields.

**Testing**

- Capture completeness; no default values; no missing-to-zero.
- Analysis reproduces the pre-registered plan.

**Acceptance criteria**

- 12–16 weeks of prospective data.
- Pre-registered primary outcome.
- Out-of-sample comparison against baselines.
- No programming change until the gate is met.

**Scientific limitations**

- One athlete; N-of-1; limited generalisability.
- Prospective data collection changes behaviour (Hawthorne effect).

### Deferred phases/features

- Velocity-loss-based autoregulation.
- Injury-risk prediction.
- Automatic deload/prescription changes.
- Population percentile comparisons.
- A universal score.
- Complex forecasting.
- Jump height/contact time (unless a device is added and the question is pre-registered).

---

## 14. Open design decisions and unresolved questions

| # | Decision | Options | Recommendation | Evidence | Revisit if |
|---|---|---|---|---|---|
| Q1 | Pre/post estimator | median vs best vs most recent | **Best eligible set for both**, with load base kept separate | Measurement logic; Grgic 2020 | Measured tests show the best set is unstable |
| Q2 | "Meaningful change" band | none / 4.2% / athlete-specific | **4.2% default**, athlete-specific once ≥3 tests exist | Grgic 2020 | Calibration data show a different error |
| Q3 | Ratio gap window | 7 / 14 / 28 days | **14 days**, configurable | Product judgement | Paired data show 14 days is too short/long |
| Q4 | Productivity scale | 5-point / 7-point / free text | **5-point labelled**, optional | Product judgement | Users find it ambiguous |
| Q5 | sRPE timing | immediate / 30 min / both | **Keep immediate, label it; add delayed later** | Sweet 2004; Day 2004 | Friction data show a delayed value is feasible |
| Q6 | Session tonnage total | hide / advanced / headline | **Advanced only**, with a caveat | Mechanics; ACSM | Users need a total for a specific comparison |
| Q7 | Ratios on the end screen | none / 2 / all | **Max 2, only if contemporaneous and reliable** | PARENT-VARIANT evidence | The Performance view is enough |
| Q8 | Performance view location | new page / Outcomes / Today | **New top-level Performance page** | UI complexity | The page becomes too large |
| Q9 | Persist derived metrics | yes / no | **No**, recompute; cache in memory only | Single source of truth | Performance becomes a problem |
| Q10 | Same-date multiple sessions | include / exclude | **Include only with a proven earlier start**, else exclude | No timestamps for imports | Timestamps are captured for all sessions |
| Q11 | Tests in the e1RM series | include / separate | **Include as observations, mark as test**; do not mix with ordinary volume | ACSM; high-intensity plan | Tests distort the trend |
| Q12 | RIR 5 | hard / not hard / unknown | **Not hard; keep as a working set** | DQ-RIR-03 | The athlete confirms a different meaning |
| Q13 | Relative intensity for accessories | show / hide | **Show when a load base exists**, else "unavailable" | ACSM | Accessory data are too sparse |
| Q14 | Bodyweight total for added | fix read / leave | **Fix the read path** before bodyweight e1RM | DEC-LOAD-02 | No bodyweight e1RM is ever used |
| Q15 | Power quality stop | infer from velocity / require event | **Require an event; no inference** | DEC-POWER-02 | A validated velocity rule exists |
| Q16 | Comparable-session key | date / type+lift / type+lift+overlap | **Type + common main lift + overlap + exclusions** | Product judgement | Too few comparisons |
| Q17 | Productivity in analysis | no / descriptive only | **Descriptive only** | No validation | Prospective data support a hypothesis |
| Q18 | Warm-up display | hide / count | **Count separately**, never in dose | DEC-RIR-01 | None |
| Q19 | e1RM display precision | 0.1 / 0.5 / integer | **0.5 kg** | Measurement error | None |
| Q20 | Late feedback threshold | 24 h / 7 days / none | **24 h for live workouts**, N/A for imports | Product judgement | Data show a different pattern |

---

## 15. Features that should NOT be implemented yet

The following are explicitly **out of scope** and should be rejected in review unless new evidence and a new decision record appear.

1. **A universal 0–100 workout effort, workload, quality, stimulus or fatigue score.** No validation; would combine incommensurable constructs.
2. **A composite readiness/fatigue/performance score.** Readiness already exists as a bounded heuristic; do not multiply constructs.
3. **ACWR-based injury-risk prediction or a "sweet spot" recommendation.** The project already rejected this (DEC-ACWR-01, DEC-EXPOSURE-02); the ratio stays descriptive.
4. **Automatic prescription changes** from any new metric: load, sets, RIR, deload, exercise selection or substitution.
5. **A "strength gain" label for a within-session e1RM change.** It is an estimate, not adaptation.
6. **A "weakness" diagnosis from an accessory-to-main ratio.** Ratios are descriptive relative performance.
7. **Universal target ratios or population percentiles.** No validated individual targets.
8. **Cross-exercise e1RM conversion** (trap bar ↔ sumo ↔ conventional; SSB ↔ competition squat; bench ↔ close-grip). Identity is explicit.
9. **Within-set velocity loss from mean velocity.** Not computable; DEC-VELOCITY-01.
10. **RIR inference from velocity, reps or RPE.** No validated per-set conversion; do not impute.
11. **A "quality-limited" power claim without a recorded quality stop.** Mean velocity alone is insufficient.
12. **A measured spinal load (newtons, compression, shear) or an injury probability.** The ordinal cost is not a measurement.
13. **Aggregating tonnage across unrelated exercises into a universal workload.** Exercise-mix dependent.
14. **Treating a test/max attempt as ordinary hypertrophy volume.** It is a separate exposure.
15. **Productivity as a workload, stimulus, readiness or prescription input.** It is a subjective single item.
16. **A complex fitness-fatigue or machine-learning forecast.** The existing model was rejected; Marchal 2025 documents the statistical problems.
17. **A population benchmark or "normal range" for e1RM, ratios or session load.** The app is for one athlete.
18. **A ranking of exercises by tonnage or "effectiveness".** Mechanics and load basis differ.
19. **A session "completion score"** beyond the existing status counts. Completion is descriptive.
20. **A new database table for derived metrics, ratios or summaries.** Compute on read; avoid a second source of truth.
21. **A required new wearable/telemetry integration.** Optional per-rep velocity exists; do not make it mandatory.
22. **A change to the rubric weights or composite** to accommodate monitoring. Keep the rubric separate.
23. **A change to the volume ledger landmarks** based on the new metrics. They remain config assumptions.
24. **A change to the spinal cap** based on the new metrics. It remains an ordinal guard.

---


## 16. Worked numerical examples

All examples are synthetic. They use the Epley+RIR convention load × (1 + (reps + rir)/30), rounded for display only.

### 16.1 Relative intensity

Inputs:

- load_base_e1rm (competition squat, median 28-day, decayed) = **150.0 kg**.
- Set A: 120 kg × 5 @ RIR 2.
- Set B: 127.5 kg × 4 @ RIR 1.
- Set C: 105 kg × 8 @ RIR 3.

Calculation:

- A: 120 / 150 = 0.800 = **80.0%** → heavy.
- B: 127.5 / 150 = 0.850 = **85.0%** → heavy.
- C: 105 / 150 = 0.700 = **70.0%** → moderate.

Interpretation: three of three working sets have a denominator; distribution 2 heavy, 1 moderate, 0 unknown. Do not say "average intensity 78.3%" unless you also show the distribution; the average hides the range and weights sets equally. Do not use the best recent e1RM (156.0) as the denominator; that would produce 76.9/81.7/67.3 and would not match the load base the prescription used.

### 16.2 Session load

Inputs: sRPE = **7**, duration = **65 min**.

Calculation: 7 × 65 = **455 AU**.

Interpretation: internal load, arbitrary units, same athlete only. If duration is missing, the result is **unknown**, not 0. If sRPE is missing, **unknown**. If the feedback was recorded 3 days later, still 455 AU with FEEDBACK_LATE; do not "correct" it. If duration is 130 min (unusually long), 910 AU with LONG_SESSION; no automatic adjustment.

### 16.3 Hard-set classification

Working sets: RIR 2, 3, 4, 5, missing.

- Hard sets (RIR ≤ 4): **3** (RIR 2, 3, 4).
- Near-failure sets (RIR ≤ 2): **1**.
- Unknown: **1** (the missing RIR).
- RIR 5: not hard.
- A warm-up RIR 6 is excluded from the working set count entirely.

If all five had missing RIR, the hard-set result is **unknown**, not 0. If the session had five working sets all at RIR 5, the hard-set result is a valid **0**, with RIR 5 sets shown.

### 16.4 Pre/post e1RM and change

Pre-session best eligible set (2026-10-20):

- 130 kg × 4 @ RIR 2 → 130 × (1 + 6/30) = 130 × 1.2 = 156.0 kg.
- Quality: reps ≤10, RIR ≤3 → ok.
- Age at session (2026-10-28): 8 days → decay factor 1.0 (within the 21-day grace).
- pre_best = 156.0 kg.

Post-session best eligible set (set 2):

- 140 kg × 3 @ RIR 1 → 140 × (1 + 4/30) = 140 × 1.1333 = 158.67 → 158.7 kg.
- Quality: ok.
- post_best = 158.7 kg.

Change:

- Absolute: 158.7 − 156.0 = +2.7 kg.
- Percentage: 2.7 / 156.0 × 100 = +1.73%.
- The 4.2% reference: 1.73% < 4.2% → **within typical test–retest variation; no clear change**.
- Do not say "strength increased". Do say "the best estimate today was 2.7 kg higher; this is within typical variation".

A clearer increase:

- Post 150 kg × 2 @ RIR 1 → 150 × (1 + 3/30) = 165.0 kg.
- Δ = +9.0 kg; % = +5.77% → above 4.2% → "larger than typical test–retest variation, but still an estimate; not evidence of adaptation".

A decrease:

- Pre 174.0 kg (145 × 4 @ RIR 2 → 145 × 1.2 = 174.0).
- Post 140 kg × 2 @ RIR 2 → 140 × (1 + 4/30) = 158.67 kg.
- Δ = −15.3 kg; % = −8.8% → clear decrease. Possible explanations: fatigue, set selection, RIR error, technique, readiness. Do not say "lost strength".

Unavailable cases:

- No eligible pre set → pre unavailable; do not use post as pre.
- No eligible post set → post unavailable; do not use a warm-up or another exercise.
- Post only 100 kg × 15 @ RIR 5 → 15 + 5 = 20, reps > 10, rir > 3 → degraded/invalid for the headline; not used.

### 16.5 e1RM absolute and percentage change

The formula is in §16.4. Additional cases:

| Case | Pre | Post | Δ kg | Δ % | Label |
|---|---:|---:|---:|---:|---|
| Within noise | 156.0 | 158.7 | +2.7 | +1.73% | Within typical variation |
| Just above | 174.0 | 181.3 | +7.3 | +4.20% | Borderline; larger than typical variation |
| Clear increase | 156.0 | 165.0 | +9.0 | +5.77% | Larger than typical variation |
| Clear decrease | 174.0 | 158.7 | −15.3 | −8.79% | Larger than typical variation |
| No pre | — | 158.7 | — | — | Unavailable |
| No post | 156.0 | — | — | — | Unavailable |

The labels are descriptive. A "clear increase" is still an estimate, not proof of adaptation.

### 16.6 Exercise-specific tonnage

Bench press working sets:

- 120 kg × 5 = 600 kg
- 125 kg × 4 = 500 kg
- 110 kg × 8 = 880 kg
- Total = **1,980 kg**

Pull-up with added load:

- +10 kg × 8 = **80 kg** tonnage (not (bodyweight + 10) × 8).
- If bodyweight is 80 kg, total mass is 90 kg; e1RM/relative intensity use 90 kg, tonnage uses 10 kg.

Do not add 1,980 kg (bench) to a squat tonnage and call it "session workload". If a total is shown, label it and restrict comparisons to similar exercise mixes.

### 16.7 Accessory-to-main-lift ratio

Inputs:

- Front squat e1RM: 100 kg × 5 @ RIR 2 → 100 × (1 + 7/30) = 123.33 → 123.3 kg, date 2026-10-20.
- Competition squat e1RM: 140 kg × 3 @ RIR 2 → 140 × (1 + 5/30) = 163.33 → 163.3 kg, date 2026-10-23.

Calculation: 100 × 123.3 / 163.3 = **75.5%**.

Dates: gap = 3 days ≤ 14 → contemporaneous. Both ok; both have ≥2 observations → "moderate confidence".

Do not say "the front squat is 75.5% of the competition squat, therefore the quads are weak". Do say "the ratio of the two estimates is 75.5%; both are estimates and the ratio is descriptive".

If the denominator were 2026-09-01, the gap would be 49 days > 14 → **unavailable** as a current ratio; show it as historical with both dates, or withhold it. Do not divide a recent numerator by an old denominator without a warning.

If the numerator were SSB squat instead of front squat, that is a different configured relationship. Do not infer it from the name.

### 16.8 Power exposure

Inputs: box jump 3 × 5, mean velocities 2.10, 2.05, 1.98 m/s.

- Power sets = **3**.
- Explosive repetitions = **15**.
- Set-to-set retention = 1.98 / 2.10 = 0.9429 → **94.3%** (drop 5.7%).
- Within-set loss: **unavailable** (mean only).
- Quality stop: if no explicit event, **not recorded**. Do not infer "quality maintained" from 94.3%.

If per-rep data exist (2.20, 2.10, 2.00, 1.90, 1.75), first-to-last loss = (2.20 − 1.75) / 2.20 = 20.5%; this is descriptive, not an RIR proxy.

Do not count the 15 reps as 15 hypertrophy working sets. They are power exposure and, where the weekly ledger already includes power_jump, they count in that group.

### 16.9 Spinal exposure

Session: trap bar 4 sets, back extension 3 sets, competition squat 3 sets.

- Base ordinal costs: trap bar 2, back extension 1, competition squat 1.
- The registry applies bounded set-count and intensity policy factors; do not recompute them by hand.
- Suppose the registry returns effective costs 2.00, 0.85, 0.85 → session total **3.70**; weekly total **3.70 / 6.0**.
- Label: "ordinal exposure units, not lumbar load".
- Do not add tonnage or set counts to this number.

---

## 17. Traceability table

| Metric | Purpose | Source data | Calculation | Existing implementation / gap | Evidence | Validation | UI |
|---|---|---|---|---|---|---|---|
| Completed working sets | How much was done | clean_set | Count working rows | _comparison has counts; no monitoring card | ACSM volume | Stage 1 | Card 1 |
| Completed reps | Volume | clean_set | Sum reps (reps unit) | Partial in comparison | ACSM volume | Stage 1 | Card 1 |
| Exercise tonnage | Within-exercise load | clean_set.tonnage_kg | Sum external × reps | session.tonnage_kg exists; no per-exercise display | Mechanics; ACSM | Stage 1/2 | Card 3 |
| Session tonnage | Optional context | clean_set | Sum A1.3 | Session column exists | Mechanics | Stage 2 | Advanced |
| Hard sets | Effort dose | clean_set.rir | Count RIR ≤4 | exposure._hard (private) | ACSM; Robinson | Stage 1 | Card 3 |
| Near-failure sets | Proximity | clean_set.rir | Count RIR ≤2 | Gap | RIR evidence | Stage 1 | Card 3 |
| Pattern distribution | Balance | taxonomy, volume keys | Count by group | volume.compute | Volume evidence | Stage 1 | Card 3 |
| Load-base e1RM | Intensity denominator | clean_set, overrides, calibration, decay | Selector | engine._latest_e1rm (private) | Reynolds; Grgic | Stage 1 | Card 3 |
| Relative intensity | How heavy vs capacity | A2.1 + set load | load/e1RM | Gap | ACSM 80% | Stage 1/2 | Card 3 |
| RI distribution | Range | A2.2 | Count bands | Gap | ACSM | Stage 2 | Card 3 |
| RIR distribution | Proximity profile | clean_set.rir | Counts | Gap | Zourdos; Refalo | Stage 1 | Card 3 |
| RIR coverage | Data quality | clean_set | known/total | Gap | Data quality | Stage 1 | Advanced |
| sRPE | Perceived difficulty | session_feedback | Latest non-null | Exists | Sweet; Day | Stage 1 | Card 5 |
| Duration | Time | feedback/session/workout | Latest non-null | Exists, duplicated | DQ-SESSION-01 | Stage 1 | Card 5 |
| Session load AU | Internal load | sRPE × duration | Multiply | Gap | Sweet | Stage 1 | Card 5 |
| Pre best e1RM | Performance baseline | clean_set | Max eligible, decayed | baseline.best_e1rm (different) | Grgic | Stage 1 | Card 2 |
| Post best e1RM | Performance today | clean_set | Max eligible | Gap | Grgic | Stage 1 | Card 2 |
| e1RM change | Within-session | C1/C2 | Δ, % | Gap | Grgic; measurement logic | Stage 1/2 | Card 2 |
| Source set | Transparency | C4 | Row fields | Gap | — | Stage 1 | Details |
| Exercise identity | Comparability | taxonomy | Exact id | Exists | Spitz; Lockie; Herrera | Stage 1 | Card 2/3 |
| e1RM series | Longitudinal | C6 | Per-session best | progress ratio (different) | Grgic; FFM rejection | Stage 2/3 | Performance |
| Rolling median | Smoother | C6 | Median of last 3 | Gap | Descriptive | Stage 3 | Performance |
| Ratio | Relative strength | C6 + config | num/den ×100 | Gap; programme_slot_of insufficient | PARENT-VARIANT; Parkinson | Stage 1/2/3 | Performance; max 2 on summary |
| Ratio dates | Comparability | C6 | Dates/gap | Gap | Product judgement | Stage 1 | Ratio detail |
| Power sets | Power exposure | clean_set, taxonomy | Count power_jump | derived excludes from RIR; no count | ACSM; Balachandran | Stage 1 | Card 4 |
| Power reps | Power volume | clean_set | Sum reps | Gap | ACSM | Stage 1 | Card 4 |
| Set-to-set retention | Consistency | clean_set.velocity | last/first | rep_velocity has within-set; no power summary | Moura; Jukic | Stage 1/2 | Card 4 |
| Power quality stop | Quality | workout_event/plan | Event/flag | Gap; text only | DEC-POWER-02 | Stage 1 | Card 4 |
| Within-set loss | Not available | mean velocity | — | Explicitly unavailable | DEC-VELOCITY-01 | Stage 1 | "Unavailable" |
| Spinal exposures | Ordinal exposure | clean_set, registry | weekly_spinal_costs | Exists | Swinton; Hanen; Cholewicki | Stage 1 | Card 4 |
| Heavy spinal sets | Context | clean_set | RIR ≤1, 4 weeks | heavy_spinal | SPINAL-COST | Stage 1 | Card 4 |
| Axial demand mix | Qualitative | demands | Count levels | demands | EXERCISE-DEMANDS | Stage 2 | Card 4 |
| Productivity | Subjective usefulness | session_feedback (new) | 1–5 | Gap | No validation | Stage 1 | Card 5 |
| Comparable summary | Historical context | Prior sessions | Median of up to 5 | Gap | Descriptive | Stage 2/3 | Card 6 |
| Feedback completeness | Data quality | feedback/session/workout | Presence flags | Gap | Data quality | Stage 1 | Card 5 |
| e1RM quality/flags | Transparency | C1/C2 | Eligibility/quality | Gap | Grgic; RIR evidence | Stage 1 | Details |

---

## 18. Appendix: glossary, formulas and implementation contracts

### 18.1 Glossary

| Term | Meaning |
|---|---|
| load_base_e1rm | The e1RM the prescription used to solve the load; median selector by default |
| pre_best_e1rm | Best eligible demonstrated estimate before the session; used for the within-session change |
| post_best_e1rm | Best eligible estimate in the session |
| hard set | Working set with RIR ≤ effort_max_rir (default 4) |
| near-failure set | Working set with RIR ≤2 |
| session load | sRPE × duration in minutes, AU |
| relative intensity | Set load / load_base_e1rm |
| relative strength ratio | Configured numerator e1RM / denominator e1RM ×100 |
| power exposure | Count of quality-limited power sets/reps; not hypertrophy volume |
| spinal exposure | Ordinal (session, exercise) cost from the rule registry; not lumbar load |
| productivity | Optional 1–5 self-report of how productive the session felt |
| comparable session | Same type + common main lift + overlap + not deload/technique/minimum + ≥3 priors |

### 18.2 Formulas

    e1RM_epley_rir       = load × (1 + (reps + rir) / 30)
    e1RM_epley           = load × (1 + reps / 30)
    effective_e1RM(t)    = e1RM × decay(age_days) × calibration_factor
    decay(age)           = 1                                   if age <= 21
                         = max(0.90, 1 - 0.01 × (age - 21)/7)  otherwise
    pre_best             = max(effective_e1RM_i) over eligible sets strictly before session
    post_best            = max(e1RM_i) over eligible sets in session
    delta_kg             = post_best - pre_best
    delta_pct            = 100 × delta_kg / pre_best
    relative_intensity   = load / load_base_e1rm
    session_load_au      = sRPE × duration_min
    ratio_pct            = 100 × numerator_e1RM / denominator_e1RM
    tonnage_exercise     = Σ(external_load_kg × reps)
    hard_sets            = count(working sets with 0 <= rir <= effort_max_rir)
    near_failure_sets    = count(working sets with 0 <= rir <= 2)

The constants 21 days, 1%/week and 10% max are the existing e1rm_decay assumptions, not new findings. The 30 and 4.2% references are from the cited literature/implementation, not universal truths.

### 18.3 Pseudocode contracts

    # features/e1rm_source.py
    def select_e1rm(
        conn,
        exercise_id: str,
        on_date: str,
        *,
        session_id: str | None = None,   # exclude this session (strict cutoff)
        estimator: str = "median",        # prescription selector; not the monitoring best
        window_days: int = 84,
        robust_window_days: int = 28,
    ) -> Estimate | Unavailable:
        ...

    # features/monitoring.py
    def pre_best(conn, session_id: str, exercise_id: str) -> Estimate | Unavailable: ...
    def post_best(conn, session_id: str, exercise_id: str) -> Estimate | Unavailable: ...
    def load_base(conn, session_id: str, exercise_id: str) -> Estimate | Unavailable: ...
    def session_load(conn, session_id: str) -> Load | Unavailable: ...
    def relative_intensity(set_row, load_base: Estimate) -> float | Unavailable: ...
    def hard_sets(sets, config) -> HardSetCount: ...
    def exercise_tonnage(sets, exercise_id) -> Tonnage | Unavailable: ...
    def power_exposure(sets, taxonomy) -> PowerExposure: ...
    def spinal_exposure(conn, session_id) -> SpinalExposure: ...  # calls registry

    # features/relative_strength.py
    def ratio(conn, relationship, on_date) -> Ratio | Unavailable:
        # both sides eligible, ok, within max_age, gap <= max_gap
        ...

### 18.4 API contract sketch

    {
      "summary": {
        "workout_id": "…",
        "session_id": "…",
        "for_date": "2026-10-28",
        "session_type": "bench_squat",
        "status": "complete",
        "completion": {
          "planned_sets": 16, "completed_sets": 14, "planned_reps": 70, "completed_reps": 62,
          "items": [{"exercise_id": "bench_press", "status": "complete", "actual": 4, "planned": 4}],
          "substitutions": []
        },
        "strength": [{
          "exercise_id": "bench_press",
          "pre": {"kg": 156.0, "date": "2026-10-20", "method": "epley_plus_rir", "quality": "ok", "source": "set:…"},
          "post": {"kg": 158.7, "set_id": 123, "load_kg": 140, "reps": 3, "rir": 1, "method": "epley_plus_rir", "quality": "ok"},
          "change": {"kg": 2.7, "pct": 1.73, "label": "within_typical_variation"},
          "excluded": [{"set_id": 124, "reason": "rir_above_3"}]
        }],
        "dose": {
          "per_exercise": [{"exercise_id": "bench_press", "sets": 3, "reps": 17, "tonnage_kg": 1980, "hard_sets": 3, "near_failure_sets": 3}],
          "relative_intensity": {"bands": {"heavy": 2, "moderate": 1}, "unknown": 0},
          "rir": {"0": 0, "1": 1, "2": 2, "3": 0, "4": 0, "5": 0, "missing": 0, "warmup": 2},
          "patterns": {"horizontal_push": 3, "squat": 3, "hinge": 3}
        },
        "special": {
          "power": {"sets": 3, "reps": 15, "retention_pct": 94.3, "quality_stop": "not_recorded"},
          "high_intensity": [],
          "spinal": {"exposures": [], "weekly_cost": 3.7, "weekly_cap": 6.0, "heavy_sets": 1}
        },
        "feedback": {
          "srpe": 7, "srpe_timing": "immediate", "duration_min": 65, "duration_source": "measured",
          "session_load_au": 455, "productivity": 4
        },
        "comparison": {"n": 3, "key": "type+main_lift+overlap", "metrics": {}},
        "quality": {"flags": [], "coverage": {"rir": 1.0, "e1rm": 0.67}}
      }
    }

Null means unknown/unavailable; the UI must map it to the correct label. A 0 is a real zero.

### 18.5 What the implementation agent must not decide

The agent implementing an approved phase must not invent:

- the e1RM selector or its window;
- the pre/post estimator (best vs median);
- the cutoff rule;
- the eligibility/quality bands;
- the relative-intensity bands;
- the "meaningful change" threshold;
- the ratio gap/age windows;
- the productivity wording/scale;
- the comparable-session key;
- the decision to add any composite score.

Those are settled here or must be raised as open questions. If a value is missing, return unavailable; do not guess.

### 18.6 Review checklist

- [ ] Does the document distinguish observed, estimated, unknown, not applicable, invalid, unavailable and zero?
- [ ] Is every headline number traceable to a row?
- [ ] Is the pre-session cutoff leakage-proof?
- [ ] Is the load base separate from the best-performance baseline?
- [ ] Is the within-session change labelled as an estimate, not adaptation?
- [ ] Are ratios configured, date-stamped and non-diagnostic?
- [ ] Is power quality explicitly unmeasured without an event?
- [ ] Is the spinal exposure still ordinal?
- [ ] Is productivity optional and outside every calculation?
- [ ] Is there any new composite scalar? (It must be "no".)
- [ ] Is there any automatic prescription change? (It must be "no".)
- [ ] Is every new threshold marked as an assumption?
- [ ] Are the sources verified with DOI/PMID?
- [ ] Does the plan avoid unnecessary migrations?

---

## 19. Related documents

- [Data model](../DATA-MODEL.md)
- [Decisions](../DECISIONS.md)
- [Limitations register](../LIMITATIONS-REGISTER.md)
- [Data quality](../DATA-QUALITY.md)
- [References](../REFERENCES.md)
- [RIR evidence](../RIR-EVIDENCE.md)
- [Fatigue, fitness and strength](../FATIGUE-FITNESS.md)
- [Volume management](../VOLUME-MANAGEMENT.md)
- [Exercise demands](../EXERCISE-DEMANDS.md)
- [Spinal cost](../SPINAL-COST.md)
- [High-intensity exposure](../HIGH-INTENSITY-EXPOSURE-PLAN.md)
- [Parent-variant ratios and weakness](../PARENT-VARIANT-WEAKNESS-EVIDENCE.md)
- [VBT evidence](../VBT-EVIDENCE.md)
- [Per-rep velocity](../REP-VELOCITY.md)
- [Web UI](../WEB-UI.md)
- [UI map](../UI-MAP.md)
- [Methodology](../METHODOLOGY.md)
- [Frequency and volume](../FREQUENCY-AND-VOLUME.md)
- [Privacy](../PRIVACY.md)
- [Repository instructions](../../AGENTS.md)
- [Roadmap](../../ROADMAP.md)

